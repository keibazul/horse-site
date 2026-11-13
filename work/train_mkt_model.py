"""배당 반영 우승 확률 모델 (mkt v1): v5 특징 + 그 경주의 단승 배당(시장) → 우승 확률

지금 결합(α·log 모델 + β·log 시장 + γ·(log 시장)²)은 모델과 시장을 정해진 식으로 섞는다.
이 모델은 배당을 특징으로 받아, 거리·등급·말 상태에 따라 시장이 틀리는 패턴을 직접 배운다.

검증 (2026-11-13, 연도마다 그 전 해까지 학습 → 그해 예측, 2016~2026 9,678경주, 코로나 무관중 제외):
  우승마 로그 손실  시장 1.7783, 지금 결합 1.7729, 이 모델 1.7656
  이 모델 − 지금 결합 −0.0073 [−0.0111, −0.0036] (11개 연도 중 9개에서 나음), 확률 보정 구간별 0.97~1.05
  단승: 확률 × 확정 배당 ≥ 1.2 인 말만 1장씩 → 3,371장 회수율 114% [99, 130] (연도별 73~153%, 11개 중 8개 100% 넘음)
        ≥ 1.0 → 11,347장 105% [97, 112]. 확정 배당으로 고른 결과라 실제(살 때 배당)는 더 나쁠 수 있음.
  작은 2단계 모델(모델 확률 + 시장 특징만)은 지금 결합보다 낫지 않았음 → 말 특징과 배당을 함께 봐야 효과가 남.

사이트: 사용자가 단승 배당을 모두 넣으면 브라우저가 이 모델을 직접 계산 (site/data/model/mkt_v1.json, site/assets/mktmodel.js).
말마다 특징은 site_export 가 site/data/mkx/날짜.json 에 저장.

사용: python train_mkt_model.py [--features-pkl 특징.pkl] [--until 20261101]
"""
import argparse
import glob
import json
import os
import time

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

import features_v5 as fv
import race_feature_lib as lib

MK = ["m_lq", "m_rank", "m_rel", "m_n", "m_top"]
COVID = ("20200223", "20211031")
HERE = os.path.dirname(os.path.abspath(__file__))
SITE_MODEL = os.path.join(HERE, "..", "site", "data", "model", "mkt_v1.json")


def market_features(df: pd.DataFrame, rid: pd.Series, odds: pd.Series) -> pd.DataFrame:
    """경주 안 단승 배당 → 시장 특징 (브라우저 mktmodel.js 와 같은 계산)"""
    q = 1 / odds
    q = q / q.groupby(rid).transform("sum")
    g = q.groupby(rid)
    return pd.DataFrame({"m_lq": np.log(q), "m_rank": g.rank(ascending=False, method="first"), "m_rel": q / g.transform("max"),
                         "m_n": g.transform("size").astype(float), "m_top": g.transform("max")}, index=df.index)


