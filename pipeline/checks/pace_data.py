import pandas as pd, numpy as np, glob
W="work/"
cols=["rcDate","rcNo","hrNo","ord","rcDist","track","seS1fAccTime","seG3fAccTime","seG1fAccTime","rcTime","sjS1fOrd","sjG3fOrd"]
d=pd.read_csv(W+"race_details_all.csv.gz",dtype=str,usecols=cols)
for f in glob.glob(W+"race_details/rd_*.csv"): d=pd.concat([d,pd.read_csv(f,dtype=str,usecols=cols)])
for c in cols[3:]:
    if c!="track": d[c]=pd.to_numeric(d[c],errors="coerce")
d=d[(d.rcDate>="20150101")&d.ord.between(1,16)&(d.seS1fAccTime>0)&(d.seG3fAccTime>0)&(d.rcTime>0)]
d["rid"]=d.rcDate+"_"+d.rcNo
d["n"]=d.groupby("rid").hrNo.transform("size"); d=d[d.n>=6]
d["late"]=d.rcTime-d.seG3fAccTime                       # 결승 600m 전 → 결승
d["late_rel"]=d.late-d.groupby("rid").late.transform("median")
d["yr"]=d.rcDate.str[:4]
# 경주 초반 빠르기: 200m 지점 상위 3두 평균 시간 − (같은 해·같은 거리) 중앙값
g=d.sort_values("seS1fAccTime").groupby("rid")
front=g.head(3).groupby("rid").seS1fAccTime.mean().rename("front_s1f")
r=d.groupby("rid").agg(dist=("rcDist","first"),yr=("yr","first"),n=("n","first")).join(front)
r["E"]=r.front_s1f-r.groupby(["yr","dist"]).front_s1f.transform("median")
# 초반 경합: 200m 지점에서 선두와 0.2초 안의 말 수
lead=d.groupby("rid").seS1fAccTime.transform("min")
r["contest"]=(d.seS1fAccTime-lead<=0.2).groupby(d.rid).sum()
# 600m 전 지점 상위 3두의 막판(600m) 상대 기록
top=d[d.sjG3fOrd.between(1,3)].groupby("rid").late_rel.mean().rename("F")
r=r.join(top).dropna()
r=r[r.E.abs()<3]
print("경주", len(r))
b=np.polyfit(r.E, r.F, 1); print(f"앞선 말 막판 상대기록 F = {b[1]:.3f} + {b[0]:.3f}×E   (E: 초반 상위3두 200m 기록 − 보통, 초. 음수=빠름)")
r["Eb"]=pd.cut(r.E,[-3,-0.6,-0.3,-0.1,0.1,0.3,0.6,3])
print(r.groupby("Eb",observed=True).F.agg(["mean","count"]).round(3).to_string())
print(r.groupby(r.contest.clip(upper=6)).F.agg(["mean","count"]).round(3).to_string())
# 경합 효과를 초반 빠르기와 함께
X=np.column_stack([np.ones(len(r)), r.E, r.contest.clip(upper=6)]); c=np.linalg.lstsq(X, r.F, rcond=None)[0]; print("F ~ 1 + E + contest:", np.round(c,3))
# 말 단위: 200m 지점 선두권(1~2위) 말 중, 같은 경주 선두권 경쟁자가 많을수록 막판이 더 처지나
d["frontS1"]=d.sjS1fOrd.between(1,2)
x=d[d.frontS1].join(r[["E","contest"]],on="rid").dropna()
c2=np.linalg.lstsq(np.column_stack([np.ones(len(x)),x.E,x.contest.clip(upper=6)]), x.late_rel, rcond=None)[0]
print("200m 선두권 말 막판 상대기록 ~ 1 + E + contest:", np.round(c2,3), "n", len(x))
r.to_csv("race_pace.csv")
