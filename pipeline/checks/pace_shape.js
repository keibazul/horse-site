// 말 단위 전개 지표: 실제 경주(시뮬레이션 파일에 든 지난 경주 결과) vs 물리엔진 시뮬레이션
//   선두권(200m 지점 선두와 0.2초 안) 두수 분포, 선두권 말 우승률(경쟁 상대 0~4두 이상), 200m 선두 우승률, 우승마의 200m 위치(0 선두~1 꼴찌)
//   + physics_calib.js 와 같은 경주 단위 지표(race)
// 사용: node pipeline/checks/pace_shape.js '{"races":700,"draws":4}'   ({"pace":false} 는 전개 효과 끔)
// 2026-11-12: 실제 1,019경주 선두권 말 우승률 [0.404,0.255,0.198,0.168,0.142], 200m 선두 우승 0.273, 우승마 위치 0.285
//   전개 효과 전 [0.303,0.203,0.154,0.121,0.105], 0.179, 0.378 → 후 [0.445,0.236,0.172,0.130,0.102], 0.234, 0.352
const fs = require("fs"), path = require("path");
const PH = require(path.join(__dirname, "../../site/physics.js"));
const DIR = path.join(__dirname, "../../site/data/sim");
const R = 450 / Math.PI;
const isInner = d => d >= 1700 && d <= 2000;
function innerU(dbg){ const v = ((-dbg)%1600+1600)%1600; if (v < 50) return v; if (v < 400) return 50+(v-50)*450/350; if (v < 850) return 500+(v-400); if (v < 1200) return 950+(v-850)*450/350; return 1400+(v-1200); }
const J1000 = 1040;
function uOf(dist, dbg){ if (isInner(dist)) return innerU(dbg); if (dist === 1400 && dbg > 1300) return 500; if (dist >= 2200 && dbg > 2200) return 1400;
  if (dist === 1000 && dbg > 1800-J1000) return J1000; return ((1800-dbg)%1800+1800)%1800; }
