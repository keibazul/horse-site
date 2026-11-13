/* 배당 반영 우승 확률 (mkt v1) — 브라우저에서 직접 계산
   모델: work/train_mkt_model.py (v5 특징 + 그 경주 단승 배당 → 우승, sklearn HistGradientBoosting) → site/data/model/mkt_v1.json
   말마다 특징: site/data/mkx/날짜.json {races: {경주: {번호: [범주 코드…, 숫자…]}}} (site_export 가 만듦)
   계산: 원점수 = baseline + Σ 트리 잎 값, 확률 = 1/(1+e^−원점수), 경주 안(출전하는 말)에서 합 1로.
   사용: const M = await MktModel.load(); MktModel.predict(M, xs, odds, ids) → {번호: 확률} | null */
(function (root) {
  "use strict";
  let P = null;
  function load(url){ if (!P) P = fetch(url || "data/model/mkt_v1.json", {cache: "no-cache"}).then(r => r.ok ? r.json() : null).catch(() => null); return P; }

  /* 시장 특징 (train_mkt_model.market_features 와 같게): q = (1/배당) 경주 안 합 1, ln q, 인기 순위, q/최대 q, 두수, 최대 q */
  function market(ids, odds){
    const inv = ids.map(i => 1 / odds[i]), s = inv.reduce((a, b) => a + b, 0), q = inv.map(v => v / s), top = Math.max(...q);
    const order = ids.map((i, k) => k).sort((a, b) => q[b] - q[a] || a - b), rank = new Array(ids.length);
    order.forEach((k, r) => rank[k] = r + 1);
    return ids.map((i, k) => [Math.log(q[k]), rank[k], q[k] / top, ids.length, top]);
  }
  function inBitset(bits, x){ const w = bits[x >> 5]; return w !== undefined && ((w >>> (x & 31)) & 1) === 1; }
  function raw(M, x){
    let s = M.baseline;
    for (const t of M.trees){
      let n = 0;
      while (!t.leaf[n]){
        const v = x[t.f[n]];
        let left;
        if (v === null || v === undefined || Number.isNaN(v)) left = t.m[n] === 1;
        else if (t.c[n]) left = Number.isInteger(v) && v >= 0 && inBitset(t.bits[t.b[n]], v);
        else left = v <= t.t[n];
        n = left ? t.l[n] : t.r[n];
      }
      s += t.v[n];
    }
    return s;
  }
  /** M: 모델, xs: {번호: 특징 배열(시장 특징 빼고)}, odds: {번호: 단승 배당}, ids: 출전하는 번호들 → {번호: 확률} (하나라도 없으면 null) */
  function predict(M, xs, odds, ids){
    if (!M || !xs || ids.length < 2 || ids.some(i => !xs[i] || !(+odds[i] > 1))) return null;
    const mk = market(ids, Object.fromEntries(ids.map(i => [i, +odds[i]])));
    const p = ids.map((i, k) => 1 / (1 + Math.exp(-raw(M, xs[i].concat(mk[k])))));
    const s = p.reduce((a, b) => a + b, 0);
    return Object.fromEntries(ids.map((i, k) => [i, p[k] / s]));
  }
  const api = {load, predict, raw, market};
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.MktModel = api;
})(typeof self !== "undefined" ? self : this);
