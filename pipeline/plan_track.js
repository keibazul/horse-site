// 베팅 계획 실전 성적표
// - 경주마다 출발 전 마지막 계획(모델 확률, 배당 안 넣음 = '조건만')을 고정 저장
// - 결과가 나오면 확정 배당으로 정산: 조합의 확정 배당이 최소 배당 이상이면 산 것으로 보고 적중이면 금액 × 확정 배당
// - 두 가지 설정: 단승·연승 / 7개 승식, 자금 10만 원·보통
// 출력: site/data/plan_track/날짜.json, site/data/plan_track/summary.json
// 사용: node pipeline/plan_track.js   (run_all 이 매번 실행)
const fs = require("fs"), path = require("path"), zlib = require("zlib");
const ROOT = path.resolve(__dirname, "..");
const DATA = path.join(ROOT, "site", "data");
const OUT = path.join(DATA, "plan_track");
const P = require(path.join(ROOT, "site", "assets", "planner.js"));
const START = "20261108";                       // 이날 경주부터 기록 (6R 부터)
const TRACKS = {wp: {label: "단승·연승", pools: ["단승식", "연승식"]}, all: {label: "7개 승식", pools: P.POOLS}};
const BANK = 100000, MODE = "normal", MARGIN = 0.1, FREEZE_MIN = 3;   // 출발 3분 전부터 고정

const rd = f => { try { return JSON.parse(fs.readFileSync(f, "utf8")); } catch { return null; } };
const kst = () => new Date(Date.now() + 9 * 3600e3);                  // UTC 시각을 한국 시각처럼 다룸
const ymd = d => d.toISOString().slice(0, 10).replace(/-/g, "");
const stMin = r => { const m = String(r?.stTime ?? "").match(/(\d{1,2}):?(\d{2})/); return m ? +m[1] * 60 + +m[2] : null; };
const key = (pool, nums) => (pool === "쌍승식" || pool === "삼쌍승식") ? nums.join(">") : [...nums].sort((a, b) => a - b).join("-");
function fullOdds(d) {
  const f = path.join(ROOT, "work", "odds_full", d + ".csv.gz");
  if (!fs.existsSync(f)) return null;
  const o = {};
  for (const line of zlib.gunzipSync(fs.readFileSync(f)).toString("utf8").trim().split("\n").slice(1)) {
    const [rc, pool, a, b, c, od] = line.split(",");
    ((o[+rc] ||= {})[pool] ||= {})[key(pool, [a, b, c].map(Number).filter(x => x > 0))] = +od;
  }
  return o;
}
function wins(pool, k, res, n) {
  const nums = k.split(/[>-]/).map(Number), top = res.slice(0, 3);
  switch (pool) {
    case "단승식": return nums[0] === res[0];
    case "연승식": return res.slice(0, n >= 8 ? 3 : 2).includes(nums[0]);
    case "복승식": return nums.every(x => res.slice(0, 2).includes(x));
    case "쌍승식": return nums[0] === res[0] && nums[1] === res[1];
    case "복연승식": case "삼복승식": return nums.every(x => top.includes(x));
    case "삼쌍승식": return nums[0] === res[0] && nums[1] === res[1] && nums[2] === res[2];
  }
  return false;
}

