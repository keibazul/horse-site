"""v5 우승 확률 모델 학습 → winner_history/win_model_v5.joblib

사용 (PowerShell):  py -3.13 train_win_model_v5.py
  - 2002년 ~ 마지막 경주일 기록으로 학습합니다.
  - 트리 수는 '마지막 2년 전까지로 학습 → 마지막 2년으로 검증'해서 고른 뒤, 전체로 다시 학습합니다.
  - 시장 배당 결합 비중(ALPHA, BETA)도 함께 저장합니다 (predict_race.py 가 배당을 입력받으면 사용).
필요한 파일: merged.csv, race_details_all.csv.gz 또는 race_details/rd_*.csv, features_v5.py, race_feature_lib*.py
걸리는 시간: 특징 계산 수 분 + 학습 10~30분 (컴퓨터 성능에 따라). 몇 달에 한 번 다시 학습하면 충분합니다.
"""
import argparse
import os
import time
import warnings

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

import features_v5 as fv

warnings.filterwarnings("ignore")

# 시장 결합 비중:  결합 확률 ∝ exp(ALPHA·log 모델 확률 + BETA·log 시장 확률)
# 2008~2026년 연도별 순차 학습(해마다 그 전 해까지로 학습한 표본외 예측, 18,096경주)으로 추정.
# 코로나 무관중 시기(2020-02-23~2021-10-31)는 배당 시장이 비정상이라 제외.
# 이 방식으로 해마다 평가했을 때 시장만 쓸 때보다 우승마 손실 −0.0042 (95% 구간 −0.0056~−0.0029).
ALPHA, BETA = 0.1689, 0.9219


def make_model(n_trees, n_cat):
    prep = ColumnTransformer([("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=np.nan), fv.CAT)],
                             remainder="passthrough")
    return Pipeline([("prep", prep), ("clf", HistGradientBoostingClassifier(
        learning_rate=0.1, max_iter=n_trees, max_leaf_nodes=15, min_samples_leaf=200, l2_regularization=1.0,
        categorical_features=list(range(n_cat)), early_stopping=False, random_state=0))])


def race_norm(p, codes):
    return p / np.bincount(codes, weights=p)[codes]


def main():
    ap = argparse.ArgumentParser(description="v5 우승 확률 모델 학습")
    ap.add_argument("--history", default="merged.csv")
    ap.add_argument("--details", default="race_details_all.csv.gz")
    ap.add_argument("--details-dir", default="race_details")
    ap.add_argument("--until", help="이 날짜(YYYYMMDD) 이전 경주로만 학습 (지난 경주를 완전한 사전 예측으로 시험할 때)")
    ap.add_argument("--out", default=os.path.join("winner_history", "win_model_v5.joblib"))
    ap.add_argument("--start-year", type=int, default=2002)
    ap.add_argument("--max-trees", type=int, default=1000)
    args = ap.parse_args()

    t0 = time.time()
    hist = fv.load_history(args.history)
    rd = fv.load_details(args.details, args.details_dir)
    if args.until:
        hist = hist[hist["date"] < args.until]; rd = rd[rd["rcDate"] < args.until]
    print(f"기록 {hist['date'].min()}~{hist['date'].max()} ({len(hist):,}행), 경주성적정보 ~{rd['rcDate'].max()} ({len(rd):,}행)", flush=True)
    df = fv.all_features(hist, rd)
    df["year"] = df["date"].str[:4].astype(int)
    df = df[df["year"] >= args.start_year].sample(frac=1, random_state=0).reset_index(drop=True)
    print(f"특징 계산 완료: {len(df):,}행 ({time.time() - t0:.0f}s)", flush=True)

    last = int(df["year"].max())
    fit, val = df[df["year"] <= last - 2], df[df["year"] >= last - 1]
    feats = fv.CAT + [c for c in fv.NUM if fit[c].notna().any()]
    m = make_model(args.max_trees, len(fv.CAT)).fit(fit[feats], fit["is_win"])
    xv = m.named_steps["prep"].transform(val[feats])
    vc = pd.factorize(val["date"] + "_" + val["race_no"].astype(str))[0]
    vy = val["is_win"].to_numpy()
    losses = [-np.log(np.clip(race_norm(p[:, 1], vc)[vy == 1], 1e-9, None)).mean()
              for p in m.named_steps["clf"].staged_predict_proba(xv)]
    best = int(np.argmin(losses)) + 1
    print(f"트리 수 선택: {best}개 (검증 {last - 1}~{last}년 우승마 손실 {losses[best - 1]:.4f}) ({time.time() - t0:.0f}s)", flush=True)

    m = make_model(best, len(fv.CAT)).fit(df[feats], df["is_win"])
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    joblib.dump({"model": m, "features": feats, "cat_features": fv.CAT, "num_features": feats[len(fv.CAT):],
                 "alpha": ALPHA, "beta": BETA, "n_trees": best, "val_loss": losses[best - 1],
                 "trained_from": df["date"].min(), "trained_through": df["date"].max(),
                 "versions": {"numpy": np.__version__, "pandas": pd.__version__, "sklearn": sklearn.__version__}}, args.out)
    print(f"저장: {args.out} (학습 {df['date'].min()}~{df['date'].max()}, 트리 {best}개, 특징 {len(feats)}개) ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
