/* 넣은 단승 배당 기록 — '살 때 배당'과 '확정 배당'이 얼마나 다른지 재기 위한 자료 (2026-11-13)
   배당을 넣을 때마다 시각과 함께 이 브라우저에 저장. 서버로 보내지 않음.
   localStorage "oddslog:v1" = {날짜: {경주: [{t: 시각(ms), o: {번호: 배당}}]}}
   같은 경주에서 20초 안에 고친 것은 마지막 기록을 덮어씀. 경주마다 최근 40개, 날짜는 최근 60일.
   사용: OddsLog.add(날짜, 경주, {번호: 배당}), OddsLog.all() */
(function (root) {
  "use strict";
  const KEY = "oddslog:v1";
  const read = () => { try { return JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch { return {}; } };
  function add(date, race, odds) {
    try {
      const o = {}; for (const [k, v] of Object.entries(odds || {})) if (+v > 1) o[k] = +v;
      if (!Object.keys(o).length) return;
      const L = read(), list = ((L[date] ||= {})[race] ||= []), now = Date.now(), last = list[list.length - 1];
      if (last && JSON.stringify(last.o) === JSON.stringify(o)) return;
      if (last && now - last.t < 20000) list[list.length - 1] = {t: now, o}; else list.push({t: now, o});
      if (list.length > 40) list.splice(0, list.length - 40);
      const days = Object.keys(L).sort(); for (const d of days.slice(0, Math.max(0, days.length - 60))) delete L[d];
      localStorage.setItem(KEY, JSON.stringify(L));
    } catch { /* 저장할 수 없는 브라우저: 기록 없이 계속 */ }
  }
  root.OddsLog = {add, all: read, KEY};
})(typeof self !== "undefined" ? self : this);