function curveR(dist){ const r = isInner(dist) ? R - 31.8 : R; return dbg => { if (dbg <= 0) return 0; const u = uOf(dist, dbg); return ((u>=50 && u<500) || (u>=950 && u<1400)) ? r : 0; }; }
function rng(seed){ let a = seed|0; return () => { a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const KS = ["s1f","g3f","g1f","fin"];
const args = JSON.parse(process.argv[2] || "{}"), nRace = args.races || 500, draws = args.draws || 4, params = args.params || {}, physics = args.physics !== false;
const files = fs.readdirSync(DIR).filter(f => /^sim_20(25|26)/.test(f)).sort();
const step = Math.max(1, Math.floor(files.length / nRace));
const nf = new Array(8).fill(0), F = Array.from({length:5}, () => [0,0]), lw = [0,0], wr = []; let tPlan = 0, tPhys = 0, nH = 0, contest = 0, nR = 0;
const A = {nf: new Array(8).fill(0), F: Array.from({length:5}, () => [0,0]), lw: [0,0], wr: []};
function add(T, s1, fin, rank){
  const n = s1.length, s1r = s1.map(x => Math.round(x*10)/10), mn = Math.min(...s1r), front = s1r.map(x => x - mn <= 0.2 + 1e-9), k = front.filter(Boolean).length;
  let w = 0; for (let i=1;i<n;i++) if (fin[i] < fin[w]) w = i;
  T.nf[Math.min(k,7)]++;
  for (let i=0;i<n;i++) if (front[i]){ T.F[Math.min(k-1,4)][1]++; if (i===w) T.F[Math.min(k-1,4)][0]++; }
  const rk = rank || (() => { const o = [...Array(n).keys()].sort((a,b)=>s1[a]-s1[b]), r = new Array(n); o.forEach((i,q)=>r[i]=q+1); return r; })();
  T.lw[1]++; if (rk[w] === 1) T.lw[0]++; T.wr.push((rk[w]-1)/(n-1));
}
const RR = [];
const SIMT = {nf: new Array(8).fill(0), F: Array.from({length:5}, () => [0,0]), lw: [0,0], wr: []};
for (let fi = 0; fi < files.length; fi += step){
  const J = JSON.parse(fs.readFileSync(path.join(DIR, files[fi])));
  const H = J.horses, n = H.length; if (n < 6) continue;
  if (H.every(h => h.actual && h.actual.cp && h.actual.cp.s1f && h.actual.ord)) {
    const fin = H.map(h => h.actual.ord <= 16 ? h.actual.ord : 99), s1 = H.map(h => h.actual.cp.s1f[1]), rank = H.map(h => h.actual.cp.s1f[0]);
    if (fin.filter(x => x < 99).length === n) add(A, s1, fin, rank);
  }
  const race = {dist: J.dist, curveR: curveR(J.dist)}, r = rng(fi*97+1);
  const maxNo = Math.max(...H.map(h=>h.no)), lanes0 = H.map(h => 1.2 + (h.no-1)*1.3*Math.min(1, 13/maxNo));
  for (let d = 0; d < draws; d++){
    const pr = J.pace[Math.floor(r()*J.pace.length)] || [1,1,1,1], pace = pr.map(v => 1 + 0.5*(v-1));
    const plans = H.map(h => { const pool = J.pools[h.debut ? "1" : "0"], res = pool[Math.floor(r()*pool.length)];
      const T = KS.map((k,j) => J.par[k]*pace[j] + h.pred[k] + res[j]);
      T[0]=Math.max(T[0],11); T[1]=Math.max(T[1],T[0]+3); T[2]=Math.max(T[2],T[1]+3); T[3]=Math.max(T[3],T[2]+8);
      return {T:[0,...T]}; });
    if (args.pace !== false){ const sh = PH.paceShift(plans.map(p => p.T[1])); plans.forEach((p,i) => { p.T[2] += sh[i][0]; p.T[3] += sh[i][1]; p.T[4] += sh[i][2];
      p.T[2]=Math.max(p.T[2],p.T[1]+3); p.T[3]=Math.max(p.T[3],p.T[2]+3); p.T[4]=Math.max(p.T[4],p.T[3]+8); }); }
    const o = PH.run(race, plans, {dt: 0.2, lanes0, params});
    add(SIMT, o.cp.s1f, o.fin);
    { const s1 = o.cp.s1f, g3 = o.cp.g3f, fin = o.fin, late = fin.map((f,i)=>f-g3[i]), sl = [...late].sort((a,b)=>a-b), med = sl[Math.floor(n/2)];
      const front = [...s1].sort((a,b)=>a-b).slice(0,3).reduce((a,b)=>a+b,0)/3, top = [...Array(n).keys()].sort((a,b)=>g3[a]-g3[b]).slice(0,3), mn = Math.min(...s1);
      RR.push({dist: J.dist, front, F: top.reduce((a,i)=>a+late[i]-med,0)/3, contest: s1.filter(x=>x-mn<=0.2).length}); }
    plans.forEach((p,i)=>{ tPlan += p.T[4]; tPhys += o.fin[i]; nH++; });
  }
}
function raceLevel(){ const byD = {}; RR.forEach(x => (byD[x.dist] = byD[x.dist] || []).push(x.front)); const md = {};
  for (const k in byD){ const a = byD[k].sort((p,q)=>p-q); md[k] = a[Math.floor(a.length/2)]; }
  RR.forEach(x => x.E = x.front - md[x.dist]); const ok = RR.filter(x => Math.abs(x.E) < 3);
  const X = ok.map(x=>[1,x.E,Math.min(6,x.contest)]), y = ok.map(x=>x.F), k = 3, A = Array.from({length:k},()=>new Array(k).fill(0)), b = new Array(k).fill(0);
  for (let i=0;i<X.length;i++) for (let p=0;p<k;p++){ b[p]+=X[i][p]*y[i]; for (let q=0;q<k;q++) A[p][q]+=X[i][p]*X[i][q]; }
  for (let p=0;p<k;p++){ for (let r=0;r<k;r++){ if (r===p) continue; const f=A[r][p]/A[p][p]; for (let q=p;q<k;q++) A[r][q]-=f*A[p][q]; b[r]-=f*b[p]; } }
  const c = b.map((v,p)=>v/A[p][p]); const mx = ok.reduce((a,x)=>a+x.E,0)/ok.length, my = y.reduce((a,v)=>a+v,0)/y.length;
  let sxy=0,sxx=0; ok.forEach(x=>{ sxy+=(x.E-mx)*(x.F-my); sxx+=(x.E-mx)**2; }); const sl = sxy/sxx;
  return {F: [+(my-sl*mx).toFixed(3), +sl.toFixed(3)], multi: c.map(v=>+v.toFixed(3)), contest: +(ok.reduce((a,x)=>a+x.contest,0)/ok.length).toFixed(2)}; }
const fmt = T => { const s = T.nf.reduce((a,b)=>a+b,0); return {races: T.lw[1], nf: [1,2,3,4].map(k => +(T.nf[k]/s).toFixed(3)).concat([+(T.nf.slice(5).reduce((a,b)=>a+b,0)/s).toFixed(3)]),
  Fwin: T.F.map(([w,c]) => +(w/c).toFixed(3)), leadWin: +(T.lw[0]/T.lw[1]).toFixed(3), winPos: +(T.wr.reduce((a,b)=>a+b,0)/T.wr.length).toFixed(3)}; };
console.log(JSON.stringify({pace: args.pace !== false, params, actual: fmt(A), sim: fmt(SIMT), finShift: +((tPhys-tPlan)/nH).toFixed(3), race: raceLevel()}));
