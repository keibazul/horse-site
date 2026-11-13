"""배당 반영 모델(mkt) 변형 실험 틀 — 연도별 순차 표본외 (2026-11-14)

검증 방식 (work/train_mkt_model.py 의 검증과 같음, work/backtest/mkt_win.json.gz 와 2017~2026년 값이 소수 6자리까지 일치하는 것을 확인):
  - Y = 2016~2026: 그 전 해까지(2002~Y-1, 코로나 무관중 2020-02-23~2021-10-31 제외) 학습 → Y해 예측
  - Y해 트리 수 = '<Y-1 학습 모델의 Y-1해 손실이 가장 작은 트리 수' (50 단위, 최대 1500)
  - 우승마 로그 손실(경주 안 합 1), 기준 대비 차이는 경주 단위 부트스트랩 95%
  - 단승 p≥5%·p×확정 배당≥1.2 를 1장씩, 2016~2022(A) / 2023~2026(B), 경주일 단위 부트스트랩

누수 2건 (이 실험에서 찾음)
  1) 순위 특징의 동률 처리: rank(method="first") 는 행 순서(= 착순)대로 동률을 가름 → 배당이 같은 말끼리 먼저 들어온 말이 앞 순위.
     단승 배당 동률은 출주의 1.8% 라 지금 모델 영향은 작았지만(1.7656 → 1.7657), 연승 배당은 동률이 10.6%(우승마의 15%)라
     p_rank 를 그렇게 만들면 손실이 −0.0166 이나 '좋아지는' 가짜 결과가 나옴. → 이 파일의 rank_desc (동률은 출전 번호 순, 브라우저와 같음).
     train_mkt_model.market_features 는 아직 method="first" (고칠지는 사용자 확인 뒤).
  2) 연승 배당 자체는 결과와 무관: 서울 연승 배당 = 0.8 × 풀 ÷ (입상 두수 × 그 말 매출) → Σ 0.8/(3×연승 배당) = 0.977 (사분위 0.972~0.981),
     실제 입상한 인기마 수에 따라 달라지지 않음 (경주 전 정보로 설명하고 남는 잔차 차이 0.01 미만).

결과 (9,678경주. 기준 base = 지금 모델과 같은 설정에서 순위 동률만 고친 것. 회수율 = 단승 p≥5%·기대값≥1.2, 전체 / 2016~2022 / 2023~2026)
  변형                              손실     기준 대비 [95%]               나은 해  회수율 %
  지금 모델 (저장된 검증 자료)        1.7656                                         125.2 / 135.2 / 115.5 (2,324장)
  base (동률 누수 고침)              1.7657   +0.0001 [−0.0017, +0.0019]             122.8 / 121.7 / 123.8 (2,048장)
  plc   1) 연승 배당 3개             1.7636   −0.0022 [−0.0044, +0.0000]   10/11    128.6 / 129.2 / 128.2
  plc2  1) 연승 배당, 순위 빼고 2개   1.7633   −0.0024 [−0.0048, +0.0000]    9/11    123.7 / 118.9 / 127.9
  race  2) 경주 단위 시장 특징 4개    1.7648   −0.0010 [−0.0031, +0.0010]    6/11    117.3 / 127.8 / 110.6
  w8    3) 최근 연도 가중(반감기 8년)  1.7664   +0.0006 [−0.0022, +0.0035]    6/11    125.5 / 124.0 / 127.0
  s1    4) 표본외 착순·3착 안 점수    1.7649   −0.0008 [−0.0033, +0.0017]    5/11    124.2 / 128.6 / 119.3
  mono  5) 배당 특징 단조 제약        1.7645   −0.0012 [−0.0032, +0.0007]    7/11    128.2 / 132.0 / 124.1
  k40   6) 특징 98 → 50개            1.7675   +0.0018 [−0.0007, +0.0041]    2/11    124.2 / 133.2 / 114.4
  → 구간까지 확실히 나아진 변형 없음 = 채택 없음. 연승 배당만 경계선(구간 위쪽 끝이 0).
  (동률 누수가 있는 채로 연승 배당을 넣으면 1.7491, −0.0166 [−0.0202, −0.0132], 회수율 138.5% 로 보임 — 가짜)

사용:  python exp_mkt_variants.py prep                 # 특징·배당 자료 (exp/data.pkl), 1단계 점수(exp/stage1.pkl), 중요도(exp/prune.json)
       python exp_mkt_variants.py run base plc ...     # 변형 학습 → exp/oos_이름.pkl
       python exp_mkt_variants.py report base plc ...  # 첫 이름이 기준
       python exp_mkt_variants.py backtest base        # exp/oos_base.pkl → backtest/mkt_win.json.gz (그 뒤 node pipeline/checks/plan_backtest.js)
"""
import gzip
import json
import os
import sys
import time

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

