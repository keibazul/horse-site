"""구간 기록 예측 모델 학습 → winner_history/sect_model_v1.joblib  (경주 전개 시뮬레이션용)

말마다 '같은 경주 말들의 중앙값보다 몇 초 빠르거나 느린지'를 네 지점에서 예측합니다.
  s1f = 출발 후 200m,  g3f = 결승 600m 전,  g1f = 결승 200m 전,  fin = 결승
예측이 틀리는 정도(잔차)는 학습에 쓰지 않은 최근 2년의 실제 잔차를 묶음으로 저장해 두고,
시뮬레이션 때 그 묶음에서 뽑아 더합니다 (말 한 마리의 네 지점 잔차를 함께 뽑아 '초반에 빨랐던 말이 막판에 지치는' 관계를 살림).

사용 (PowerShell):  py -3.13 train_sectional_model.py
필요: merged.csv, race_details_all.csv.gz(+race_details/rd_*.csv), features_v5.py, race_feature_lib*.py
시간: 수 분 ~ 20분. 몇 달에 한 번이면 충분합니다.
"""
import argparse
import os
import time
import warnings

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

import features_v5 as fv

warnings.filterwarnings("ignore")
KS = ["s1f", "g3f", "g1f", "fin"]
SRC = {"s1f": "seS1fAccTime", "g3f": "seG3fAccTime", "g1f": "seG1fAccTime", "fin": "rcTime"}
POOL_KEEP = 600            # 묶음마다 저장할 잔차 수
PAR_DAYS = 1095            # 기준 시간: 그 날짜 이전 3년


def bucket_of(dist):
    """거리 구간: 0 = 1000~1200m, 1 = 1300~1400m, 2 = 1600m 이상"""
    d = np.asarray(dist, float)
    return np.select([d <= 1200, d <= 1400], [0, 1], 2)


