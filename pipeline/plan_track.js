// 베팅 계획 실전 성적표 (2026-11-14부터: 배당 반영 확률 × 단승 배당 ≥ 1.2 인 말의 단승)
// - 경주 결과가 나오면 그 경주의 확정 단승 배당을 넣었다고 보고 지금 계획(site/assets/planner.js)을 그대로 계산해 정산
//   확률: 그날보다 앞서 학습을 끝낸 배당 반영 모델(site/data/model/mkt_v1.json) + 그날 말 특징(site/data/mkx) × 당일 주로 보정
//   → 과거 검증(pipeline/checks/plan_backtest.js)과 같은 방식을 앞으로의 경주에 적용한 기록. 살 때 배당이 아니라 확정 배당이라 실제보다 유리할 수 있음.
// - 2026-11-15 경주부터 그날 마지막 경주와 1200m 이하 경주는 자동으로 뺌 (11/14 기록은 빼기 전 기준 그대로 둠)
// - 자금 10만 원 · 보통, 하루 안에서는 앞 경주부터 차례로 금액을 정함 (계획과 같음)
// - 2026-11-08 하루는 이전 방식(모델 확률로 조건부 7개 승식, 출발 전 고정) 기록 → 그대로 두고 따로 보여 줌
// 출력: site/data/plan_track/날짜.json, site/data/plan_track/summary.json
// 사용: node pipeline/plan_track.js   (run_all 이 매번 실행)
const fs = require("fs"), path = require("path");
const ROOT = path.resolve(__dirname, "..");
const DATA = path.join(ROOT, "site", "data");
const OUT = path.join(DATA, "plan_track");
const P = require(path.join(ROOT, "site", "assets", "planner.js"));
const MK = require(path.join(ROOT, "site", "assets", "mktmodel.js"));
const START = "20261114";
const BANK = 100000, MODE = "normal";
const TRACK = "ev", LABEL = "단승 기대값 1.2 이상 · 보통";

const rd = f => { try { return JSON.parse(fs.readFileSync(f, "utf8")); } catch { return null; } };
const M = rd(path.join(DATA, "model", "mkt_v1.json"));

