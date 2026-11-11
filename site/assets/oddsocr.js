/* 배당판 사진에서 읽은 글자 → {마번: 단승 배당}
   (예측 화면 race.html 이 씀. 실제 페이지 확인: pipeline/checks/ocr_e2e.py)

   현장 배당판(단승): 한 줄에 "배당  마번" — 예) "204.4 1", "21.7 2" … "30.8 10"
     - 글자 인식이 둘을 붙여 읽는 일이 잦음: "4.9 7" → "497", "7.7 9" → "7.79"
       → 줄 끝이 마번(위에서 아래로 1, 2, 3 … 순서)이라는 점으로 다시 나눔. 소수점이 빠졌으면 마지막 자리 앞에 넣음(배당은 소수 한 자리)
     - 단승 판 오른쪽에 연승 판이 같이 찍히면 한 줄에 쌍이 둘 → 왼쪽(단승)만 씀
   표 모양(마번이 앞, 배당이 뒤: "1 말이름 3.2 …")도 읽음. 둘 중 더 많이 읽힌 쪽을 고름.
   검산: 모든 말을 읽었으면 Σ(1/배당) 이 1.25 안팎(단승 환급률 약 80%)이어야 함 → 벗어나면 틀린 값이 있다고 알림 */
(function (root) {
  "use strict";
  function oddsOf(t) {
    if (/^\d{1,4}\.\d$/.test(t) && +t >= 1) return {v: +t, sure: true};
    if (/^\d{2,5}$/.test(t)) { const v = +(t.slice(0, -1) + "." + t.slice(-1)); if (v >= 1) return {v, sure: false}; }   // 소수점을 놓친 경우
    return null;
  }
  const toks = ln => ln.replace(/,/g, ".").split(/\s+/).map(t => t.replace(/[^0-9.]/g, "").replace(/^\.+|\.+$/g, "")).filter(Boolean);

  function boardMode(lines, allN) {
    const set = new Set(allN);
    // 1) 줄마다 가능한 (마번, 배당) 후보 — 줄 맨 앞 쌍만 (오른쪽 연승 판으로 넘어가지 않게), 왼쪽 것 우선
    const rows = [];
    for (const ln of lines) {
      const tk = toks(ln), opts = [];
      const add = c => { if (!opts.some(o => o.n === c.n)) opts.push(c); };
      for (let i = 0; i < Math.min(2, tk.length); i++) {
        const t = tk[i], o = oddsOf(t), nx = tk[i + 1];
        if (o && nx && /^\d{1,2}$/.test(nx) && set.has(+nx)) add({n: +nx, od: o.v, sure: o.sure});
        for (const n of allN) {                                   // 배당과 마번이 붙어 읽힌 경우
          const s = String(n);
          if (t.length > s.length && t.endsWith(s)) { const o2 = oddsOf(t.slice(0, -s.length)); if (o2) add({n, od: o2.v, sure: false, exact: o2.sure}); }
        }
      }
      if (opts.length) rows.push(opts);
    }
    // 2) 마번은 위에서 아래로 커짐 → 그 순서에 맞는 가장 긴 조합을 고름 (머리글 등에서 생긴 가짜 쌍을 버림)
    let states = new Map([[0, {cnt: 0, q: 0, path: []}]]);
    const better = (a, b) => !b || a.cnt > b.cnt || (a.cnt === b.cnt && a.q > b.q);
    for (const opts of rows) {
      const next = new Map(states);
      for (const [last, st] of states) for (const c of opts) {
        if (c.n <= last) continue;
        const q = st.q + (c.sure ? 2 : c.exact ? 1 : 0) + (c.n === last + 1 ? 0.5 : 0);
        const cand = {cnt: st.cnt + 1, q, path: st.path.concat([c])};
        if (better(cand, next.get(c.n))) next.set(c.n, cand);
      }
      states = next;
    }
    let best = null;
    for (const st of states.values()) if (better(st, best)) best = st;
    const map = {}, unsure = [];
    for (const c of best.path) { map[c.n] = c.od; if (!c.sure) unsure.push(c.n); }
    return {map, unsure, mode: "board"};
  }

  function tableMode(lines, allN) {
    const map = {};
    for (const ln of lines) {
      const tk = ln.replace(/,/g, ".").match(/\d+(?:\.\d+)?/g) || [];
      if (tk.length < 2 || tk[0].includes(".")) continue;
      const no = +tk[0], od = tk.slice(1).find(x => /^\d{1,4}\.\d$/.test(x) && +x >= 1);
      if (allN.includes(no) && od && !(no in map)) map[no] = +od;
    }
    return {map, unsure: [], mode: "table"};
  }

  /** text: 글자 인식 결과(줄바꿈 포함), allN: 이 경주 마번 배열 → {map, unsure:[확인할 마번], mode, check:{sum, ok}|null} */
  function parse(text, allN) {
    const lines = String(text || "").split(/\n+/).map(s => s.trim()).filter(Boolean);
    const b = boardMode(lines, allN), t = tableMode(lines, allN);
    const r = Object.keys(t.map).length > Object.keys(b.map).length ? t : b;
    const got = Object.keys(r.map).map(Number);
    r.check = null;
    if (got.length >= allN.length - 1 && got.length >= 4) {             // (출전 취소 1두까지) 거의 다 읽었을 때만 검산
      const sum = got.reduce((a, n) => a + 1 / r.map[n], 0);
      r.check = {sum: Math.round(sum * 1000) / 1000, ok: sum > 1.08 && sum < 1.45};
    }
    return r;
  }

  /* 읽을 부분을 회색조로: 어두운 판은 뒤집고(검은 글자·흰 바탕), 글자 줄 높이가 60px 안팎이 되게 키움. bin=true 면 흑백으로 나눔(오츠 방법) */
  function prepare(img, sel, nRows, bin){
    const s = sel || {x: 0, y: 0, w: img.width, h: img.height};
    const cropped = !!sel && s.w * s.h < img.width * img.height * 0.9;
    let sc = cropped ? 64 * (nRows + 1.5) / s.h : 2000 / Math.max(s.w, s.h);
    sc = Math.min(sc, 6, 2800 / Math.max(s.w, s.h)); sc = Math.max(sc, 700 / Math.max(s.w, s.h), 0.15);
    const c = document.createElement("canvas"); c.width = Math.max(1, Math.round(s.w * sc)); c.height = Math.max(1, Math.round(s.h * sc));
    const g = c.getContext("2d", {willReadFrequently: true}); g.imageSmoothingQuality = "high";
    g.drawImage(img, s.x, s.y, s.w, s.h, 0, 0, c.width, c.height);
    const d = g.getImageData(0, 0, c.width, c.height), px = d.data, n = px.length / 4; let sum = 0;
    for (let i = 0; i < px.length; i += 4){ const y = Math.round(0.299 * px[i] + 0.587 * px[i+1] + 0.114 * px[i+2]); px[i] = y; sum += y; }
    const inv = sum / n < 110, hist = new Array(256).fill(0);
    for (let i = 0; i < px.length; i += 4){ const y = inv ? 255 - px[i] : px[i]; px[i] = y; hist[y]++; }
    let thr = 128;
    if (bin){ let w0 = 0, s0 = 0, best = -1; const tot = hist.reduce((a, v, k) => a + v * k, 0);
      for (let t = 0; t < 256; t++){ w0 += hist[t]; if (!w0) continue; const w1 = n - w0; if (!w1) break; s0 += t * hist[t];
        const m0 = s0 / w0, m1 = (tot - s0) / w1, v = w0 * w1 * (m0 - m1) * (m0 - m1); if (v > best){ best = v; thr = t; } } }
    for (let i = 0; i < px.length; i += 4){ const y = bin ? (px[i] > thr ? 255 : 0) : px[i]; px[i] = px[i+1] = px[i+2] = y; px[i+3] = 255; }
    g.putImageData(d, 0, 0);
    return c;
  }

  const api = {parse, oddsOf, prepare};
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.OddsOcr = api;
})(typeof self !== "undefined" ? self : this);
