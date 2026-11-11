/* 베팅 계획 계산 (사이트 plan.html 과 과거 검증 pipeline/checks/plan_backtest.js 가 같이 씀)

   경주마다
   1) 확률: 모델 확률(경주 전 정보만). 배당을 섞은 결합 확률은 시장과 거의 같아져서 '싼 마권'을 찾는 데는 쓰지 않음
      (지난 1년 검증: 결합 확률 × 배당 ≥ 1.1 인 마권은 거의 없었고, 있던 것도 크게 잃음)
   2) 승식별 후보: 모델 확률 높은 조합 몇 개 (하빌 방식, 2착 0.8·3착 0.7 보정)
   3) 걸 만한지: 조합 확률이 승식별 최소 확률 이상이고, 배당이 '최소 배당'((1+여유)/모델 확률) 이상이어야 함
        - 단승 배당을 넣은 경주: 단승은 넣은 배당으로 바로 판단, 다른 승식은 단승 배당으로 추정한 배당이 최소 배당에 크게 못 미치면 뺌
        - 모든 마권은 '배당판에서 그 조합 배당이 최소 배당 이상일 때만 사기' 조건부
        - 배당판에서 본 그 조합의 배당(race.board)을 넣으면: 최소 배당 이상이면 '사기'(금액 그대로), 미만이면 '넘기기'(passed).
          넘긴 마권의 돈은 다른 마권으로 옮기지 않음 (배당을 넣을 때마다 이미 산 마권의 금액이 바뀌지 않게)
   4) 금액: 켈리 기준(확률·배당으로 정한 자금 비율)의 일부. 최소 배당에서 산다고 보고 계산(보수적)
   5) 한 경주 합계는 법정 상한 10만 원 이하, 하루 합계는 입력한 자금 이하, 100원 단위
   걸 만한 조합이 없으면 그 경주는 건너뜀(이유 표시).  */