fs.mkdirSync(OUT, {recursive: true});
const now = kst(), today = ymd(now), nowMin = now.getUTCHours() * 60 + now.getUTCMinutes();
const days = fs.readdirSync(path.join(DATA, "entries")).filter(f => f.endsWith(".json")).map(f => f.slice(0, 8)).filter(d => d >= START).sort();
for (const d of days) {
  const ent = rd(path.join(DATA, "entries", d + ".json")), pred = rd(path.join(DATA, "pred", d + ".json"));
  if (!ent || !pred) continue;
  const f = path.join(OUT, d + ".json");
  const T = rd(f) || {date: d, bank: BANK, mode: MODE, tracks: {}};
  const raceNos = [...new Set(ent.rows.map(r => +r.rcNo))].sort((a, b) => a - b);
  const startOf = Object.fromEntries(raceNos.map(n => [n, stMin(ent.rows.find(r => +r.rcNo === n))]));
  const bias = rd(path.join(DATA, "bias", d + ".json"));
  const inputs = raceNos.map(n => {
    const r = pred.races?.[n] || {}, live = Object.keys(r.p || {}).filter(k => !(r.out || []).map(String).includes(k));
    const bf = bias?.races?.[n]?.f || {}, p = Object.fromEntries(Object.entries(r.p || {}).map(([k, v]) => [k, v * (bf[k] ?? 1)]));
    return {race: n, p, out: r.out, void: r.void, nDebut: live.filter(k => (r.n || {})[k] === 0).length};
  });
  let changed = false;
  for (const [tk, tr] of Object.entries(TRACKS)) {
    const t = T.tracks[tk] ||= {label: tr.label, races: {}};
    const pl = P.plan(inputs, {bankroll: BANK, mode: MODE, pools: tr.pools, margin: MARGIN});
    for (const pr of pl.races) {
      const n = pr.race, cur = t.races[n];
      const before = d > today || (d === today && startOf[n] != null && nowMin < startOf[n] - FREEZE_MIN);
      const late = d === START && startOf[n] != null && !t.races[n] && !before;   // 첫날 이미 출발한 경주는 기록하지 않음
      if (before && !pred.races?.[n]?.result) {
        const snap = pr.bets ? {bets: pr.bets.map(b => ({pool: b.pool, key: b.key, stake: b.stake, minOdds: b.minOdds, p: +b.p.toFixed(4)}))} : {skip: pr.skip};
        snap.at = now.toISOString().slice(0, 16).replace("T", " ");
        if (JSON.stringify({...cur, at: 0, settle: 0}) !== JSON.stringify({...snap, at: 0, settle: 0})) { t.races[n] = snap; changed = true; }
      } else if (late) { /* 기록 시작 전 경주 */ }
    }
  }
  // 정산
  const res = Object.values(pred.races || {}).some(r => r.result);
  const full = res ? fullOdds(d) : null;
  for (const t of Object.values(T.tracks)) {
    for (const [n, x] of Object.entries(t.races)) {
      const r = pred.races?.[n];
      if (x.settle || !r || !(r.result || r.void) || !x.bets) {
        if (x.bets && r?.void && !x.settle) { x.settle = {spent: 0, ret: 0, void: true}; changed = true; }
        continue;
      }
      const nRun = Object.keys(r.p).length - (r.out || []).length;
      const needFull = x.bets.some(b => b.pool !== "단승식" && b.pool !== "연승식");
      if (needFull && !full) continue;                                      // 모든 조합 배당을 받은 뒤 정산
      let spent = 0, ret = 0;
      for (const b of x.bets) {
        const fo = b.pool === "단승식" ? r.odds?.[b.key] : b.pool === "연승식" ? r.plc?.[b.key] : full?.[n]?.[b.pool]?.[b.key];
        const out = (r.out || []).map(String);
        if (b.key.split(/[>-]/).some(k => out.includes(k))) { b.res = "환불"; continue; }
        if (!(fo >= b.minOdds)) { b.res = fo ? `안 삼(${fo})` : "안 삼"; continue; }
        spent += b.stake; b.fo = fo;
        if (wins(b.pool, b.key, r.result, nRun)) { b.res = "적중"; ret += b.stake * fo; } else b.res = "미적중";
      }
      x.settle = {spent, ret: Math.round(ret)}; changed = true;
    }
  }
  if (changed) fs.writeFileSync(f, JSON.stringify(T));
}
// 누적
const sum = {start: START, bank: BANK, mode: MODE, tracks: {}};
for (const f of fs.readdirSync(OUT).filter(x => /^\d{8}\.json$/.test(x)).sort()) {
  const T = rd(path.join(OUT, f));
  for (const [tk, t] of Object.entries(T.tracks)) {
    const s = sum.tracks[tk] ||= {label: t.label, days: [], spent: 0, ret: 0, bets: 0, hits: 0, races: 0, skipped: 0, pending: 0};
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
fs.writeFileSync(path.join(OUT, "summary.json"), JSON.stringify(sum));
console.log("베팅 계획 기록:", Object.values(sum.tracks).map(s => `${s.label} 산 ${s.spent} 환급 ${s.ret} 대기 ${s.pending}`).join(" / "));
