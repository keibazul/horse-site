// 물리엔진 세기 맞추기: 지난 1년 경주 파일로 시뮬레이션해서 실제 기록의 초반 빠르기·선두 다툼 효과와 비교
const fs = require("fs"), path = require("path");
const PH = require(require("path").join(__dirname, "../../site/physics.js"));
const DIR = require("path").join(__dirname, "../../site/data/sim");
const R = 450 / Math.PI;
const isInner = d => d >= 1700 && d <= 2000;
function innerU(dbg){ const v = ((-dbg)%1600+1600)%1600; if (v < 50) return v; if (v < 400) return 50+(v-50)*450/350; if (v < 850) return 500+(v-400); if (v < 1200) return 950+(v-850)*450/350; return 1400+(v-1200); }
const J1000 = 1040;
function uOf(dist, dbg){ if (isInner(dist)) return innerU(dbg); if (dist === 1400 && dbg > 1300) return 500; if (dist >= 2200 && dbg > 2200) return 1400;
  if (dist === 1000 && dbg > 1800-J1000) return J1000; return ((1800-dbg)%1800+1800)%1800; }
function curveR(dist){ const r = isInner(dist) ? R - 31.8 : R; return dbg => { if (dbg <= 0) return 0; const u = uOf(dist, dbg); return ((u>=50 && u<500) || (u>=950 && u<1400)) ? r : 0; }; }
function rng(seed){ let a = seed|0; return () => { a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const KS = ["s1f","g3f","g1f","fin"];
function polyfit(x, y){ const n=x.length, mx=x.reduce((a,b)=>a+b,0)/n, my=y.reduce((a,b)=>a+b,0)/n; let sxy=0,sxx=0; for (let i=0;i<n;i++){ sxy+=(x[i]-mx)*(y[i]-my); sxx+=(x[i]-mx)**2; } const b=sxy/sxx; return [my-b*mx, b]; }
function ols(X, y){ // 작은 정규방정식
  const k = X[0].length, A = Array.from({length:k},()=>new Array(k).fill(0)), b = new Array(k).fill(0);
  for (let i=0;i<X.length;i++){ for (let p=0;p<k;p++){ b[p]+=X[i][p]*y[i]; for (let q=0;q<k;q++) A[p][q]+=X[i][p]*X[i][q]; } }
  for (let p=0;p<k;p++){ let mx=p; for (let r=p+1;r<k;r++) if (Math.abs(A[r][p])>Math.abs(A[mx][p])) mx=r; [A[p],A[mx]]=[A[mx],A[p]]; [b[p],b[mx]]=[b[mx],b[p]];
    for (let r=0;r<k;r++){ if (r===p) continue; const f=A[r][p]/A[p][p]; for (let q=p;q<k;q++) A[r][q]-=f*A[p][q]; b[r]-=f*b[p]; } }
  return b.map((v,p)=>v/A[p][p]); }
const files = fs.readdirSync(DIR).filter(f => /^sim_20(25|26)/.test(f)).sort();
const args = JSON.parse(process.argv[2] || "{}"), nRace = args.races || 400, draws = args.draws || 4, params = args.params || {}, physics = args.physics !== false;
const step = Math.max(1, Math.floor(files.length / nRace));
const rows = []; let tPlan = 0, tPhys = 0, nH = 0, blockedS = 0;
const t0 = Date.now();
for (let fi = 0; fi < files.length; fi += step){
  const J = JSON.parse(fs.readFileSync(path.join(DIR, files[fi])));
  const H = J.horses, n = H.length; if (n < 6) continue;
  const race = {dist: J.dist, curveR: curveR(J.dist)}, r = rng(fi*97+1);
  const maxNo = Math.max(...H.map(h=>h.no)), lanes0 = H.map(h => 1.2 + (h.no-1)*1.3*Math.min(1, 13/maxNo));
  for (let d = 0; d < draws; d++){
    const pr = J.pace[Math.floor(r()*J.pace.length)] || [1,1,1,1], pace = pr.map(v => 1 + 0.5*(v-1));
    const plans = H.map(h => { const pool = J.pools[h.debut ? "1" : "0"], res = pool[Math.floor(r()*pool.length)];
      const T = KS.map((k,j) => J.par[k]*pace[j] + h.pred[k] + res[j]);
      return T; });
    if (args.pace !== false){ const sh = PH.paceShift(plans.map(T => T[0])); plans.forEach((T,i) => { T[1] += sh[i][0]; T[2] += sh[i][1]; T[3] += sh[i][2]; }); }   // 전개 효과 ({"pace":false} 로 끔)
    plans.forEach((T,i) => { T[0]=Math.max(T[0],11); T[1]=Math.max(T[1],T[0]+3); T[2]=Math.max(T[2],T[1]+3); T[3]=Math.max(T[3],T[2]+8); plans[i] = {T:[0,...T]}; });
    let s1, g3, fin;
    if (physics){ const o = PH.run(race, plans, {dt: args.dt || 0.2, lanes0, params}); s1 = o.cp.s1f; g3 = o.cp.g3f; fin = o.fin;
      plans.forEach((p,i)=>{ tPlan += p.T[4]; tPhys += fin[i]; nH++; blockedS += o.blocked[i]; }); }
    else { s1 = plans.map(p=>p.T[1]); g3 = plans.map(p=>p.T[2]); fin = plans.map(p=>p.T[4]); }
    const late = fin.map((f,i)=>f-g3[i]), sl = [...late].sort((a,b)=>a-b), med = sl[Math.floor(n/2)];
    const front = [...s1].sort((a,b)=>a-b).slice(0,3).reduce((a,b)=>a+b,0)/3;
    const top = [...Array(n).keys()].sort((a,b)=>g3[a]-g3[b]).slice(0,3);
    const mn = Math.min(...s1);
    rows.push({dist: J.dist, front, F: top.reduce((a,i)=>a+late[i]-med,0)/3, contest: s1.filter(x=>x-mn<=0.2).length});
  }
}
const byDist = {}; rows.forEach(x => (byDist[x.dist] = byDist[x.dist] || []).push(x.front));
const medD = {}; for (const k in byDist){ const a = byDist[k].sort((p,q)=>p-q); medD[k] = a[Math.floor(a.length/2)]; }
rows.forEach(x => x.E = x.front - medD[x.dist]);
const ok = rows.filter(x => Math.abs(x.E) < 3);
const [a, b] = polyfit(ok.map(x=>x.E), ok.map(x=>x.F));
const c = ols(ok.map(x=>[1, x.E, Math.min(6, x.contest)]), ok.map(x=>x.F));
const cm = ok.reduce((s,x)=>s+x.contest,0)/ok.length;
console.log(JSON.stringify({physics, params, races: ok.length, F: [+a.toFixed(3), +b.toFixed(3)], multi: c.map(v=>+v.toFixed(3)), contest: +cm.toFixed(2),
  finShift: nH ? +((tPhys - tPlan)/nH).toFixed(3) : 0, blocked: nH ? +(blockedS/nH).toFixed(2) : 0, sec: (Date.now()-t0)/1000}));
