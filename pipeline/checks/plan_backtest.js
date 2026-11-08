// 베팅 계획(site/assets/planner.js)을 지난 경주일에 그대로 적용해 본 결과
// - 예측: site/data/pred (그날보다 앞서 학습을 끝낸 모델만, 표본외)
// - 단승 배당을 넣은 경우는 마감 후 확정 단승 배당을 넣었다고 가정 (실제로는 산 뒤에 배당이 바뀜 → 이 결과는 조금 유리하게 나옴)
// - 조건부 마권은 그 조합의 확정 배당이 최소 배당 이상일 때만 샀다고 보고, 확정 배당으로 정산
// 사용: node pipeline/checks/plan_backtest.js [--odds yes|no] [--mode normal] [--margin 0.1] [--pools 단승식,연승식,...] [--json out.json]
const fs = require("fs"), path = require("path"), zlib = require("zlib");
const ROOT = path.resolve(__dirname, "../..");
const P = require(path.join(ROOT, "site/assets/planner.js"));
const arg = (k, d) => { const i = process.argv.indexOf("--" + k); return i > 0 ? process.argv[i + 1] : d; };
const useOdds = arg("odds", "yes") === "yes", mode = arg("mode", "normal"), margin = +arg("margin", "0.1");
const pools = arg("pools", P.POOLS.join(",")).split(","), bankroll = +arg("bank", "100000");
if (arg("rules")) Object.assign(P.RULES, JSON.parse(arg("rules")));

const key = (pool, nums) => (pool === "쌍승식" || pool === "삼쌍승식") ? nums.join(">") : [...nums].sort((a, b) => a - b).join("-");
function loadOdds(d) {
  const f = path.join(ROOT, "work/odds_full", d + ".csv.gz");
  if (!fs.existsSync(f)) return null;
  const t = zlib.gunzipSync(fs.readFileSync(f)).toString("utf8").trim().split("\n").slice(1);
  const o = {};
  for (const line of t) {
    const [rc, pool, a, b, c, od] = line.split(",");
    const nums = [a, b, c].map(Number).filter(x => x > 0);
    ((o[+rc] ||= {})[pool] ||= {})[key(pool, nums)] = +od;
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
    case "복연승식": return nums.every(x => top.includes(x));
    case "삼복승식": return nums.every(x => top.includes(x));
    case "삼쌍승식": return nums[0] === res[0] && nums[1] === res[1] && nums[2] === res[2];
  }
}

const days = fs.readdirSync(path.join(ROOT, "site/data/pred")).filter(f => f.endsWith(".json")).map(f => f.slice(0, 8)).sort();
const byPool = {}, byDay = [];
let stake = 0, ret = 0, nBet = 0, nHit = 0, racesBet = 0, racesAll = 0, skipped = {}, noOdds = 0;
for (const d of days) {
  const pr = JSON.parse(fs.readFileSync(path.join(ROOT, "site/data/pred", d + ".json"), "utf8"));
  if (!pr.backtestDone || !(pr.trained_through && pr.trained_through < d)) continue;
  let full = loadOdds(d);
  if (!full && pools.some(p => p !== "단승식" && p !== "연승식")) { noOdds++; continue; }
  full ||= {};
  const races = Object.entries(pr.races).filter(([, r]) => r.result || r.void).map(([rno, r]) => {
    const out = (r.out || []).map(String);
    const live = Object.keys(r.p || {}).filter(k => !out.includes(k));
    return {race: +rno, p: r.p, odds: useOdds ? r.odds : null, out: r.out, void: r.void,
      nDebut: live.filter(k => (r.n || {})[k] === 0).length, _r: r};
  });
  const pl = P.plan(races.map(({_r, ...x}) => x), {bankroll, mode, pools, margin});
  let ds = 0, dr = 0;
  for (const R of pl.races) {
    racesAll++;
    const r = pr.races[R.race];
    if (!R.bets) { skipped[R.skip.replace(/\d+/g, "n")] = (skipped[R.skip.replace(/\d+/g, "n")] || 0) + 1; continue; }
    let bought = 0;
    const n = Object.keys(r.p).length - (r.out || []).length;
    for (const b of R.bets) {
      const fo = b.pool === "단승식" ? r.odds?.[b.key] : b.pool === "연승식" ? r.plc?.[b.key] : full[R.race]?.[b.pool]?.[b.key];
      if (!(fo >= b.minOdds)) continue;                       // 조건 안 맞으면 안 삼
      bought++; nBet++; stake += b.stake; ds += b.stake;
      const st = byPool[b.pool] ||= {n: 0, hit: 0, s: 0, r: 0};
      st.n++; st.s += b.stake;
      if (wins(b.pool, b.key, r.result, n)) { const v = b.stake * fo; ret += v; dr += v; st.r += v; st.hit++; nHit++; }
    }
    if (bought) racesBet++;
  }
  byDay.push([ds, dr]);
}
// 경주일 단위 부트스트랩 95% 구간
let rng = 7; const rnd = () => (rng = (rng * 1103515245 + 12345) % 2147483648) / 2147483648;
const boots = [];
for (let it = 0; it < 2000; it++) { let s = 0, r = 0; for (let i = 0; i < byDay.length; i++) { const x = byDay[Math.floor(rnd() * byDay.length)]; s += x[0]; r += x[1]; } boots.push(s ? r / s : 0); }
boots.sort((a, b) => a - b);
const out = {useOdds, mode, margin, days: byDay.length, noOddsDays: noOdds, races: racesAll, racesBet, bets: nBet, hits: nHit, stake, ret: Math.round(ret),
  roi: stake ? ret / stake : null, ci: [boots[50], boots[1950]], perDayStake: Math.round(stake / Math.max(1, byDay.length)), byPool, skipped};
console.log(JSON.stringify(out, (k, v) => typeof v === "number" ? Math.round(v * 1000) / 1000 : v, 1));
if (arg("json")) fs.writeFileSync(arg("json"), JSON.stringify(out));