fs.mkdirSync(OUT, {recursive: true});
const days = fs.readdirSync(path.join(DATA, "entries")).filter(f => f.endsWith(".json")).map(f => f.slice(0, 8)).filter(d => d >= START).sort();
for (const d of days) {
  const ent = rd(path.join(DATA, "entries", d + ".json")), pred = rd(path.join(DATA, "pred", d + ".json")), X = rd(path.join(DATA, "mkx", d + ".json"));
  if (!ent || !pred) continue;
  const f = path.join(OUT, d + ".json");
  const T = rd(f) || {date: d, bank: BANK, mode: MODE, tracks: {}};
  let changed = false;
  for (const k of Object.keys(T.tracks)) if (k !== TRACK) { delete T.tracks[k]; changed = true; }   // 이전 방식의 출발 전 기록 (이날부터는 쓰지 않음)
  const t = T.tracks[TRACK] ||= {label: LABEL, races: {}};
  if (!M || !X || !(String(M.trained_through) < d)) { if (changed) fs.writeFileSync(f, JSON.stringify(T)); continue; }   // 모델이 이날을 학습했으면 기록하지 않음
  const bias = rd(path.join(DATA, "bias", d + ".json"));
  const raceNos = [...new Set(ent.rows.map(r => +r.rcNo))].sort((a, b) => a - b);
  // 결과가 나온 경주까지 (앞 경주부터 차례로 금액을 정하므로, 중간에 결과가 빠진 경주가 있으면 거기서 멈춤)
  const inputs = [];
  for (const n of raceNos) {
    const r = pred.races?.[n];
    if (!r) break;
    if (r.void) { inputs.push({race: n, void: r.void}); continue; }
    if (!r.result?.length || r.partial) break;                                // partial: 1~3착만 올라온 상태 (나머지 말이 아직 정리되지 않음)
    const out = (r.out || []).map(String), ids = Object.keys(r.p || {}).filter(k => !out.includes(k));
    const odds = Object.fromEntries(ids.map(i => [i, +r.odds?.[i]]));
    let pm = MK.predict(M, X.races?.[n], odds, ids);
    if (!pm) break;                                                           // 확정 배당이 아직 모두 들어오지 않음
    const bf = bias?.races?.[n]?.f || {}, v = Object.fromEntries(ids.map(i => [i, pm[i] * (bf[i] ?? 1)])), s = Object.values(v).reduce((a, b) => a + b, 0);
    pm = Object.fromEntries(ids.map(i => [i, v[i] / s]));
    inputs.push({race: n, pm, odds, out: r.out, result: r.result, dist: +ent.rows.find(x => +x.rcNo === n)?.rcDist || 0});
  }
  // 마지막 경주·1200m 이하는 planner 가 자동으로 뺌 (2026-11-15 경주부터; 그날 모든 경주 결과가 나와야 마지막 경주를 앎 → 그 전에는 마지막 번호 경주를 기다림)
  const lastNo = Math.max(...raceNos.filter(n => !pred.races?.[n]?.void));
  for (const x of inputs) x.last = x.race === lastNo;
  const pl = P.plan(inputs, {bankroll: BANK, mode: MODE});
  for (const pr of pl.races) {
    const n = pr.race, inp = inputs.find(x => x.race === n);
    if (t.races[n]) continue;
    let x;
    if (inp.void) x = {skip: "경주 취소"};
    else if (pr.off) x = {skip: pr.skip, off: pr.off};
    else if (!pr.bets) x = {skip: pr.skip, top: inp.pm ? +Math.max(...Object.keys(inp.pm).map(i => inp.pm[i] * inp.odds[i])).toFixed(3) : null};
    else {
      let spent = 0, ret = 0;
      const bets = pr.bets.map(b => {
        const hit = +b.key === inp.result[0], fo = inp.odds[b.key];
        spent += b.stake; if (hit) ret += b.stake * fo;
        return {key: b.key, stake: b.stake, odds: fo, p: +b.p.toFixed(4), ev: +b.ev.toFixed(3), res: hit ? "적중" : "미적중"};
      });
      x = {bets, settle: {spent, ret: Math.round(ret)}};
    }
    t.races[n] = x; changed = true;
  }
  if (changed) fs.writeFileSync(f, JSON.stringify(T));
}
// 누적 (이전 방식 기록은 old 로 따로)
const sum = {start: START, bank: BANK, mode: MODE, tracks: {}, old: {}};
for (const f of fs.readdirSync(OUT).filter(x => /^\d{8}\.json$/.test(x)).sort()) {
  const T = rd(path.join(OUT, f));
  for (const [tk, t] of Object.entries(T.tracks)) {
    const isNew = T.date >= START && tk === TRACK;
    const box = isNew ? sum.tracks : sum.old;
    const s = box[tk] ||= {label: t.label, days: [], spent: 0, ret: 0, bets: 0, hits: 0, races: 0, skipped: 0, pending: 0};
    let ds = 0, dr = 0, dn = 0;
    for (const x of Object.values(t.races)) {
      if (!x.bets) { s.skipped++; continue; }
      if (!x.settle) { s.pending++; continue; }
      s.races++; ds += x.settle.spent; dr += x.settle.ret;
      for (const b of x.bets) if (b.res === "적중" || b.res === "미적중") { s.bets++; dn++; if (b.res === "적중") s.hits++; }
    }
    s.spent += ds; s.ret += dr;
    if (ds || dn) s.days.push({date: T.date, spent: ds, ret: dr});
  }
}
for (const s of Object.values(sum.old)) { s.pending = 0; s.ended = "20261108"; }   // 이전 방식은 11/8 하루로 끝 (나머지 대기 기록은 지움)
fs.writeFileSync(path.join(OUT, "summary.json"), JSON.stringify(sum));
console.log("베팅 계획 기록:", Object.values(sum.tracks).map(s => `${s.label} 산 ${s.spent} 환급 ${s.ret} (${s.races}경주, 건너뜀 ${s.skipped})`).join(" / ") || "아직 없음");
