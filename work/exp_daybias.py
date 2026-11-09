"""실험: 당일 게이트 경향을 모델 입력으로 넣으면 나아지는가 (GitHub Actions 에서 실행)
같은 조건: 2002~2022 로 학습 → 2023~2024 로 트리 수 선택 → 2002~2024 로 다시 학습 → 2025-01-01 ~ 마지막 경주일 평가
  base     : 지금 특징
  base×보정: base 확률에 exp(0.157·IB·(0.5−게이트)) 를 곱함 (지금 사이트 방식)
  day      : 당일 게이트 경향 특징 3개를 넣어 학습
평가: 우승마 로그 손실 — 모델만 / 확정 단승 배당과 결합(α 0.1689, β 0.9219), 경주일 단위 부트스트랩 95% 구간
"""
import time
import numpy as np, pandas as pd
import features_v5 as fv
from train_win_model_v5 import make_model, race_norm

t0 = time.time()
hist = fv.load_history("merged.csv"); rd = fv.load_details("race_details_all.csv.gz", "race_details")
df = fv.all_features(hist, rd)
df["year"] = df["date"].str[:4].astype(int)
df = df[df["year"] >= 2002].reset_index(drop=True)
odds = rd[["rcDate", "rcNo", "hrNo", "winOdds"]].rename(columns={"rcDate": "date"})
odds["race_no"] = pd.to_numeric(odds["rcNo"], errors="coerce"); odds["winOdds"] = pd.to_numeric(odds["winOdds"], errors="coerce")
df = df.merge(odds[["date", "race_no", "hrNo", "winOdds"]].drop_duplicates(["date", "race_no", "hrNo"]), on=["date", "race_no", "hrNo"], how="left")
print(f"특징 {len(df):,}행 ({time.time()-t0:.0f}s)", flush=True)
base = fv.CAT + [c for c in fv.NUM if c not in fv.DAY_FEATURES and df[c].notna().any()]
day = base + fv.DAY_FEATURES
fit, val = df[df["date"] < "20230101"], df[(df["date"] >= "20230101") & (df["date"] < "20250101")]
full, test = df[df["date"] < "20250101"], df[df["date"] >= "20250101"].copy()

def trees(feats):
    m = make_model(1000, len(fv.CAT)).fit(fit[feats], fit["is_win"])
    xv = m.named_steps["prep"].transform(val[feats]); vc = pd.factorize(val["date"] + "_" + val["race_no"].astype(str))[0]; vy = val["is_win"].to_numpy()
    L = [-np.log(np.clip(race_norm(p[:, 1], vc)[vy == 1], 1e-9, None)).mean() for p in m.named_steps["clf"].staged_predict_proba(xv)]
    return int(np.argmin(L)) + 1, min(L)

rid = test["date"] + "_" + test["race_no"].astype(str)
codes = pd.factorize(rid)[0]
P = {}
for name, feats in [("base", base), ("day", day)]:
    n, l = trees(feats); print(f"{name}: 트리 {n}, 검증 손실 {l:.4f} ({time.time()-t0:.0f}s)", flush=True)
    m = make_model(n, len(fv.CAT)).fit(full[feats], full["is_win"])
    P[name] = race_norm(m.predict_proba(test[feats])[:, 1], codes)
fac = np.exp(0.157 * test["day_ib"].fillna(0).to_numpy() * (0.5 - test["gate_pos"].fillna(0.5).to_numpy()))
P["base×보정"] = race_norm(P["base"] * fac, codes)
y = test["is_win"].to_numpy().astype(bool)
ok_r = pd.Series(y).groupby(codes).transform("sum").to_numpy() == 1
od = test["winOdds"].to_numpy()
has_od = pd.Series(od > 1).groupby(codes).transform("all").to_numpy()
q = np.where(od > 1, 1 / od, np.nan); q = q / pd.Series(q).groupby(codes).transform("sum").to_numpy()
days = test["date"].to_numpy()

def loss_by_race(p, mask):
    lr = pd.Series(-np.log(np.clip(p, 1e-9, None)) * y).groupby(codes).sum()
    keep = pd.Series(mask).groupby(codes).all()
    return lr[keep]

dmap = pd.Series(days).groupby(codes).first()
rng = np.random.default_rng(0); ud = dmap.unique(); B = [rng.choice(ud, len(ud)) for _ in range(500)]
def report(label, a, b):
    x = (b - a); xd = x.groupby(dmap[x.index].values).agg(["sum", "count"])
    bs = [xd.loc[s, "sum"].sum() / xd.loc[s, "count"].sum() for s in B]
    print(f"{label:30s} 경주 {len(x):5d}  차이 {x.mean():+.5f}  95% [{np.percentile(bs, 2.5):+.5f}, {np.percentile(bs, 97.5):+.5f}]", flush=True)
mask = ok_r
L = {k: loss_by_race(v, mask) for k, v in P.items()}
for k in L: print(f"모델만 {k:10s} 손실 {L[k].mean():.4f}")
report("모델만: day − base", L["base"], L["day"])
report("모델만: base×보정 − base", L["base"], L["base×보정"])
report("모델만: day − base×보정", L["base×보정"], L["day"])
mask2 = ok_r & has_od
def comb(p):
    s = np.exp(0.1689 * np.log(np.clip(p, 1e-9, None)) + 0.9219 * np.log(np.clip(q, 1e-9, None)))
    return race_norm(np.where(np.isnan(s), 0, s) + 1e-12, codes)
C = {k: loss_by_race(comb(v), mask2) for k, v in P.items()}
C["시장"] = loss_by_race(np.nan_to_num(q, nan=1e-9), mask2)
for k in C: print(f"결합 {k:10s} 손실 {C[k].mean():.4f}")
report("결합: day − base", C["base"], C["day"])
report("결합: base×보정 − base", C["base"], C["base×보정"])
report("결합: day − base×보정", C["base×보정"], C["day"])
report("결합 day − 시장", C["시장"], C["day"])
print(f"끝 ({time.time()-t0:.0f}s)")