(function (root) {
  "use strict";
  const ALPHA = 0.1689, BETA = 0.9219, GAMMA = 0.8, DELTA = 0.7;
  const RACE_CAP = 100000, UNIT = 100;
  const POOLS = ["단승식", "연승식", "복승식", "쌍승식", "복연승식", "삼복승식", "삼쌍승식"];
  const PAYOUT = {"단승식": 0.8, "연승식": 0.8, "복승식": 0.73, "쌍승식": 0.73, "복연승식": 0.73, "삼복승식": 0.73, "삼쌍승식": 0.73};
  // 승식별: 살펴볼 조합 수, 최소 조합 확률 (확률이 낮은 고배당일수록 과거에 손실이 컸음)
  const RULES = {
    "단승식": {k: 2, minP: 0.20}, "연승식": {k: 2, minP: 0.45},
    "복승식": {k: 2, minP: 0.08}, "쌍승식": {k: 2, minP: 0.05}, "복연승식": {k: 2, minP: 0.15},
    "삼복승식": {k: 2, minP: 0.04}, "삼쌍승식": {k: 2, minP: 0.012}
  };
  const MODES = {safe: 0.125, normal: 0.25, all: 0.25};

  function norm(o) { const s = Object.values(o).reduce((a, b) => a + b, 0); const r = {}; for (const k in o) r[k] = o[k] / s; return r; }

  /** 결합 확률 (모델 p, 단승 배당 odds; 둘 다 {번호: 값}) */
  function combine(p, odds) {
    const ids = Object.keys(p);
    const q = norm(Object.fromEntries(ids.map(i => [i, 1 / odds[i]])));
    const v = Object.fromEntries(ids.map(i => [i, Math.exp(ALPHA * Math.log(Math.max(p[i], 1e-9)) + BETA * Math.log(q[i]))]));
    return {comb: norm(v), market: q};
  }

  /** 하빌 조합 확률: {승식: Map(키 → 확률)} 키는 "3" / "3-7" / "3>7" / "2-3-7" / "3>7>2" */
  function combos(P) {
    const ids = Object.keys(P).map(Number), n = ids.length, p = ids.map(i => P[i]);
    const pw = e => { const v = p.map(x => Math.pow(x, e)), s = v.reduce((a, b) => a + b, 0); return v.map(x => x / s); };
    const q = pw(GAMMA), r = pw(DELTA);
    const out = Object.fromEntries(POOLS.map(k => [k, new Map()]));
    const add = (m, k, v) => m.set(k, (m.get(k) || 0) + v);
    const placeN = n <= 7 ? 2 : 3;
    for (let a = 0; a < n; a++) {
      add(out["단승식"], `${ids[a]}`, p[a]);
      for (let b = 0; b < n; b++) { if (b === a) continue;
        const pab = p[a] * q[b] / (1 - q[a]);
        add(out["쌍승식"], `${ids[a]}>${ids[b]}`, pab);
        add(out["복승식"], [ids[a], ids[b]].sort((x, y) => x - y).join("-"), pab);
        if (placeN === 2) { add(out["연승식"], `${ids[a]}`, pab); add(out["연승식"], `${ids[b]}`, pab); }
        if (n < 3) continue;
        for (let c = 0; c < n; c++) { if (c === a || c === b) continue;
          const v = pab * r[c] / (1 - r[a] - r[b]);
          add(out["삼쌍승식"], `${ids[a]}>${ids[b]}>${ids[c]}`, v);
          const s3 = [ids[a], ids[b], ids[c]].sort((x, y) => x - y);
          add(out["삼복승식"], s3.join("-"), v);
          if (placeN === 3) { add(out["연승식"], `${ids[a]}`, v); add(out["연승식"], `${ids[b]}`, v); add(out["연승식"], `${ids[c]}`, v); }
          add(out["복연승식"], `${s3[0]}-${s3[1]}`, v); add(out["복연승식"], `${s3[0]}-${s3[2]}`, v); add(out["복연승식"], `${s3[1]}-${s3[2]}`, v);
        }
      }
    }
    return out;
  }
  const ceil1 = x => Math.ceil(x * 10 - 1e-9) / 10;
  const keyNums = k => k.split(/[>-]/).map(Number);

  /** 한 경주의 후보 마권 (금액 전)
      race = {race, p:{번호:모델확률}, odds?:{번호:단승배당}, board?:{"승식:조합키":배당판 배당}, out?:[번호], nDebut?:수, nRunners?:수, done?:bool, void?:str}
      opt  = {pools:[승식], margin:0.1} */
  function candidates(race, opt) {
    const out = new Set((race.out || []).map(String));
    const p0 = {}; for (const [k, v] of Object.entries(race.p || {})) if (!out.has(String(k))) p0[k] = Math.max(+v, 1e-6);
    const ids = Object.keys(p0);
    if (race.void) return {skip: race.void};
    if (race.done) return {skip: "끝난 경주"};
    if (ids.length < 3) return {skip: "출전마가 너무 적음"};
    const P = norm(p0);
    const odds = race.odds || {}, haveOdds = ids.every(i => +odds[i] > 1);
    let M = null, CB = null;
    if (haveOdds) { const c = combine(P, Object.fromEntries(ids.map(i => [i, +odds[i]]))); M = c.market; CB = c.comb; }
    const F = P, src = haveOdds ? "odds" : "model";
    const top = Math.max(...Object.values(F));
    if (race.nDebut != null && race.nDebut * 2 >= ids.length) return {skip: `첫 출전 말이 ${race.nDebut}두라 예측을 믿기 어려움`, src, top};
    const m = opt.margin ?? 0.1;
    const C = combos(F), CM = M ? combos(M) : null;
    const bets = [], why = [], board = race.board || {};
    for (const pool of opt.pools || ["단승식", "연승식", "복승식", "삼복승식"]) {
      const R = RULES[pool];
      const list = [...C[pool].entries()].sort((a, b) => b[1] - a[1]).slice(0, R.k);
      for (const [key, pr] of list) {
        if (pr < R.minP) { why.push("prob"); continue; }
        const minOdds = Math.max(1.1, ceil1((1 + m) / pr));
        let cur = null, est = null;
        const bo = +board[`${pool}:${key}`], seen = bo >= 1;          // 배당판에서 본 이 조합의 배당
        if (seen) cur = bo;
        else if (pool === "단승식" && haveOdds) cur = +odds[key];
        else if (CM) { const qm = CM[pool].get(key); if (qm) est = PAYOUT[pool] / qm; }
        const bet = {pool, key, nums: keyNums(key), p: pr, minOdds, cur, est, seen, pc: CB && pool === "단승식" ? CB[key] : null};
        if (seen) { bet.pass = cur < minOdds; bets.push(bet); continue; }      // 배당판 값을 넣은 줄은 넘기더라도 남겨 둠 (금액 배분은 그대로, 표시는 '넘기기')
        if (cur != null && cur < minOdds) { why.push("value"); continue; }
        if (est != null && est < minOdds * 0.9) { why.push("value"); continue; }
        bets.push(bet);
      }
    }
    if (!bets.length) {
      const reason = why.includes("value") ? "모델 확률에 비해 배당이 낮음 (인기가 이미 몰림)" : (top < 0.25 ? `혼전 (모델 1순위 ${Math.round(top * 100)}%)` : "기준을 넘는 조합 없음");
      return {skip: reason, src, top};
    }
    return {bets, src, top};
  }

  /** 켈리 비율: 배당 o 에서 확률 p 인 마권에 자금의 몇 %를 거는지 */
  // 낮은 배당에서 '10% 남는다'는 가정이 그대로 커지지 않게 한 마권 비율은 10%까지
  const kelly = (p, o) => Math.min(0.1, Math.max(0, (p * o - 1) / (o - 1)));

  /** 하루 계획: races 배열, opt = {bankroll, mode:'safe'|'normal'|'all', pools, margin} */
  function plan(races, opt) {
    const B = Math.max(0, Math.floor(+opt.bankroll || 0));
    const frac = MODES[opt.mode] ?? 0.25;
    const res = races.map(r => ({race: r.race, ...candidates(r, opt)}));
    // 1) 켈리 일부로 금액
    for (const r of res) {
      if (!r.bets) continue;
      for (const b of r.bets) { b.k = kelly(b.p, b.seen ? b.minOdds : (b.cur ?? b.minOdds)); b.raw = frac * b.k * B; }
    }
    // 2) '예산 모두 쓰기'면 같은 비율로 늘려 하루 합계 = 자금 (경주 상한에 걸리면 남는 돈은 다른 경주로)
    const raceCap = Math.min(RACE_CAP, B);
    const active = res.filter(r => r.bets);
    const rawSum = r => r.bets.reduce((a, b) => a + b.raw, 0);
    if (opt.mode === "all" && active.length) {
      let left = B, open = active.slice();
      for (let it = 0; it < 20 && open.length && left > UNIT; it++) {
        const tot = open.reduce((a, r) => a + rawSum(r), 0); if (!(tot > 0)) break;
        const s = left / tot, next = [];
        for (const r of open) {
          const want = rawSum(r) * s, cur = r.bets.reduce((a, b) => a + (b.amt || 0), 0);
          const room = raceCap - cur, add = Math.min(want, room);
          r.bets.forEach(b => b.amt = (b.amt || 0) + add * b.raw / rawSum(r));
          left -= add;
          if (want < room) next.push(r);
        }
        open = next;
      }
    } else {
      for (const r of active) r.bets.forEach(b => b.amt = b.raw);
      const tot = active.reduce((a, r) => a + r.bets.reduce((x, b) => x + b.amt, 0), 0);
      if (tot > B) active.forEach(r => r.bets.forEach(b => b.amt *= B / tot));
    }
    // 3) 경주 상한, 100원 단위 (내림), 100원 미만은 뺌
    for (const r of active) {
      let sum = r.bets.reduce((a, b) => a + b.amt, 0);
      if (sum > raceCap) r.bets.forEach(b => b.amt *= raceCap / sum);
      r.bets.forEach(b => b.stake = Math.floor(b.amt / UNIT) * UNIT);
      // 배당판 값을 넣은 줄 가운데 넘기는 것(조건 미달)·100원 미만은 passed 로 옮김: 합계에는 안 들어가고 화면에는 남음(고칠 수 있게)
      r.passed = r.bets.filter(b => b.seen && (b.pass || b.stake < UNIT)).map(b => (b.small = !b.pass, b));
      if (!r.passed.length) delete r.passed;
      r.bets = r.bets.filter(b => !b.pass && b.stake >= UNIT).sort((a, b) => POOLS.indexOf(a.pool) - POOLS.indexOf(b.pool) || b.p - a.p);
      r.total = r.bets.reduce((a, b) => a + b.stake, 0);
      if (!r.bets.length) { delete r.bets; r.skip = (r.passed || []).some(b => b.pass) ? "배당판 배당이 조건보다 낮음" : "추천 금액이 100원 미만 (자금을 늘리거나 운용 방식을 바꾸면 들어감)"; }
    }
    const total = res.reduce((a, r) => a + (r.total || 0), 0);
    return {races: res, total, bankroll: B, raceCap};
  }

  const api = {plan, candidates, combos, combine, kelly, POOLS, RULES, RACE_CAP, MODES};
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.Planner = api;
})(typeof self !== "undefined" ? self : this);
