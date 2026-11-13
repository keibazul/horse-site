// 베팅 계획(site/assets/planner.js)을 지난 경주일에 그대로 적용해 본 결과 (2026-11-13: 배당 반영 확률로 단승)
// - 자료: work/backtest/mkt_win.json.gz (work/backtest_mkt_data.py) — 2016~2026 경주마다 연도별 표본외 배당 반영 확률
//   (그 전 해까지 학습한 모델), 확정 단승 배당, 1착. 코로나 무관중(2020-02-23~2021-10-31) 제외.
// - 단승 배당은 마감 후 확정 배당을 넣었다고 가정 (실제로는 산 뒤에도 배당이 바뀜 → 이 결과는 실제보다 유리하게 나올 수 있음)
// - 하루마다 같은 자금으로 시작 (전날 손익을 이어 가지 않음)
// 사용: node pipeline/checks/plan_backtest.js [--mode normal] [--bank 100000] [--flat yes] [--json out.json]
//       node pipeline/checks/plan_backtest.js --site site/data/plan_check.json   (사이트 표: 네 가지 설정)
const fs = require("fs"), path = require("path"), zlib = require("zlib");
const ROOT = path.resolve(__dirname, "../..");
const P = require(path.join(ROOT, "site/assets/planner.js"));
const arg = (k, d) => { const i = process.argv.indexOf("--" + k); return i > 0 ? process.argv[i + 1] : d; };
if (arg("value")) Object.assign(P.VALUE, JSON.parse(arg("value")));
const days = JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(ROOT, "work/backtest/mkt_win.json.gz"))).toString("utf8"));
const half = d => d < "20230101" ? "2016~2022" : "2023~2026";

function run(mode, bankroll, flat) {
  const per = {};          // 기간·연도별 [건 수, 적중, 구매, 환급]
  const byDay = [];
  const add = (k, n, h, s, r) => { const o = per[k] ||= [0, 0, 0, 0]; o[0] += n; o[1] += h; o[2] += s; o[3] += r; };
  for (const d of Object.keys(days).sort()) {
    const R = days[d];
    const races = Object.entries(R).map(([n, r]) => ({race: +n, pm: r.p, odds: r.odds}));
    const pl = P.plan(races, {bankroll, mode});
    let ds = 0, dr = 0, dn = 0, dh = 0;
    for (const x of pl.races) {
      if (!x.bets) continue;
      const r = R[x.race];
      for (const b of x.bets) {
        const s = flat ? 1 : b.stake, win = r.win === +b.key, v = win ? s * r.odds[b.key] : 0;
        ds += s; dr += v; dn++; dh += win;
      }
    }
    add("전체", dn, dh, ds, dr); add(half(d), dn, dh, ds, dr); add(d.slice(0, 4), dn, dh, ds, dr);
    byDay.push({d, half: half(d), s: ds, r: dr});
  }
  let seed = 7; const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  function ci(list) {     // 경주일 단위로 다시 뽑기 (같은 날 마권끼리 묶임)
    const b = [];
    for (let it = 0; it < 2000; it++) { let s = 0, r = 0; for (let i = 0; i < list.length; i++) { const x = list[Math.floor(rnd() * list.length)]; s += x.s; r += x.r; } b.push(s ? r / s : 0); }
    b.sort((a, c) => a - c); return [b[50], b[1950]];
  }
  const row = (k, list) => { const [n, h, s, r] = per[k] || [0, 0, 0, 0]; return {label: k, bets: n, hits: h, stake: Math.round(s), ret: Math.round(r), roi: s ? r / s : null, ci: list ? ci(list) : null}; };
  const st = byDay.map(x => x.s).sort((a, b) => a - b);
  return {mode, bankroll, flat, value: {...P.VALUE}, days: byDay.length, races: Object.values(days).reduce((a, R) => a + Object.keys(R).length, 0),
    rows: [row("전체", byDay), row("2016~2022", byDay.filter(x => x.half === "2016~2022")), row("2023~2026", byDay.filter(x => x.half === "2023~2026"))],
    years: Object.keys(per).filter(k => /^\d{4}$/.test(k)).sort().map(k => row(k)),
    perDayStake: Math.round(per["전체"][2] / byDay.length), medianDayStake: st[st.length >> 1], maxDayStake: st[st.length - 1],
    betDays: byDay.filter(x => x.s > 0).length, loseDays: byDay.filter(x => x.s > 0 && x.r < x.s).length};
}
const r4 = o => JSON.stringify(o, (k, v) => typeof v === "number" ? Math.round(v * 1000) / 1000 : v);
if (arg("site")) {
  // 사이트 표 (site/data/plan_check.json): 1장씩, 조심스럽게, 보통, 자금 모두 쓰기 — 자금 10만 원
  const C = [["flat", "100원씩", "normal", true], ["safe", "조심스럽게", "safe", false], ["normal", "보통", "normal", false], ["all", "자금 모두 쓰기", "all", false]];
  const res = C.map(([key, label, mode, flat]) => ({key, label, ...run(mode, 100000, flat)}));
  const first = Object.keys(days).sort()[0], last = Object.keys(days).sort().pop();
  const out = {version: 2, made: new Date().toISOString().slice(0, 10), first, last, days: res[0].days, races: res[0].races, value: P.VALUE, bankroll: 100000,
    configs: res.map(({key, label, rows, perDayStake, medianDayStake, maxDayStake, betDays, loseDays}) => ({key, label, rows, perDayStake, medianDayStake, maxDayStake, betDays, loseDays})),
    years: res[0].years.map(y => ({label: y.label, bets: y.bets, hits: y.hits, roi: y.roi}))};
  fs.writeFileSync(arg("site"), r4(out));
  for (const c of out.configs) console.log(c.label.padEnd(10), c.rows.map(x => `${x.label} ${x.bets}장 ${(x.roi * 100).toFixed(1)}% [${(x.ci[0] * 100).toFixed(0)}, ${(x.ci[1] * 100).toFixed(0)}]`).join(" | "), `하루 평균 ${c.perDayStake} 중앙 ${c.medianDayStake} 최대 ${c.maxDayStake} 손실일 ${c.loseDays}/${c.betDays}`);
} else {
  const out = run(arg("mode", "normal"), +arg("bank", "100000"), arg("flat", "no") === "yes");
  console.log(JSON.stringify(JSON.parse(r4(out)), null, 1));
  if (arg("json")) fs.writeFileSync(arg("json"), JSON.stringify(out));
}
