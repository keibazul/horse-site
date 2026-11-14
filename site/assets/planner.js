/* 베팅 계획 계산 (사이트 plan.html·live.html 과 과거 검증 pipeline/checks/plan_backtest.js 가 같이 씀)

   2026-11-13 바꿈: 배당 반영 확률(assets/mktmodel.js, 말 정보 + 그 경주 단승 배당 → 우승)로 단승만 고른다.
   경주마다
   1) 확률: race.pm = 배당 반영 확률 (출전하는 모든 말의 단승 배당이 있어야 계산됨 → 없으면 '배당 대기')
   2) 사는 말: 확률 ≥ 5% 이고 확률 × 단승 배당(기대값) ≥ 1.2 인 말 (여러 마리일 수 있음)
        검증: 연도별 표본외 확률(그 전 해까지 학습), 확정 배당으로 1장씩 —
        2016~2022(5,700경주)로 규칙을 정함: 135% [112, 159] → 2023~2026(3,978경주) 확인: 116% [93, 135]
        (규칙은 '1,000장 넘는 것 가운데 앞 기간 95% 구간 아래쪽이 가장 높은 것'으로 미리 정해 고름)
   3) 다른 승식(연승·복승·쌍승·복연승·삼복승·삼쌍승)은 같은 확률로 하빌 조합 확률 × 확정 배당을 시험했지만
      앞 기간에서 고른 규칙이 뒤 기간에서 유지되지 않아(79~130%, 들쭉날쭉) 계획에 넣지 않음
   4) 금액: 켈리 기준(확률·배당으로 정한 자금 비율, 한 마권 최대 10%) × 운용 비율
        조심스럽게 1/8, 보통 1/4, 자금 모두 쓰기는 아래 7)
        켈리 비율을 구할 때는 확률 × 0.85 (기대값 1.2 이상으로 고른 말은 모델이 확률을 높게 잡는 경향 → 승자의 저주 보정)
        배당은 경주마다 출발 직전에야 알 수 있으므로 앞 경주부터 차례로 금액을 정하고, 하루 합계가 자금에 닿으면 뒤 경주는 못 삼
        (opt.spent: 이미 끝난 경주에 쓴 돈 → 남은 자금에서 셈)
   5) 한 경주 합계는 법정 상한 10만 원 이하, 하루 합계는 입력한 자금 이하, 100원 단위
   6) 2026-11-14: 자동으로 빼는 경주 — 그날 마지막 경주(사람들이 배당 높은 말을 더 사서 그 배당이 실제보다 낮음: 20배↑ 말의
        실제 우승 ÷ 배당이 말하는 우승 = 0.68, 그 밖 경주 0.86; 계획 마권 216장 67%), 1200m 이하(모델의 시장 대비 우위가 절반, 계획 마권 103%)
        — pipeline/checks/last_race.py, crowd_bias.py. 사용자가 켜고 끌 수 있음: race.use === true 면 자동 제외를 무시, false 면 뺌.
        이 두 기준은 같은 과거 자료를 보고 정했으므로 검증 숫자는 그만큼 낙관적.
   7) 자금 모두 쓰기: 금액 = 켈리 비율 × 자금 ÷ (ALL.kbar × 살 수 있는 경주 수). 살 수 있는 경주 수 = 앞에서 마권을 산 경주 + 이 경주 + 아직 남은 켜진 경주
        → 경주를 끄면 남은 경주 몫이 커지고, 살 말이 없던 경주의 몫은 뒤로 넘어감 (최소 ALL.minRaces 경주로 나눔)
   8) 세금 문턱: 한 장의 환급금이 200만 원을 넘거나, 100배를 넘는 배당에서 10만 원을 넘으면 기타소득세가 붙으므로 그 아래가 되게 금액을 줄임 (b.tax)
   주의: 확정 배당으로 고른 결과라 실제(살 때 배당)는 더 나쁠 수 있음. 배당은 마감까지 바뀌므로 될수록 늦게 넣을 것. */
