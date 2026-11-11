/* 경주 물리엔진 (브라우저 sim.html 과 검증용 Node 가 같이 씀)
 *
 * 말마다 '계획'(구간 기록 모델 + 잔차로 뽑은 지점별 통과 시간)을 갖고 출발한다.
 * 계획대로라면 서로 영향이 없지만, 실제로는 다음이 일어난다:
 *   - 길막힘: 앞말과 1마신 안으로 붙으면 그 속도에 묶이거나, 옆이 비면 바깥(또는 안쪽)으로 돌아 나간다.
 *   - 곡선 손실: 레일에서 멀수록 곡선에서 더 먼 거리를 달린다 (반지름 R, 바깥 y m → 거리 × (R+y)/R).
 *   - 선두 다툼: 초반 선두권에서 옆·바로 앞 경쟁마가 더 빨리 달리면 자리를 내주지 않으려고 그 속도를 따라간다 (MATCH),
 *                선두권에 여럿이 붙으면 조금 더 밀어붙인다 (KAPPA).
 *   - 체력: 계획보다 빨리 달린 거리만큼 '빚'이 쌓이고, 결승 600m 전부터 그 빚만큼 처진다.
 *            막혀서 계획보다 늦게 달리면 일부를 아끼고, 앞말 바로 뒤(바람막이)에서는 조금씩 아낀다.
 *   - 전개 효과(paceShift, 계획에 먼저 더함): 출발 200m 지점에서 선두와 0.2초 안에 몇 마리가 있는지(선두권)에 따라
 *            선두권 말과 뒤따르는 말의 600m 전·200m 전·결승 시간을 조금씩 옮긴다. 2022~2026년 4,970경주에서
 *            구간 기록 모델의 표본외 잔차로 잰 값(자기 200m 잔차를 뺀 뒤): 혼자 앞선 말은 결승이 0.59초 빠르고,
 *            선두권이 5두 이상이면 선두권 말은 0.05초 느리고 뒤에 있던 말은 0.07초 빠르다.
 *            넣기 전 시뮬레이션은 앞선 말이 너무 자주 졌음(200m 선두 우승 17%, 실제 27%) → 넣은 뒤 23%.
 * 세기(MATCH 0.8, LAMBDA 1.5)는 2015~2026년 실제 경주 11,962개의
 *   "초반이 1초 빠르면 앞선 말의 마지막 600m가 0.47초 느려짐", "선두 다툼 1두당 +0.04초",
 *   "초반 선두와 0.2초 안 말 수 평균 3.2두" 에 맞췄다. 지난 1년 2,000여 번 시뮬레이션에서 각각 0.47초, 0.05초, 3.4두.
 */