def make_model(n_trees: int) -> Pipeline:
    prep = ColumnTransformer([("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=np.nan), fv.CAT)], remainder="passthrough")
    return Pipeline([("prep", prep), ("clf", HistGradientBoostingClassifier(
        learning_rate=0.05, max_iter=n_trees, max_leaf_nodes=15, min_samples_leaf=200, l2_regularization=1.0,
        categorical_features=list(range(len(fv.CAT))), early_stopping=False, random_state=0))])


def export_json(art: dict, path: str) -> int:
    """브라우저용: 트리마다 노드 배열 (sklearn HistGradientBoosting 의 예측 규칙 그대로)"""
    pipe = art["model"]
    enc = pipe.named_steps["prep"].named_transformers_["cat"]
    clf = pipe.named_steps["clf"]
    trees = []
    for it in clf._predictors:
        pr = it[0]
        nd = pr.nodes
        trees.append({
            "f": nd["feature_idx"].astype(int).tolist(),
            "t": [float(v) for v in nd["num_threshold"]],        # 그대로 (줄이면 0.9999999999999999 같은 경계가 1.0 이 되어 길이 바뀜)
            "l": nd["left"].astype(int).tolist(), "r": nd["right"].astype(int).tolist(),
            "m": nd["missing_go_to_left"].astype(int).tolist(), "leaf": nd["is_leaf"].astype(int).tolist(),
            "v": [float(v) for v in nd["value"]],
            "c": nd["is_categorical"].astype(int).tolist(), "b": nd["bitset_idx"].astype(int).tolist(),
            "bits": pr.raw_left_cat_bitsets.astype(np.int64).tolist(),
        })
    out = {"name": "mkt_v1", "trained_through": art["trained_through"], "features": art["features"], "n_cat": len(fv.CAT),
           "categories": [[str(x) for x in c] for c in enc.categories_], "market": MK,
           "baseline": float(np.ravel(clf._baseline_prediction)[0]), "trees": trees}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history", default="merged.csv")
    ap.add_argument("--details", default="race_details_all.csv.gz")
    ap.add_argument("--details-dir", default="race_details")
    ap.add_argument("--features-pkl", help="fv.all_features 결과를 미리 저장한 파일 (없으면 새로 계산)")
    ap.add_argument("--until")
    ap.add_argument("--out", default=os.path.join("winner_history", "win_mkt_v1.joblib"))
    ap.add_argument("--max-trees", type=int, default=1500)
    ap.add_argument("--no-site", action="store_true", help="사이트용 JSON 을 쓰지 않음")
    a = ap.parse_args()
    t0 = time.time()
    rd = fv.load_details(a.details, a.details_dir)
    if a.features_pkl:
        df = pd.read_pickle(a.features_pkl)
    else:
        df = fv.all_features(fv.load_history(a.history), rd)
    if a.until:
        df = df[df["date"] < a.until]
    od = rd[["rcDate", "rcNo", "hrNo", "winOdds"]].copy()
    od["hrNo"] = lib.normalize_id(od["hrNo"].astype(str)); od["race_no"] = pd.to_numeric(od["rcNo"], errors="coerce")
    od["winOdds"] = pd.to_numeric(od["winOdds"], errors="coerce")
    od = od.rename(columns={"rcDate": "date"}).drop_duplicates(["date", "race_no", "hrNo"], keep="last")
    df = df.copy(); df["hrNo"] = lib.normalize_id(df["hrNo"].astype(str))
    df = df.merge(od[["date", "race_no", "hrNo", "winOdds"]], on=["date", "race_no", "hrNo"], how="left")
    df = df[~df["date"].between(*COVID)]
    rid = df["date"] + "_" + df["race_no"].astype(str)
    g = df.groupby(rid)
    ok = g["winOdds"].transform(lambda s: s.notna().all() and (s > 0).all() and (s < 9999).all()) & (g["is_win"].transform("sum") == 1) & (g["hrNo"].transform("size") >= 5)
    df, rid = df[ok].copy(), rid[ok]
    df = pd.concat([df, market_features(df, rid, df["winOdds"])], axis=1)
    df["rid"] = rid
    df["year"] = df["date"].str[:4].astype(int)
    df = df[df["year"] >= 2002].reset_index(drop=True)
    feats = fv.CAT + [c for c in fv.NUM if df[c].nunique() > 1] + MK
    print(f"학습 자료 {df['date'].min()}~{df['date'].max()} {df['rid'].nunique():,}경주 {len(df):,}행, 특징 {len(feats)} ({time.time() - t0:.0f}s)", flush=True)

    last = int(df["year"].max())
    fit, val = df[df["year"] <= last - 2], df[df["year"] >= last - 1]
    m = make_model(a.max_trees).fit(fit[feats], fit["is_win"])
    xv = m.named_steps["prep"].transform(val[feats])
    vc = pd.factorize(val["rid"])[0]; vy = val["is_win"].to_numpy()
    losses = []
    for k, p in enumerate(m.named_steps["clf"].staged_predict_proba(xv)):
        pp = p[:, 1] / np.bincount(vc, weights=p[:, 1])[vc]
        losses.append(-np.log(np.clip(pp[vy == 1], 1e-9, None)).mean())
    best = int(np.argmin(losses)) + 1
    print(f"트리 수 {best} (검증 {last - 1}~{last} 손실 {losses[best - 1]:.4f}) ({time.time() - t0:.0f}s)", flush=True)
    m = make_model(best).fit(df[feats], df["is_win"])
    art = {"model": m, "features": feats, "cat_features": fv.CAT, "market": MK, "n_trees": best, "val_loss": losses[best - 1],
           "trained_from": df["date"].min(), "trained_through": df["date"].max(),
           "versions": {"numpy": np.__version__, "pandas": pd.__version__, "sklearn": sklearn.__version__}}
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    joblib.dump(art, a.out)
    print(f"저장 {a.out} (~{art['trained_through']}, 트리 {best})", flush=True)
    if not a.no_site:
        print(f"사이트용 {SITE_MODEL}: {export_json(art, SITE_MODEL) / 1e6:.2f}MB ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