def make(n, n_cat):
    prep = ColumnTransformer([("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=np.nan), fv.CAT)],
                             remainder="passthrough")
    return Pipeline([("prep", prep), ("reg", HistGradientBoostingRegressor(
        learning_rate=0.08, max_iter=n, max_leaf_nodes=31, min_samples_leaf=200, l2_regularization=1.0,
        categorical_features=list(range(n_cat)), early_stopping=False, random_state=0))])


def load_sectionals(gz, folder, extra=()):
    """경주성적정보에서 지점별 통과 시간·주로 상태 (extra: 더 읽을 열)"""
    import glob, re
    cols = ["rcDate", "rcNo", "hrNo", "ord", "rcDist", "track"] + list(SRC.values()) + list(extra)
    parts, last = [], ""
    if gz and os.path.exists(gz):
        d = pd.read_csv(gz, dtype=str, usecols=lambda c: c in cols); parts.append(d); last = d["rcDate"].max()
    for f in sorted(glob.glob(os.path.join(folder, "rd_*.csv"))) if folder else []:
        m = re.search(r"rd_(\d{8})\.csv$", f)
        if m and m.group(1) > last:
            parts.append(pd.read_csv(f, dtype=str, usecols=lambda c: c in cols))
    d = pd.concat(parts, ignore_index=True)
    d = d.assign(date=d["rcDate"], race_no=pd.to_numeric(d["rcNo"]).astype(int), hrNo=d["hrNo"].astype(str).str.strip().str.lstrip("0"))
    for c in ["ord", "rcDist"] + list(SRC.values()) + [c for c in extra if c not in ("diffUnit", "chulNo", "hrName", "jkName", "weather")]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d.drop_duplicates(["date", "race_no", "hrNo"], keep="last")


def track_state(track):
    s = pd.Series(track, dtype=object).astype(str).str.extract(r"^\s*(\S+?)\s*\(")[0]
    return s


def race_medians(sec):
    """경주별 지점 중앙값 시간 (정상 완주, 네 지점 기록이 모두 있는 경주만)"""
    ok = sec["ord"].between(1, 16) & np.logical_and.reduce([sec[c] > 0 for c in SRC.values()])
    s = sec[ok]
    g = s.groupby(["date", "race_no"])
    med = g[list(SRC.values())].median().rename(columns={v: k for k, v in SRC.items()})
    med["n"] = g.size()
    med["rcDist"] = g["rcDist"].first()
    med["state"] = track_state(g["track"].first()).values
    return med[med["n"] >= 5].reset_index()


def par_times(medians, date, dist, state=None):
    """그 날짜 이전 3년, 같은 거리(가능하면 같은 주로 상태) 경주들의 중앙값 시간의 중앙값"""
    lo = (pd.Timestamp(date) - pd.Timedelta(days=PAR_DAYS)).strftime("%Y%m%d")
    m = medians[(medians["date"] < date) & (medians["date"] >= lo) & (medians["rcDist"] == dist)]
    if state is not None and (m["state"] == state).sum() >= 8:
        m = m[m["state"] == state]
    if len(m) < 3:
        return None
    return {k: float(m[k].median()) for k in KS}


def main():
    ap = argparse.ArgumentParser(description="구간 기록 예측 모델 학습")
    ap.add_argument("--history", default="merged.csv")
    ap.add_argument("--details", default="race_details_all.csv.gz")
    ap.add_argument("--details-dir", default="race_details")
    ap.add_argument("--until", help="이 날짜(YYYYMMDD) 이전 경주로만 학습 (지난 경주를 완전한 사전 예측으로 시험할 때)")
    ap.add_argument("--out", default=os.path.join("winner_history", "sect_model_v1.joblib"))
    ap.add_argument("--max-trees", type=int, default=800)
    args = ap.parse_args()

    t0 = time.time()
    hist = fv.load_history(args.history)
    rd = fv.load_details(args.details, args.details_dir)
    if args.until:
        hist = hist[hist["date"] < args.until]; rd = rd[rd["rcDate"] < args.until]
    df = fv.all_features(hist, rd)
    sec = load_sectionals(args.details, args.details_dir)
    if args.until:
        sec = sec[sec["date"] < args.until]
    df = df.merge(sec[["date", "race_no", "hrNo"] + list(SRC.values())], on=["date", "race_no", "hrNo"], how="inner")
    df["year"] = df["date"].str[:4].astype(int)
    ok = np.logical_and.reduce([df[c] > 0 for c in SRC.values()]) & df["today_dist"].notna() & (df["year"] >= 2003)
    df = df[ok].copy()
    df["code"] = df["date"] + "_" + df["race_no"].astype(str)
    df = df[df.groupby("code")["hrNo"].transform("size") >= 5]
    g = df.groupby("code")
    for k, c in SRC.items():
        df[f"d_{k}"] = (df[c] - g[c].transform("median")).clip(-6, 15)
    df["bucket"] = bucket_of(df["today_dist"]); df["debut"] = (df["n_prior_races"] == 0).astype(int)
    df = df.sample(frac=1, random_state=0).reset_index(drop=True)
    last = int(df["year"].max())
    fit, val = df[df["year"] <= last - 3], df[df["year"].between(last - 2, last - 1)]
    print(f"학습 행 {len(df):,} (경주 {df['code'].nunique():,}), 트리 선택·잔차: {last - 2}~{last - 1}년 ({time.time() - t0:.0f}s)", flush=True)

    feats = fv.CAT + [c for c in fv.NUM if fit[c].notna().any()]
    best, pred_val = {}, {}
    for k in KS:
        m = make(args.max_trees, len(fv.CAT)).fit(fit[feats], fit[f"d_{k}"])
        xv = m.named_steps["prep"].transform(val[feats]); y = val[f"d_{k}"].to_numpy()
        mse = [np.mean((p - y) ** 2) for p in m.named_steps["reg"].staged_predict(xv)]
        best[k] = int(np.argmin(mse)) + 1
        pred_val[k] = list(m.named_steps["reg"].staged_predict(xv))[best[k] - 1]
        print(f"  {k}: 트리 {best[k]}, 검증 오차(RMSE) {np.sqrt(mse[best[k] - 1]):.3f}초 ({time.time() - t0:.0f}s)", flush=True)

    res = np.column_stack([val[f"d_{k}"].to_numpy() - pred_val[k] for k in KS])
    rng = np.random.default_rng(0)
    pools = {}
    for b in (0, 1, 2):
        for d in (0, 1):
            sel = ((val["bucket"] == b) & (val["debut"] == d)).to_numpy()
            if sel.sum() < 200:                                    # 첫 출전마가 적은 거리는 1000~1200m 첫 출전 묶음을 씀
                sel = ((val["bucket"] == 0) & (val["debut"] == d)).to_numpy()
            P = res[sel]
            pools[f"{b}{d}"] = np.round(P[rng.choice(len(P), min(POOL_KEEP, len(P)), replace=False)], 3)

    # 경주 전체 빠르기 변동: 경주 중앙값 / 기준 시간 (같은 거리 이전 3년)
    med = race_medians(sec)
    med["year"] = med["date"].str[:4].astype(int)
    pace = {0: [], 1: [], 2: []}
    for _, r in med[med["year"].between(last - 2, last - 1)].sample(frac=1, random_state=0).head(1500).iterrows():
        p = par_times(med, r["date"], r["rcDist"])
        if p:
            pace[int(bucket_of(r["rcDist"]))].append([r[k] / p[k] for k in KS])
    pace = {f"{b}": np.round(np.array(v[:400]), 4) for b, v in pace.items() if v}

    models = {}
    for k in KS:
        models[k] = make(best[k], len(fv.CAT)).fit(df[feats], df[f"d_{k}"])
        print(f"  전체 재학습 {k} ({time.time() - t0:.0f}s)", flush=True)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    joblib.dump({"models": models, "features": feats, "points": KS, "pools": pools, "pace": pace, "best": best,
                 "trained_through": df["date"].max()}, args.out)
    print(f"저장: {args.out} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
