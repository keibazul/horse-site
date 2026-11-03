import numpy as np
import pandas as pd

# =====================================================
# build_race_features_v2.py 와 '같은 계산'을 함수로 옮긴 파일입니다.
# predict_race.py 가 앞으로 열릴 경주의 특징을 학습 때와 똑같은 방식으로 계산하는 데 사용합니다.
# (계산 방식을 바꾸면 학습한 모델과 어긋나므로, 둘을 함께 고쳐야 합니다)
# =====================================================

USE_COLS = ["date", "race_no", "hrNo", "hrName", "ord", "rank", "rcTime", "chulNo", "wgBudam", "age", "sex",
            "jkNo", "trNo", "wgHr", "track"]

SHRINK_K = 30
BASE_WIN = 0.09
BASE_TOP3 = 0.27
RECENT_WINDOW = 100

OUT_COLS = [
    "date", "race_no", "hrNo", "hrName", "ord", "is_win", "is_top3", "ord_pct", "n_finishers",
    "n_prior_races", "n_prior_wins", "n_prior_top3", "win_rate", "top3_rate", "avg_ord", "avg_ord_pct",
    "last1_ord", "last2_ord", "last3_ord", "last3_avg_ord", "last5_avg_ord",
    "last3_wins", "last5_wins", "last3_top3", "last5_top3",
    "last3_avg_ord_pct", "last3_avg_gap", "days_since_last_race",
    "rank", "chulNo", "age", "sex", "wgBudam", "wgBudam_rel",
    "win_rate_rel", "top3_rate_rel", "avg_ord_pct_rel", "last3_avg_ord_pct_rel", "last3_avg_gap_rel",
    "jk_n_prior", "jk_win_rate", "jk_top3_rate", "jk_win_rate_recent", "jk_win_rate_rel",
    "tr_n_prior", "tr_win_rate", "tr_top3_rate", "tr_win_rate_recent", "tr_win_rate_rel",
    "same_jockey_as_prev", "wg_kg", "wg_chg", "wg_dev", "track_state", "track_moisture",
]


def normalize_id(s):
    """마번/기수번호/조교사번호의 앞쪽 0을 떼어 표기 방식이 달라도 같은 ID로 맞춤 (결측은 그대로 둠)"""
    return s.where(s.isna(), s.astype(str).str.strip().str.lstrip("0"))


def _entity_stats(d, id_col, prefix):
    """기수/조교사별로 '이번 경주 이전'까지의 성적. 같은 경주(같은 race_seq)의 결과는 섞이지 않음"""
    agg = (d.groupby([id_col, "race_seq"])
             .agg(n=("is_win", "size"), w=("is_win", "sum"), t3=("is_top3", "sum"))
             .reset_index().sort_values([id_col, "race_seq"]))
    ga = agg.groupby(id_col)
    before = {c: ga[c].cumsum() - agg[c] for c in ("n", "w", "t3")}
    recent = {c: before[c] - before[c].groupby(agg[id_col]).shift(RECENT_WINDOW).fillna(0) for c in ("n", "w")}
    out = agg[[id_col, "race_seq"]].copy()
    out[f"{prefix}_n_prior"] = before["n"]
    out[f"{prefix}_win_rate"] = (before["w"] + SHRINK_K * BASE_WIN) / (before["n"] + SHRINK_K)
    out[f"{prefix}_top3_rate"] = (before["t3"] + SHRINK_K * BASE_TOP3) / (before["n"] + SHRINK_K)
    out[f"{prefix}_win_rate_recent"] = (recent["w"] + SHRINK_K * BASE_WIN) / (recent["n"] + SHRINK_K)
    return out


