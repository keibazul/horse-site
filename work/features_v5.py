"""v5 모델 특징 계산 (학습 train_win_model_v5.py 와 예측 predict_race.py 가 함께 씀)

  v2 특징 (race_feature_lib.py)      : 말·기수·조교사 이전 성적, 마체중, 주로
  v4 특징 (race_feature_lib_v4.py)   : 구간 통과순위·끝걸음, Elo 레이팅
  v5 특징 (race_feature_lib_v5.py)   : 경주 거리, 속도지수, 과거 배당 대비 성적, 감량, 장구, 레이팅, 나이(일), 날씨

필요한 파일: merged.csv (과거 경주 기록), race_details_all.csv.gz 와/또는 race_details/rd_날짜.csv (경주성적정보)
계산 방식을 바꾸면 학습한 모델과 어긋나므로 반드시 모델을 다시 학습해야 합니다.
"""
import glob
import os
import re

import numpy as np
import pandas as pd

import race_feature_lib as lib
import race_feature_lib_v4 as v4
import race_feature_lib_v5 as v5

HIST_COLS = list(dict.fromkeys(lib.USE_COLS + ["jkName"] + v4.V4_COLS + ["seG3fAccTime"]))
RD_COLS = ["rcDate", "rcNo", "chulNo", "hrNo", "ord", "rcDist", "winOdds", "plcOdds", "rating", "wgJk", "hrTool",
           "weather", "birthday", "track", "rcTime", "seG3fAccTime"]
CAT = ["sex", "rank", "track_state", "weather"]                       # 범주형 특징 (모델 입력 앞쪽)
V2_NUM = ["n_finishers", "n_prior_races", "n_prior_wins", "n_prior_top3", "win_rate", "top3_rate", "avg_ord", "avg_ord_pct",
          "last1_ord", "last2_ord", "last3_ord", "last3_avg_ord", "last5_avg_ord", "last3_wins", "last5_wins", "last3_top3",
          "last5_top3", "last3_avg_ord_pct", "last3_avg_gap", "days_since_last_race", "chulNo", "age", "wgBudam", "wgBudam_rel",
          "win_rate_rel", "top3_rate_rel", "avg_ord_pct_rel", "last3_avg_ord_pct_rel", "last3_avg_gap_rel", "jk_n_prior",
          "jk_win_rate", "jk_top3_rate", "jk_win_rate_recent", "jk_win_rate_rel", "same_jockey_as_prev", "tr_n_prior",
          "tr_win_rate", "tr_top3_rate", "tr_win_rate_recent", "tr_win_rate_rel", "wg_kg", "wg_chg", "wg_dev", "track_moisture"]
NUM = V2_NUM + v4.NEW_FEATURES + v5.NEW_FEATURES                       # 숫자 특징
KEYS = ["date", "race_no", "hrNo"]


# =====================================================
# 불러오기
# =====================================================
def load_history(path="merged.csv"):
    raw = pd.read_csv(path, usecols=HIST_COLS, dtype={"date": str, "hrNo": str, "chulNo": str, "jkNo": str, "trNo": str})
    raw["race_seq"] = raw["date"].astype(int) * 100 + raw["race_no"].astype(int)
    return raw


def load_details(gz="race_details_all.csv.gz", folder="race_details"):
    """경주성적정보: 합쳐 둔 파일(gz) + 그 뒤에 새로 받은 race_details/rd_날짜.csv 를 모두 읽음"""
    parts, last = [], ""
    if gz and os.path.exists(gz):
        d = pd.read_csv(gz, dtype=str, usecols=lambda c: c in RD_COLS)
        parts.append(d); last = d["rcDate"].max()
    files = sorted(glob.glob(os.path.join(folder, "rd_*.csv"))) if folder else []
    for f in files:
        m = re.search(r"rd_(\d{8})\.csv$", f)
        if m and m.group(1) > last:
            parts.append(pd.read_csv(f, dtype=str, usecols=lambda c: c in RD_COLS))
    if not parts:
        raise FileNotFoundError(f"경주성적정보가 없습니다: {gz} 또는 {folder}/rd_*.csv (fetch_race_details.py 로 받으세요)")
    d = pd.concat(parts, ignore_index=True)
    d["hrNo"] = d["hrNo"].astype(str).str.strip().str.lstrip("0")
    return d.drop_duplicates(["rcDate", "rcNo", "hrNo"], keep="last").reset_index(drop=True)


# =====================================================
# 특징 계산
# =====================================================
def all_features(history, rd_raw, v2_raw=None):
    """history(merged.csv 형태) 전체 행의 특징. v2_raw 를 주면 v2 계산에는 그 표를 씀 (예측 때 같은 날 경주 순서 처리용)"""
    f2 = lib.compute_features(v2_raw if v2_raw is not None else history)
    f2["hrNo"] = f2["hrNo"].astype(str)
    f4 = v4.compute_v4(history)
    f5 = v5.compute_v5(history, rd_raw)
    df = f2.merge(f4, on=KEYS, how="left").merge(f5, on=KEYS, how="left")
    for c in CAT:
        df[c] = df[c].astype(object).where(df[c].notna(), None)
    return df