import features_v5 as fv
import race_feature_lib as lib
import train_mkt_model as tm

EXP = "exp"
MK = tm.MK
PL = ["p_lq", "p_rank", "p_diff"]                    # 후보 5: 연승 풀 몫(로그)·순위·단승 풀과의 차이
RC = ["m_ent", "m_sd", "m_gap", "m_gapr"]            # 후보 6: 배당 엔트로피·로그 확률 표준편차·1·2번 인기 차(차이, 로그 비)
S1 = ["s_ord", "s_top3", "s_ord_rel", "s_top3_rel"]  # 후보 23: 표본외 착순 점수·3착 안 점수 (+ 경주 안 상대값)
MONO = {"m_lq": 1, "m_rank": -1, "m_rel": 1}         # 후보 24
STEP, MAX_TREES = 50, 1500


def rank_desc(v, rid, chul):
    """경주 안에서 큰 값부터 1, 2, … 값이 같으면 출전 번호가 작은 말이 앞 (브라우저 mktmodel.js 와 같음).
    rank(method="first") 는 행 순서(= 착순)대로 동률을 갈라 결과가 샘."""
    o = pd.DataFrame({"r": rid, "v": -v, "c": pd.to_numeric(chul, errors="coerce")}).sort_values(["r", "v", "c"], kind="stable")
    return (o.groupby("r").cumcount() + 1).reindex(v.index).astype(float)


def place_features(rid, plc, m_lq, chul):
    b = 1 / plc.clip(lower=1.0)
    b = b / b.groupby(rid).transform("sum")
    lb = np.log(b)
    return pd.DataFrame({"p_lq": lb, "p_rank": rank_desc(b, rid, chul), "p_diff": lb - m_lq}, index=plc.index)


