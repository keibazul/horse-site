// 베팅 계획 '지난 경주일 연습 보기' 모아 보기 (2026-11-18)
// site/data/plan_past/날짜.json 이 있는 날(11/14 전 지난 1년)을 자금 10만 원·보통으로 계산한 날별 산 금액·환급 → site/data/plan_past/summary.json
// 확률 = 연도별 표본외 배당 반영 확률(work/backtest/mkt_win.json.gz), 확정 단승 배당, 마지막 경주·1200m 이하 자동 제외 — 화면의 연습 보기와 같은 계산
// 사용: node pipeline/checks/plan_past_summary.js   (work/export_plan_past.py 다음에)
const fs = require("fs"), path = require("path"), zlib = require("zlib");
const ROOT = path.resolve(__dirname, "../..");
const P = require(path.join(ROOT, "site/assets/planner.js"));
const D = JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(ROOT, "work/backtest/mkt_win.json.gz"))));
const A = JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(ROOT, "work/backtest/race_attrs.json.gz"))));
const dir = path.join(ROOT, "site/data/plan_past");
const days = fs.readdirSync(dir).filter(f => /^\d{8}\.json$/.test(f)).map(f => f.slice(0, 8)).sort();
const out = {bank: 100000, mode: "normal", days: []};
for (const d of days) {
  const R = D[d]; if (!R) continue;
  const pl = P.plan(Object.entries(R).map(([n, r]) => ({race: +n, pm: r.p, odds: r.odds, dist: A[d]?.[n]?.[0], last: !!A[d]?.[n]?.[1]})), {bankroll: out.bank, mode: out.mode});
  let s = 0, r = 0, b = 0, h = 0;
  for (const x of pl.races) if (x.bets) for (const k of x.bets) { s += k.stake; b++; if (R[x.race].win === +k.key) { r += k.stake * R[x.race].odds[k.key]; h++; } }
  out.days.push({d, s, r: Math.round(r), b, h});
}
const sum = k => out.days.reduce((a, x) => a + x[k], 0);
out.total = {days: out.days.length, betDays: out.days.filter(x => x.s).length, hitDays: out.days.filter(x => x.h).length, bets: sum("b"), hits: sum("h"), spent: sum("s"), ret: sum("r")};
fs.writeFileSync(path.join(dir, "summary.json"), JSON.stringify(out));
console.log(out.total, "회수율", (out.total.ret / out.total.spent * 100).toFixed(1) + "%");