(function (root) {
  "use strict";
  // 결합 계수 (work/winner_history/blend.json 과 같게, 2026-11-12): α·log 모델 + β·log 시장 + γ·(log 시장)² — γ 는 비인기마 편향
  const BLEND = {a: 0.1569, b: 0.7616, g: -0.0368};
  const GAMMA = 0.8, DELTA = 0.7;     // 하빌 2착·3착 보정
  const RACE_CAP = 100000, UNIT = 100;
  const POOLS = ["단승식", "연승식", "복승식", "쌍승식", "복연승식", "삼복승식", "삼쌍승식"];
  const PAYOUT = {"단승식": 0.8, "연승식": 0.8, "복승식": 0.73, "쌍승식": 0.73, "복연승식": 0.73, "삼복승식": 0.73, "삼쌍승식": 0.73};
  // 승식별: 살펴볼 조합 수, 최소 조합 확률 (확률이 낮은 고배당일수록 과거에 손실이 컸음)
  const RULES = {
    "단승식": {k: 2, minP: 0.20}, "연승식": {k: 2, minP: 0.45},
    "복승식": {k: 2, minP: 0.08}, "쌍승식": {k: 2, minP: 0.05}, "복연승식": {k: 2, minP: 0.15},
    "삼복승식": {k: 2, minP: 0.04}, "삼쌍승식": {k: 2, minP: 0.012}
  };
  const MODES = {safe: 0.125, normal: 0.25};
  const AUTO = {last: true, sprint: 1200};                 // 자동으로 빼는 경주: 그날 마지막 경주, 이 거리(m) 이하
  const ALL = {kbar: 0.005, minRaces: 3};                  // 자금 모두 쓰기: 과거 검증에서 마권을 산 날 평균 자금의 약 80%를 쓰게 맞춘 값
  const TAX = {pay: 2000000, odds: 100, payHigh: 100000};  // 환급금 과세 문턱 (소득세법 과세최저한)

  function norm(o) { const s = Object.values(o).reduce((a, b) => a + b, 0); const r = {}; for (const k in o) r[k] = o[k] / s; return r; }

  /** 결합 확률 (모델 p, 단승 배당 odds; 둘 다 {번호: 값}) */
  function combine(p, odds) {
    const ids = Object.keys(p);
    const q = norm(Object.fromEntries(ids.map(i => [i, 1 / odds[i]])));
    const v = Object.fromEntries(ids.map(i => { const lq = Math.log(q[i]); return [i, Math.exp(BLEND.a * Math.log(Math.max(p[i], 1e-9)) + BLEND.b * lq + BLEND.g * lq * lq)]; }));
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

  // 단승 가치 기준 (배당 반영 확률): 위 설명의 검증 결과로 정함
  const VALUE = {minP: 0.05, minEV: 1.2, shrink: 0.85};   // shrink: 금액을 정할 때 확률에 곱함 (고른 말은 실제 우승이 예측의 0.83~0.89배 — pipeline/checks/plan_ev_curve.py)

  /** 한 경주의 후보 마권 (금액 전)
      race = {race, pm?:{번호:배당 반영 확률}, odds?:{번호:단승 배당}, out?:[번호], done?:bool, void?:str}
      pm 은 페이지가 모든 말의 단승 배당으로 계산해 넣음 (없으면 '배당 대기') */
  function candidates(race, opt) {
    const out = new Set((race.out || []).map(String));
    if (race.void) return {skip: race.void};
    if (race.done) return {skip: "끝난 경주"};
    const auto = AUTO.last && race.last ? "last" : (AUTO.sprint && +race.dist > 0 && +race.dist <= AUTO.sprint ? "sprint" : null);
    if (race.use === false) return {skip: "직접 뺀 경주", off: "user", auto};
    if (auto && race.use !== true) return {skip: auto === "last" ? "그날 마지막 경주는 자동으로 뺌" : `${AUTO.sprint}m 이하 경주는 자동으로 뺌`, off: auto, auto};
    const pm = race.pm || null, odds = race.odds || {};
    const ids = (race.ids || Object.keys(pm || race.p || {})).map(String).filter(k => !out.has(k));   // ids: 출전표의 번호들 (배당을 넣기 전에도 두수를 알도록)
    if (ids.length < 3) return {skip: "출전마가 너무 적음"};
    if (!pm || !ids.every(i => +odds[i] > 1 && pm[i] != null)) return {skip: "단승 배당을 모두 넣으면 계산", wait: true, src: "wait", auto};
    const P = norm(Object.fromEntries(ids.map(i => [i, Math.max(+pm[i], 1e-9)])));
    const top = Math.max(...Object.values(P));
    const bets = [];
    for (const i of ids) {
      const p = P[i], o = +odds[i], ev = p * o;
      if (p >= VALUE.minP && ev >= VALUE.minEV) bets.push({pool: "단승식", key: String(i), nums: [+i], p, cur: o, ev, minOdds: Math.max(1.1, ceil1(VALUE.minEV / p))});
    }
    if (!bets.length) return {skip: `기대값 ${VALUE.minEV} 넘는 말 없음`, src: "mkt", top, auto};
    return {bets: bets.sort((a, b) => b.ev - a.ev), src: "mkt", top, auto};
  }

  /** 켈리 비율: 배당 o 에서 확률 p 인 마권에 자금의 몇 %를 거는지 */
  // 낮은 배당에서 '10% 남는다'는 가정이 그대로 커지지 않게 한 마권 비율은 10%까지
  const kelly = (p, o) => Math.min(0.1, Math.max(0, (p * o - 1) / (o - 1)));

  /** 하루 계획: races 배열(위 race 에 last·dist·use 추가), opt = {bankroll, mode:'safe'|'normal'|'all', spent: 끝난 경주에 쓴 돈, betRaces: 끝난 경주 중 마권을 산 경주 수} */
  function plan(races, opt) {
    const B = Math.max(0, Math.floor(+opt.bankroll || 0));
    const all = opt.mode === "all", frac = MODES[opt.mode] ?? 0.25;
    const res = races.map(r => ({race: r.race, void: !!r.void, ...candidates(r, opt)})).sort((x, y) => x.race - y.race);
    const raceCap = Math.min(RACE_CAP, B);
    let left = Math.max(0, B - Math.max(0, +opt.spent || 0)), bought = Math.max(0, +opt.betRaces || 0);
    const pending = r => !r.off && !r.void && (r.wait || r.bets || r.src === "mkt");      // 아직 살 수 있는 경주 (끝난·취소·뺀 경주 제외)
    // 앞 경주부터: 켈리 × 운용 비율 → 세금 문턱·경주 상한·남은 자금으로 줄임 → 100원 단위 (내림), 100원 미만은 뺌
    res.forEach((r, i) => {
      if (!r.bets) return;
      const slots = Math.max(ALL.minRaces, bought + 1 + res.slice(i + 1).filter(pending).length);
      for (const b of r.bets) {
        b.k = kelly(b.p * (VALUE.shrink || 1), b.cur ?? b.minOdds);
        b.amt = all ? b.k * B / (ALL.kbar * slots) : frac * b.k * B;
      }
      const sum = r.bets.reduce((a, b) => a + b.amt, 0), lim = Math.min(raceCap, left);
      if (sum > lim) r.bets.forEach(b => b.amt *= lim / sum);
      for (const b of r.bets) {
        b.stake = Math.floor(b.amt / UNIT) * UNIT;
        const o = b.cur ?? b.minOdds, mx = Math.floor((o > TAX.odds ? TAX.payHigh : TAX.pay) / o / UNIT) * UNIT;   // 세금 문턱 아래로
        if (b.stake > mx) { b.stake = mx; b.tax = true; }
      }
      r.bets = r.bets.filter(b => b.stake >= UNIT);
      r.total = r.bets.reduce((a, b) => a + b.stake, 0);
      left -= r.total;
      if (r.bets.length) bought++;
      else { delete r.bets; r.skip = lim < UNIT ? "오늘 자금을 다 씀" : "추천 금액이 100원 미만 (자금을 늘리거나 운용 방식을 바꾸면 들어감)"; }
    });
    const total = res.reduce((a, r) => a + (r.total || 0), 0);
    return {races: res, total, bankroll: B, raceCap, left, on: res.filter(pending).length};
  }

  const api = {plan, candidates, combos, combine, kelly, POOLS, RULES, RACE_CAP, MODES, BLEND, VALUE, AUTO, ALL, TAX};
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.Planner = api;
})(typeof self !== "undefined" ? self : this);