def _pipe(est, cats, **kw):
    prep = ColumnTransformer([("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=np.nan), cats)], remainder="passthrough")
    return Pipeline([("prep", prep), ("m", est(max_leaf_nodes=15, min_samples_leaf=200, l2_regularization=1.0,
                                               categorical_features=list(range(len(cats))), random_state=0, **kw))])


# ---------------------------------------------------------------- 자료
def prep(history="merged.csv"):
    os.makedirs(EXP, exist_ok=True)
    rd = fv.load_details("race_details_all.csv.gz", "race_details")
    df = fv.all_features(fv.load_history(history), rd)
    od = rd[["rcDate", "rcNo", "hrNo", "winOdds", "plcOdds", "chulNo"]].copy()
    od["hrNo"] = lib.normalize_id(od["hrNo"].astype(str)); od["race_no"] = pd.to_numeric(od["rcNo"], errors="coerce")
    for c in ("winOdds", "plcOdds"):
        od[c] = pd.to_numeric(od[c], errors="coerce")
    od["chul_rd"] = pd.to_numeric(od["chulNo"], errors="coerce")
    od = od.rename(columns={"rcDate": "date"}).drop_duplicates(["date", "race_no", "hrNo"], keep="last")
    df["hrNo"] = lib.normalize_id(df["hrNo"].astype(str))
    df = df.merge(od[["date", "race_no", "hrNo", "winOdds", "plcOdds", "chul_rd"]], on=["date", "race_no", "hrNo"], how="left")
    df["rid"] = df["date"] + "_" + df["race_no"].astype(str); df["year"] = df["date"].str[:4].astype(int)
    g = df.groupby("rid")
    df["ok"] = (g["winOdds"].transform(lambda s: s.notna().all() and (s > 0).all() and (s < 9999).all()) & (g["is_win"].transform("sum") == 1)
                & (g["hrNo"].transform("size") >= 5) & ~df["date"].between(*tm.COVID) & (df["year"] >= 2002))
    df.to_pickle(f"{EXP}/data.pkl")
    # 1단계 점수: 해마다 그 전 해까지 기록으로 학습한 '정규화 착순' 회귀와 '3착 안' 분류 (배당 없이 v5 특징만) → 그해 점수
    d = df[df.year >= 2002].copy(); F = fv.CAT + fv.NUM
    d["s_ord"] = np.nan; d["s_top3"] = np.nan
    for Y in range(2005, int(d.year.max()) + 1):
        tr, te = d[(d.year < Y) & d.ord_pct.notna()], d.year == Y
        f = [c for c in F if c in fv.CAT or tr[c].nunique() > 1]
        kw = dict(learning_rate=0.08, max_iter=250)
        d.loc[te, "s_ord"] = _pipe(HistGradientBoostingRegressor, fv.CAT, **kw).fit(tr[f], tr.ord_pct).predict(d.loc[te, f])
        d.loc[te, "s_top3"] = _pipe(HistGradientBoostingClassifier, fv.CAT, **kw).fit(tr[f], tr.is_top3).predict_proba(d.loc[te, f])[:, 1]
    d[["date", "race_no", "hrNo", "s_ord", "s_top3"]].to_pickle(f"{EXP}/stage1.pkl")
    # 특징 중요도: 2013년 전까지 학습 → 2013~2014년(검증 기간 밖) 순열 중요도
    x = load(); F = base_feats(x)
    tr, te = x[x.year < 2013], x[x.year.between(2013, 2014)]
    f = [c for c in F if c in fv.CAT or tr[c].nunique() > 1]
    m = make(400, f).fit(tr[f], tr.is_win)
    rc = pd.factorize(te.rid)[0]; y = te.is_win.to_numpy(); rng = np.random.default_rng(0)

    def loss(X):
        p = m.predict_proba(X)[:, 1]; p = p / np.bincount(rc, weights=p)[rc]
        return -np.log(p[y == 1]).mean()
    b = loss(te[f]); imp = {}
    for c in f:
        v = []
        for _ in range(3):
            X = te[f].copy(); X[c] = X[c].to_numpy()[rng.permutation(len(X))]; v.append(loss(X) - b)
        imp[c] = float(np.mean(v))
    json.dump({"late": [c for c in F if c not in f], "rank": sorted(imp.items(), key=lambda kv: -kv[1])}, open(f"{EXP}/prune.json", "w"), ensure_ascii=False)


def load():
    df = pd.read_pickle(f"{EXP}/data.pkl")
    df = df[df.ok].reset_index(drop=True)
    df = pd.concat([df, tm.market_features(df, df["rid"], df["winOdds"])], axis=1)
    df["m_rank"] = rank_desc(np.exp(df["m_lq"]), df["rid"], df["chulNo"])      # 동률 누수 고침 (train_mkt_model 은 아직 method="first")
    df = pd.concat([df, place_features(df["rid"], df["plcOdds"], df["m_lq"], df["chulNo"])], axis=1)
    q = np.exp(df["m_lq"])
    df["m_ent"] = (-(q * df["m_lq"])).groupby(df["rid"]).transform("sum")
    df["m_sd"] = df.groupby("rid")["m_lq"].transform("std")
    q2 = q.where(df["m_rank"] == 2).groupby(df["rid"]).transform("max")
    df["m_gap"] = df["m_top"] - q2; df["m_gapr"] = np.log(df["m_top"] / q2)
    if os.path.exists(f"{EXP}/stage1.pkl"):
        df = df.merge(pd.read_pickle(f"{EXP}/stage1.pkl"), on=["date", "race_no", "hrNo"], how="left")
        df["s_ord_rel"] = df["s_ord"] - df.groupby("rid")["s_ord"].transform("mean")
        df["s_top3_rel"] = df["s_top3"] / df.groupby("rid")["s_top3"].transform("sum")
    return df


def base_feats(df):
    return fv.CAT + [c for c in fv.NUM if df[c].nunique() > 1] + MK


def pruned(df, k):
    """순열 중요도 상위 k개 + 범주형 4개 + 2013년 뒤에 생긴 특징(장구·레이팅) + 시장 특징"""
    P = json.load(open(f"{EXP}/prune.json"))
    keep = set([c for c, _ in P["rank"] if c not in MK][:k]) | set(P["late"]) | set(MK) | set(fv.CAT)
    return [c for c in base_feats(df) if c in keep]


def make(n_trees, feats, mono=None):
    cst = [0] * len(fv.CAT) + [mono.get(c, 0) for c in feats if c not in fv.CAT] if mono else None
    return _pipe(HistGradientBoostingClassifier, fv.CAT, learning_rate=0.05, max_iter=n_trees, monotonic_cst=cst, early_stopping=False)


# ---------------------------------------------------------------- 순차 학습
def run(name, df, feats, weight=None, mono=None):
    t0 = time.time(); n_sel = None; parts = []
    for Y in range(2015, int(df.year.max()) + 1):
        tr, te = df[df.year < Y], df[df.year == Y]
        f = [c for c in feats if c in fv.CAT or tr[c].nunique() > 1]          # 그때까지 값이 없는 특징은 뺌
        m = make(MAX_TREES, f, mono)
        m.fit(tr[f], tr["is_win"], **({"m__sample_weight": weight(tr["year"].to_numpy(), Y)} if weight else {}))
        x = m.named_steps["prep"].transform(te[f]); rc = pd.factorize(te["rid"])[0]; y = te["is_win"].to_numpy()
        losses = []
        for k, p in enumerate(m.named_steps["m"].staged_predict_proba(x)):
            pp = p[:, 1] / np.bincount(rc, weights=p[:, 1])[rc]
            losses.append(-np.log(np.clip(pp[y == 1], 1e-9, None)).mean())
            if k + 1 == n_sel:
                o = te[["rid", "hrNo", "chul_rd", "year", "date", "winOdds", "is_win"]].copy(); o["p"] = pp; parts.append(o)
        print(f"[{name}] {Y} 트리 {n_sel} 손실 {losses[n_sel - 1] if n_sel else float('nan'):.4f} ({time.time() - t0:.0f}s)", flush=True)
        n_sel = (int(np.argmin(losses[STEP - 1::STEP])) + 1) * STEP
    pd.concat(parts).to_pickle(f"{EXP}/oos_{name}.pkl")


def variants(df):
    F = base_feats(df)
    hl = lambda h: (lambda yr, Y: 0.5 ** ((Y - 1 - yr) / h))                   # 최근 연도 가중 (반감기 h년)
    return {
        "base": dict(feats=F),
        "plc": dict(feats=F + PL), "plc2": dict(feats=F + ["p_lq", "p_diff"]),
        "race": dict(feats=F + RC),
        "w8": dict(feats=F, weight=hl(8)),
        "s1": dict(feats=F + S1),
        "mono": dict(feats=F, mono=MONO),
        "k40": dict(feats=pruned(df, 40)) if os.path.exists(f"{EXP}/prune.json") else None,
    }


# ---------------------------------------------------------------- 비교
def _races(o):
    w = o[o.is_win == 1].set_index("rid")
    return pd.DataFrame({"loss": -np.log(w.p.clip(lower=1e-9)), "year": w.year})


def _roi(o, dates, rng):
    b = o[(o.p >= 0.05) & (o.p * o.winOdds >= 1.2)]
    d = b.assign(ret=b.winOdds * b.is_win).groupby("date").agg(s=("ret", "size"), r=("ret", "sum")).reindex(dates).fillna(0).to_numpy()
    if d[:, 0].sum() == 0:
        return "-"
    bs = d[rng.integers(0, len(d), (2000, len(d)))].sum(1)
    lo, hi = np.percentile(bs[:, 1] / np.maximum(bs[:, 0], 1), [2.5, 97.5])
    return f"{d[:, 1].sum() / d[:, 0].sum() * 100:.1f} [{lo * 100:.0f},{hi * 100:.0f}] {int(d[:, 0].sum())}장"


def report(names):
    ob = pd.read_pickle(f"{EXP}/oos_{names[0]}.pkl"); rb = _races(ob); rows = []
    for n in names:
        o = pd.read_pickle(f"{EXP}/oos_{n}.pkl"); r = _races(o).reindex(rb.index); rng = np.random.default_rng(7)
        d = (r.loss - rb.loss).to_numpy(); lo, hi = np.percentile(d[rng.integers(0, len(d), (4000, len(d)))].mean(1), [2.5, 97.5])
        A = (rb.year <= 2022).to_numpy(); yd = (r.loss - rb.loss).groupby(rb.year).mean()
        dates = sorted(o.date.unique()); da = [x for x in dates if x < "20230101"]; db = [x for x in dates if x >= "20230101"]
        rows.append({"변형": n, "손실": round(r.loss.mean(), 4), "차이": round(d.mean(), 4), "95%": f"[{lo:+.4f}, {hi:+.4f}]", "A": round(d[A].mean(), 4), "B": round(d[~A].mean(), 4),
                     "나은 해": f"{int((yd < 0).sum())}/{len(yd)}", "회수율": _roi(o, dates, rng), "2016~2022": _roi(o, da, rng), "2023~2026": _roi(o, db, rng)})
    print(pd.DataFrame(rows).to_string(index=False))


def backtest(name):
    """표본외 확률 → backtest/mkt_win.json.gz (backtest_mkt_data.py 와 같은 형식)"""
    o = pd.read_pickle(f"{EXP}/oos_{name}.pkl"); days: dict = {}
    for rid, g in o.groupby("rid"):
        d, n = rid.split("_"); w = g[g["is_win"] == 1]["chul_rd"]
        days.setdefault(d, {})[n] = {"p": {str(int(c)): round(float(v), 6) for c, v in zip(g["chul_rd"], g["p"])},
                                     "odds": {str(int(c)): float(v) for c, v in zip(g["chul_rd"], g["winOdds"])}, "win": int(w.iloc[0]) if len(w) else None}
    with gzip.open("backtest/mkt_win.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(days, fh, separators=(",", ":"))
    print("경주일", len(days), "경주", sum(len(v) for v in days.values()))


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "prep":
        prep()
    elif cmd == "run":
        df = load(); V = variants(df)
        for n in args:
            run(n, df, **V[n])
    elif cmd == "report":
        report(args)
    elif cmd == "backtest":
        backtest(args[0])