def compute_features(raw):
    """merged.csv 형태의 표(정상 완주 기록)에서 모든 행의 '경주 이전' 특징을 계산해 돌려줌.

    raw 에 'race_seq' 열이 있으면 그 값을 시간 순서로 사용하고, 없으면 날짜*100+경주번호로 만듭니다.
    (예측할 경주의 출전마는 같은 날짜에 같은 race_seq 를 줘서, 같은 날 다른 경주의 가짜 결과가
     이전 성적에 섞이지 않게 합니다)"""
    df = raw[[c for c in USE_COLS + ["race_seq"] if c in raw.columns]].copy()
    for c in ("hrNo", "jkNo", "trNo"):
        df[c] = normalize_id(df[c])
    df = df.drop_duplicates(["date", "race_no", "hrNo"])
    df = df[df["ord"].between(1, 16)].copy()

    df["race_date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    if "race_seq" not in df.columns:
        df["race_seq"] = df["date"].astype(int) * 100 + df["race_no"].astype(int)
    df["rank"] = df["rank"].str.replace("등급", "", regex=False)

    race_cols = ["date", "race_no"]
    df["n_finishers"] = df.groupby(race_cols)["hrNo"].transform("size")
    df["_win_time"] = df["rcTime"].where(df["ord"] == 1)
    df["winner_time"] = df.groupby(race_cols)["_win_time"].transform("min")
    df["ord_pct"] = df["ord"] / df["n_finishers"]
    df["gap_to_winner"] = (df["rcTime"] - df["winner_time"]).round(2)

    no_winner = df["winner_time"].isna()
    if no_winner.any():
        df = df[~no_winner].copy()

    df["is_win"] = (df["ord"] == 1).astype(int)
    df["is_top3"] = (df["ord"] <= 3).astype(int)
    df = df.reset_index(drop=True)

    # 기수 / 조교사의 '이전' 성적
    df = df.merge(_entity_stats(df, "jkNo", "jk"), on=["jkNo", "race_seq"], how="left")
    df = df.merge(_entity_stats(df, "trNo", "tr"), on=["trNo", "race_seq"], how="left")

    # 말별로 시간 순서대로 정렬하고 '이전 성적' 계산
    df = df.sort_values(["hrNo", "race_seq"]).reset_index(drop=True)
    g = df.groupby("hrNo")

    def last_n_sum(col, n):
        before = g[col].cumsum() - df[col]
        lag = before.groupby(df["hrNo"]).shift(n).fillna(0)
        return before - lag

    n_prior = g.cumcount()
    den = n_prior.replace(0, np.nan)
    df["n_prior_races"] = n_prior
    df["n_prior_wins"] = g["is_win"].cumsum() - df["is_win"]
    df["n_prior_top3"] = g["is_top3"].cumsum() - df["is_top3"]
    df["win_rate"] = df["n_prior_wins"] / den
    df["top3_rate"] = df["n_prior_top3"] / den
    df["avg_ord"] = (g["ord"].cumsum() - df["ord"]) / den
    df["avg_ord_pct"] = (g["ord_pct"].cumsum() - df["ord_pct"]) / den

    for k in (1, 2, 3):
        df[f"last{k}_ord"] = g["ord"].shift(k)

    for n in (3, 5):
        cnt = np.minimum(n_prior, n).replace(0, np.nan)
        df[f"last{n}_avg_ord"] = last_n_sum("ord", n) / cnt
        df[f"last{n}_wins"] = last_n_sum("is_win", n).where(n_prior > 0)
        df[f"last{n}_top3"] = last_n_sum("is_top3", n).where(n_prior > 0)
    cnt3 = np.minimum(n_prior, 3).replace(0, np.nan)
    df["last3_avg_ord_pct"] = last_n_sum("ord_pct", 3) / cnt3
    df["last3_avg_gap"] = last_n_sum("gap_to_winner", 3) / cnt3

    df["days_since_last_race"] = (df["race_date"] - g["race_date"].shift(1)).dt.days
    df["same_jockey_as_prev"] = (df["jkNo"] == g["jkNo"].shift(1)).astype(float).where(n_prior > 0)

    # 마체중 / 주로 상태 ('441(-9)' = 441kg, 직전 경주 대비 -9kg / '470()' = 변화 없음 / '441' = 변화 알 수 없음)
    wg = df["wgHr"].str.extract(r"^\s*(\d+)\s*(?:\(\s*([+-]?\d*)\s*\))?\s*$")
    df["wg_kg"] = pd.to_numeric(wg[0])
    chg = pd.to_numeric(wg[1], errors="coerce")
    blank = wg[1] == ""
    df["wg_chg"] = chg.where(~blank, np.where(n_prior > 0, 0.0, np.nan))

    has_kg = df["wg_kg"].notna().astype(int)
    kg0 = df["wg_kg"].fillna(0)
    sum_before = kg0.groupby(df["hrNo"]).cumsum() - kg0
    cnt_before = has_kg.groupby(df["hrNo"]).cumsum() - has_kg
    df["wg_dev"] = df["wg_kg"] - sum_before / cnt_before.replace(0, np.nan)

    tk = df["track"].str.extract(r"^\s*(\S+?)\s*\((\d+)%\)\s*$")
    df["track_state"] = tk[0]
    df["track_moisture"] = pd.to_numeric(tk[1])

    # 이번 경주 조건과 '같은 경주 말들과 비교한 값'
    df["chulNo"] = pd.to_numeric(df["chulNo"], errors="coerce")
    df["age"] = pd.to_numeric(df["age"], errors="coerce")
    df["wgBudam"] = pd.to_numeric(df["wgBudam"], errors="coerce")
    df["wgBudam_rel"] = df["wgBudam"] - df.groupby(race_cols)["wgBudam"].transform("mean")

    for col in ["win_rate", "top3_rate", "avg_ord_pct", "last3_avg_ord_pct", "last3_avg_gap",
                "jk_win_rate", "tr_win_rate"]:
        df[f"{col}_rel"] = df[col] - df.groupby(race_cols)[col].transform("mean")

    return df[OUT_COLS].sort_values(["date", "race_no", "ord"]).reset_index(drop=True)