(function (root) {
  "use strict";
  const LEN = 2.4;                      // 말 몸길이 (m)
  const LANE = 1.25;                    // 옆 말과 필요한 간격 (m)
  // 전개 효과 표: 선두권(F: 경쟁 상대 0~4두 이상) / 뒤따름(B: 선두권 1~5두 이상) → [600m 전, 200m 전, 결승] 초
  const PACE = { W: 0.2, fx: { F0: [-0.022, -0.387, -0.591], F1: [-0.052, -0.187, -0.204], F2: [-0.046, -0.092, -0.059], F3: [-0.055, -0.059, -0.012], F4: [-0.098, -0.047, 0.052],
                              B1: [0.006, 0.036, 0.05], B2: [0.025, 0.062, 0.063], B3: [0.035, 0.059, 0.039], B4: [0.048, 0.038, -0.008], B5: [0.041, -0.01, -0.074] } };
  /** s1: 말별 계획 200m 통과 시간 → 말별 [600m 전, 200m 전, 결승]에 더할 초 (기록처럼 0.1초 단위로 반올림해 선두권을 셈) */
  function paceShift(s1) {
    const r = s1.map(x => Math.round(x * 10) / 10), mn = Math.min(...r), front = r.map(x => x - mn <= PACE.W + 1e-9), k = front.filter(Boolean).length;
    return front.map(f => PACE.fx[f ? "F" + Math.min(k - 1, 4) : "B" + Math.min(k, 5)]);
  }
  const P = { KAPPA: 0.004, MATCH: 0.8, LAMBDA: 1.5, BIAS: 0.007, DRAFT: 0.0035, RECOVER: 0.5, LAT_V: 1.2, A_MAX: 1.6, D_MAX: 2.6, FRONT_GAP: 3.0 };

  // 출발 가속 + 지점 사이 단조 3차 보간 (sim.html 과 같은 계획 곡선)
  function planMotion(D, T) {
    const n = T.length, del = [];
    for (let k = 0; k < n - 1; k++) del.push((D[k + 1] - D[k]) / Math.max(0.05, T[k + 1] - T[k]));
    const T1 = T[1], d1 = D[1];
    let tau = T1 - d1 / del[1]; if (!(tau > 0.6)) tau = 0.6;
    const ex = Math.exp(-T1 / tau), vmax = d1 / (T1 - tau * (1 - ex)), v1 = vmax * (1 - ex);
    const m = new Array(n).fill(0); m[1] = v1;
    for (let k = 2; k < n - 1; k++) { const a = del[k - 1], b = del[k]; if (a * b <= 0) { m[k] = 0; continue; }
      const h0 = T[k] - T[k - 1], h1 = T[k + 1] - T[k], w1 = 2 * h1 + h0, w2 = h1 + 2 * h0; m[k] = (w1 + w2) / (w1 / a + w2 / b); }
    { const k = n - 1, h0 = T[k - 1] - T[k - 2], h1 = T[k] - T[k - 1], e = ((2 * h1 + h0) * del[k - 1] - h1 * del[k - 2]) / (h0 + h1);
      m[k] = n > 3 ? Math.min(Math.max(e, 0.85 * del[k - 1]), 1.08 * del[k - 1]) : del[k - 1]; }
    for (let k = 1; k < n - 1; k++) { const d = del[k], a = m[k] / d, b = m[k + 1] / d, s = a * a + b * b; if (s > 9) { const q = 3 / Math.sqrt(s); if (k > 1) m[k] = q * a * d; m[k + 1] = q * b * d; } }
    const seg = t => { let k = 1; while (k < n - 2 && t > T[k + 1]) k++; return k; };
    return {
      pos(t) { if (t <= 0) return 0; if (t <= T1) return vmax * (t - tau * (1 - Math.exp(-t / tau)));
        if (t >= T[n - 1]) return D[n - 1] + m[n - 1] * (t - T[n - 1]);
        const k = seg(t), hh = T[k + 1] - T[k], s = (t - T[k]) / hh, s2 = s * s, s3 = s2 * s;
        return (2 * s3 - 3 * s2 + 1) * D[k] + (s3 - 2 * s2 + s) * hh * m[k] + (-2 * s3 + 3 * s2) * D[k + 1] + (s3 - s2) * hh * m[k + 1]; },
      vel(t) { if (t <= 0) return 0; if (t <= T1) return vmax * (1 - Math.exp(-t / tau));
        if (t >= T[n - 1]) return m[n - 1];
        const k = seg(t), hh = T[k + 1] - T[k], s = (t - T[k]) / hh; return (6 * s * s - 6 * s) * (D[k] - D[k + 1]) / hh + (3 * s * s - 4 * s + 1) * m[k] + (3 * s * s - 2 * s) * m[k + 1]; }
    };
  }

  // 계획 속도를 거리(2m 간격) 표로: vPlan(s)
  function planTable(D, T, dist) {
    const mv = planMotion(D, T), N = Math.ceil(dist / 2) + 2, tab = new Float32Array(N);
    let t = 0, k = 0; const tEnd = T[T.length - 1] + 3;
    while (k < N && t < tEnd + 30) { const s = mv.pos(t); while (k < N && k * 2 <= s) { tab[k] = Math.max(1, mv.vel(t)); k++; } t += 0.1; }
    for (; k < N; k++) tab[k] = tab[k - 1] || 15;
    tab[0] = Math.max(tab[0], 0.5);
    return tab;
  }

  /* 한 경주 돌리기
   * race: {dist, curveR(dbg) → 곡선 반지름(m) 또는 0, n}
   * plans: [{T:[0,t200,tg3,tg1,tfin]}]  (D = [0,200,dist-600,dist-200,dist])
   * opts: {dt, record (기록 간격 초, 없으면 안 함), lanes0 (출발 위치 y), params}
   * 반환: {fin[], cp:{s1f[],g3f[],g1f[]}, traj?:{dt, s[i]:Float32Array, y[i], v[i]}, blocked[], debt[]}
   */
  function run(race, plans, opts) {
    const o = opts || {}, pp = Object.assign({}, P, o.params || {});
    const dist = race.dist, n = plans.length, dt = o.dt || 0.2;
    const D = [0, 200, dist - 600, dist - 200, dist];
    const tab = plans.map(p => p.tab || planTable(D, p.T, dist));
    // BIAS: 막힘·다툼으로 생기는 평균 손실(약 0.6초)을 메워, 결승 기록 평균이 계획(실제 기록 분포)과 같도록
    const vPlan = (i, s) => { const t = tab[i], f = Math.max(0, Math.min(t.length - 1.001, s / 2)), k = f | 0, r = f - k; return (t[k] * (1 - r) + t[k + 1] * r) * (1 + pp.BIAS); };
    const s = new Float64Array(n), v = new Float64Array(n), y = new Float64Array(n), debt = new Float64Array(n), blocked = new Float64Array(n);
    const blockedLate = new Float64Array(n), wideLate = new Float64Array(n);   // 결승 600m 안 막힌 시간, 마지막 곡선에서 가장 바깥 위치
    const yT = new Float64Array(n);
    for (let i = 0; i < n; i++) { y[i] = o.lanes0 ? o.lanes0[i] : 1.2 + i * 1.3; yT[i] = y[i]; }
    const fin = new Array(n).fill(null), cp = { s1f: new Array(n).fill(null), g3f: new Array(n).fill(null), g1f: new Array(n).fill(null) };
    const marks = [["s1f", 200], ["g3f", dist - 600], ["g1f", dist - 200]];
    const rec = o.record ? { dt: o.record, s: [], y: [], v: [] } : null;
    if (rec) for (let i = 0; i < n; i++) { rec.s.push([]); rec.y.push([]); rec.v.push([]); }
    let t = 0, nextRec = 0, done = 0;
    const tMax = Math.max(...plans.map(p => p.T[4])) * 1.25 + 20;
    const order = Array.from({ length: n }, (_, i) => i);
    while (t < tMax) {
      if (rec && t >= nextRec - 1e-9) { for (let i = 0; i < n; i++) { rec.s[i].push(s[i]); rec.y[i].push(y[i]); rec.v[i].push(v[i]); } nextRec += rec.dt; }
      if (done === n && (!rec || t > Math.max(...fin) + 6)) break;
      order.sort((a, b) => s[b] - s[a]);
      const lead = s[order[0]];
      // 선두권(선두에서 FRONT_GAP m 안) 말 수
      let pack = 0; for (const j of order) { if (lead - s[j] <= pp.FRONT_GAP) pack++; else break; }
      let ym = 0; for (let k = 0; k < n; k++) ym += y[k]; ym /= n;      // 곡선 손실 기준: 그 순간 말들의 평균 위치
      const ns = new Float64Array(n);
      for (let r = 0; r < n; r++) {
        const i = order[r], si = s[i];
        if (si >= dist) {                                   // 결승 뒤: 천천히 속도를 줄임
          const nv = Math.max(6, v[i] - 1.3 * dt); v[i] = nv; ns[i] = si + nv * dt; continue; }
        const vp = vPlan(i, Math.min(si, dist));
        let vd = vp;
        const early = si < 0.55 * dist;
        if (early && si > 60 && lead - si <= pp.FRONT_GAP && pack >= 2) {
          vd *= 1 + pp.KAPPA * Math.min(pack - 1, 3);
          // 경쟁마 따라가기: 선두권 안에서 나란히(±1마신) 달리는 말 중 가장 빠른 말
          let rv = 0; for (let q = 0; q < pack; q++) { const j = order[q]; if (j !== i && Math.abs(s[j] - si) < LEN * 1.1 && v[j] > rv) rv = v[j]; }
          if (rv > vd) vd += pp.MATCH * (rv - vd);
        }
        if (si > dist - 600 && si < dist) vd *= Math.max(0.88, Math.min(1.04, 1 - pp.LAMBDA * debt[i] / 600));
        // 바로 앞 같은 줄의 말
        let ahead = -1, gap = 1e9;
        for (let q = r - 1; q >= 0; q--) { const j = order[q]; const ds = s[j] - si; if (ds > 12) break;
          if (Math.abs(y[j] - y[i]) < LANE && ds < gap) { gap = ds; ahead = j; } }
        let drafting = false;
        if (ahead >= 0) {
          const room = gap - LEN;
          drafting = room < 3.5 && si > 100 && si < dist;
          if (room < 1.2 + Math.max(0, v[i] - v[ahead]) * 0.9 && vd > v[ahead]) {
            // 비켜 갈 자리 찾기: 바깥 먼저, 안쪽은 레일과 1m 넘게 떨어졌을 때
            const free = c => { if (c < 0.9 || c > 24) return false; for (let k = 0; k < n; k++) { if (k === i) continue;
              if (Math.abs(s[k] - si) < LEN + 0.8 && Math.abs(y[k] - c) < LANE) return false; } return true; };
            const out = y[ahead] + LANE + 0.05, inn = y[ahead] - LANE - 0.05;
            if (free(out)) yT[i] = out; else if (free(inn)) yT[i] = inn;
            else { vd = Math.min(vd, v[ahead] + Math.max(0, room) * 0.4); blocked[i] += dt; if (si > dist - 600) blockedLate[i] += dt; }
          }
        }
        if (ahead < 0 || gap - LEN > 4) {
          // 앞이 트였으면 레일 쪽으로 조금씩 (곡선에서는 더 적극적으로)
          const c = Math.max(1.0, y[i] - 1.0);
          let ok = true; for (let k = 0; k < n; k++) { if (k === i) continue; if (Math.abs(s[k] - si) < LEN + 0.8 && y[k] < y[i] && y[k] > c - LANE) { ok = false; break; } }
          if (ok) yT[i] = Math.min(yT[i], c);
        }
        // 가속 한계
        const aMax = si < 150 ? 4.5 : pp.A_MAX;
        const nv = Math.max(0, v[i] + Math.max(-pp.D_MAX * dt, Math.min(aMax * dt, vd - v[i])));
        // 체력: 계획보다 빠르면 빚, 막혀서 느리면 일부 저축, 바람막이는 조금씩 저축
        const extra = (nv - vp) * dt;
        if (si > 60 && si < dist - 600) debt[i] += extra > 0 ? extra : extra * pp.RECOVER;
        if (drafting && si < dist - 600) debt[i] -= pp.DRAFT * nv * dt;
        // 옆 이동 (초당 LAT_V m)
        const dy = yT[i] - y[i], step = pp.LAT_V * dt; y[i] += Math.max(-step, Math.min(step, dy));
        // 곡선: 바깥일수록 같은 속도로 덜 나아감 (레일에서 1.5m 기준)
        const Rc = race.curveR(dist - si);
        if (Rc > 0 && si > dist - 900) wideLate[i] = Math.max(wideLate[i], y[i]);
        const geo = Rc > 0 ? (Rc + ym) / (Rc + y[i]) : 1;
        v[i] = nv; ns[i] = si + nv * dt * geo;
      }
      for (let i = 0; i < n; i++) {
        const a = s[i], b = ns[i];
        for (const [k, d] of marks) if (cp[k][i] === null && a < d && b >= d) cp[k][i] = t + dt * (d - a) / Math.max(1e-6, b - a);
        if (fin[i] === null && a < dist && b >= dist) { fin[i] = t + dt * (dist - a) / Math.max(1e-6, b - a); done++; }
        s[i] = b;
      }
      t += dt;
    }
    for (let i = 0; i < n; i++) if (fin[i] === null) fin[i] = t;
    const out = { fin, cp, blocked: Array.from(blocked), blockedLate: Array.from(blockedLate), wideLate: Array.from(wideLate), debt: Array.from(debt), t };
    if (rec) out.traj = { dt: rec.dt, s: rec.s.map(a => Float32Array.from(a)), y: rec.y.map(a => Float32Array.from(a)), v: rec.v.map(a => Float32Array.from(a)) };
    return out;
  }

  const api = { run, planTable, planMotion, paceShift, PACE, PARAMS: P, LEN };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.RacePhysics = api;
})(typeof window !== "undefined" ? window : globalThis);
