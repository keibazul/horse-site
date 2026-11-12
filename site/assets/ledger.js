/* 내 마권 기록장 공통: 저장, 조합 확률(하빌), 정산
   (기록장 bets.html 과 내 마권 분석 my.html 이 같이 씀. 현장 화면 live.html 은 경주 직후 단승·연승을 바로 정산하는 자기 방식이 따로 있음)

   기록 한 장: {id, grp, sel?, date:"YYYYMMDD", race, pool:"단승식"…, nums:[번호…], amount, memo?, created}
   정산: data/div/날짜.json(확정 배당, 저녁) — 없으면 '결과 대기'·'배당 대기' */
(function (root) {
  "use strict";
  const KEY = "horse-bets-v1";
  const POOLS = [["단승식",1,false,"1착"],["연승식",1,false,"3착 안 (7두 이하 2착 안)"],["복승식",2,false,"1·2착 순서 무관"],["쌍승식",2,true,"1→2착 순서대로"],
                 ["복연승식",2,false,"두 마리 모두 3착 안"],["삼복승식",3,false,"1~3착 순서 무관"],["삼쌍승식",3,true,"1→2→3착 순서대로"]];
  const PI = Object.fromEntries(POOLS.map(p => [p[0], {k: p[1], ordered: p[2], desc: p[3]}]));
  const store = {
    load(){ try { const v = JSON.parse(localStorage.getItem(KEY) || "[]"); return Array.isArray(v) ? v : []; } catch { return []; } },
    save(v){ try { localStorage.setItem(KEY, JSON.stringify(v)); return true; } catch { return false; } }
  };
  const cache = {};
  function getJSON(url){ if (url in cache) return cache[url]; const p = fetch(url, {cache: "no-cache"}).then(r => r.ok ? r.json() : null).catch(() => null); cache[url] = p; return p; }
  const comboKey = (pool, nums) => PI[pool].ordered ? nums.join(">") : [...nums].sort((a, b) => a - b).join("-");
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  const won = v => Math.round(v).toLocaleString("ko-KR") + "원";

  /* 조합 확률 (하빌, 2착 0.8·3착 0.7) */
  function comboProb(pool, nums, pMap){
    const ids = Object.keys(pMap).map(Number); if (!ids.length) return null;
    const p = ids.map(i => pMap[i]), s = p.reduce((a, b) => a + b, 0); if (!(s > 0)) return null;
    const P = p.map(x => x / s), pw = e => { const v = P.map(x => Math.pow(x, e)), t = v.reduce((a, b) => a + b, 0); return v.map(x => x / t); };
    const q = pw(0.8), r = pw(0.7), n = ids.length, ix = Object.fromEntries(ids.map((x, k) => [x, k]));
    if (nums.some(x => !(x in ix))) return null;
    const sel = nums.map(x => ix[x]);
    const p12 = (a, b) => P[a] * q[b] / (1 - q[a]);
    const p123 = (a, b, c) => p12(a, b) * r[c] / (1 - r[a] - r[b]);
    if (pool === "단승식") return P[sel[0]];
    if (pool === "쌍승식") return p12(sel[0], sel[1]);
    if (pool === "복승식") return p12(sel[0], sel[1]) + p12(sel[1], sel[0]);
    if (pool === "삼쌍승식") return p123(sel[0], sel[1], sel[2]);
    let tot = 0; const place = n <= 7 ? 2 : 3;
    for (let a = 0; a < n; a++) for (let b = 0; b < n; b++){ if (b === a) continue;
      if (pool === "연승식" && place === 2){ if (a === sel[0] || b === sel[0]) tot += p12(a, b); continue; }
      for (let c = 0; c < n; c++){ if (c === a || c === b) continue; const v = p123(a, b, c), top = [a, b, c];
        if (pool === "연승식" && top.includes(sel[0])) tot += v;
        else if (pool === "복연승식" && top.includes(sel[0]) && top.includes(sel[1])) tot += v;
        else if (pool === "삼복승식" && sel.every(x => top.includes(x))) tot += v; } }
    return tot;
  }

  /* 정산 → {st:"win"|"lose"|"ref"|"wait", ret:환급(대기면 null), text, prob:모델 적중 확률, res:[1~3착], top:모델 1순위 번호} */
  async function settle(b){
    const div = await getJSON(`data/div/${b.date}.json`), pred = await getJSON(`data/pred/${b.date}.json`);
    const pr = pred?.races?.[b.race];
    const out = new Set((div?.races?.[b.race]?.out || pr?.out || []).map(Number));
    const live = {}; if (pr?.p) for (const [k, v] of Object.entries(pr.p)) if (!out.has(+k)) live[k] = v;
    const prob = comboProb(b.pool, b.nums, live);
    const top = Object.keys(live).length ? +Object.entries(live).sort((x, y) => y[1] - x[1])[0][0] : null;
    const dr = div?.races?.[b.race];
    if (dr?.void || pr?.void) return {st: "ref", ret: b.amount, text: `${esc(dr?.void || pr?.void)} · 환불`, prob, top};
    if (b.nums.some(x => out.has(x))) return {st: "ref", ret: b.amount, text: "출전 취소 · 환불", prob, top};
    if (!dr || !dr.result) return {st: "wait", ret: null, text: pr?.result ? "배당 대기" : "결과 대기", prob, top};
    const od = dr.pay?.[b.pool]?.[comboKey(b.pool, b.nums)];
    const res = dr.result.slice(0, 3);
    if (od) return {st: "win", ret: b.amount * od, text: `적중 ${won(b.amount * od)} (배당 ${od})`, prob, res, top, odds: od};
    return {st: "lose", ret: 0, text: "미적중", prob, res, top};
  }

  /* 기록이 어디서 왔나: 베팅 계획·현장 화면의 '산 대로 기록' = 계획대로, 나머지 = 직접 */
  const source = b => (b.memo === "베팅 계획" || b.memo === "현장 화면") ? "plan" : "self";

  root.Ledger = {KEY, POOLS, PI, store, getJSON, comboKey, comboProb, settle, source};
})(typeof self !== "undefined" ? self : this);