def _today_tools(rd_hist, hr_nos):
    """오늘 장구를 모를 때: 직전 경주에서 달고 있던 장구(해지 '-' 는 빼고 '+' 표시는 지움)를 그대로 쓴다고 봄"""
    h = rd_hist[rd_hist["hrNo"].isin(hr_nos)].sort_values(["rcDate", "rcNo"]).drop_duplicates("hrNo", keep="last")
    def keep(s):
        s = "" if pd.isna(s) else str(s)
        items = [x.strip().replace("+", "") for x in s.split(",") if x.strip() and x.strip() != "-" and not x.strip().endswith("-")]
        return ",".join(items)
    return dict(zip(h["hrNo"], h["hrTool"].map(keep)))


def _birthdays(rd_hist, entries, date):
    """생일: 과거 경주성적에서. 첫 출전마는 '태어난 해 = 경주 연도 - 나이' 의 평균 생일(4월 초)로 추정"""
    b = rd_hist.dropna(subset=["birthday"]).drop_duplicates("hrNo", keep="last").set_index("hrNo")["birthday"]
    out = entries["hrNo"].map(b)
    year = int(date[:4]) - pd.to_numeric(entries["age"], errors="coerce")
    guess = year.map(lambda y: f"{int(y)}0405" if pd.notna(y) else np.nan)
    return out.fillna(guess), out.isna()


def entrant_features(history, rd_raw, entries, date):
    """date 이전 기록만으로 출전마(entries)의 특징을 계산.
    entries 열: rcNo, chulNo, hrNo, hrName, jkNo, jkName, trNo, sex, age, wgBudam, rank, rcDist, rating, wgJk,
                wgHr, track, [hrTool, weather]
    출전마를 '결과가 아직 없는 가짜 행'으로 기록 끝에 붙여 학습 때와 같은 계산을 통과시킴."""
    hist = history[history["date"] < date]
    rdh = rd_raw[rd_raw["rcDate"] < date]
    e = entries.copy()
    e["date"] = date
    e["race_no"] = e["rcNo"].astype(int)
    e["ord"] = e.groupby("rcNo")["chulNo"].transform(lambda s: pd.to_numeric(s).rank(method="first")).astype(int).clip(upper=16)
    e["rcTime"] = 60.0 + e["ord"]                      # 가짜 기록 (자기 자신의 특징에는 쓰이지 않음)
    for c in v4.V4_COLS:
        e[c] = 0.0
    e["jkName"] = e.get("jkName")
    # v2: 같은 날 다른 경주의 가짜 결과가 기수·조교사 성적에 섞이지 않도록 오늘 경주는 모두 같은 순서값
    e2 = e.assign(race_seq=int(date) * 100 + 99)
    e4 = e.assign(race_seq=int(date) * 100 + e["race_no"])
    v2_raw = pd.concat([hist[lib.USE_COLS + ["race_seq"]], e2[lib.USE_COLS + ["race_seq"]]], ignore_index=True)
    h_all = pd.concat([hist[HIST_COLS + ["race_seq"]], e4[HIST_COLS + ["race_seq"]]], ignore_index=True)

    # 경주성적정보 쪽 가짜 행: 경주 전에 알 수 있는 값만
    hr = lib.normalize_id(e["hrNo"].astype(str))
    tools_known = e["hrTool"] if "hrTool" in e.columns else pd.Series(np.nan, index=e.index)
    guess_tools = hr.map(_today_tools(rdh, set(hr)))
    bday, bday_guessed = _birthdays(rdh, e.assign(hrNo=hr), date)
    rd_today = pd.DataFrame({
        "rcDate": date, "rcNo": e["race_no"].astype(str), "chulNo": e["chulNo"].astype(str), "hrNo": hr,
        "ord": e["ord"].astype(str), "rcDist": e["rcDist"], "winOdds": np.nan, "plcOdds": np.nan,
        "rating": e["rating"] if "rating" in e.columns else np.nan, "wgJk": e["wgJk"] if "wgJk" in e.columns else np.nan,
        "hrTool": tools_known.where(tools_known.notna(), guess_tools).fillna(""),
        "weather": e["weather"] if "weather" in e.columns else np.nan, "birthday": bday, "track": e.get("track"),
        "rcTime": e["rcTime"].astype(str), "seG3fAccTime": "0"})
    rd_all = pd.concat([rdh[RD_COLS], rd_today[RD_COLS]], ignore_index=True)

    feat = all_features(h_all, rd_all, v2_raw)
    feat = feat[feat["date"] == date].copy()
    info = {"birthday_guessed": int(bday_guessed.sum()), "tools_guessed": int(tools_known.isna().sum()),
            "rd_last": rdh["rcDate"].max(), "hist_last": hist["date"].max()}
    return feat, info
