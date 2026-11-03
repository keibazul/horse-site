"""v5 추가 특징: 경주성적정보(API214_1)의 경주 거리·배당·장구 등을 이용한 특징.

모든 '과거 성적' 특징은 그 경주 이전 기록만으로 계산합니다.
'이번 경주 조건' 특징(오늘 거리, 감량, 장구, 날씨, 생후 일수)은 경주 전에 공개되는 정보입니다.

속도지수 (한국마사회 출전마분석정보 정의를 따름)
  기준값 = 같은 거리·같은 주로 상태에서 '그 날짜 이전 3년간' 우승마 평균 기록
  속도지수 = 100 + (기준값 - 기록) / 0.2      (0.2초 = 1점, 클수록 빠름)
  보정 속도지수 = 그날 주로 빠르기(그날 우승마들이 기준값보다 얼마나 빨랐는지, 1000m당 초)를 빼고 계산
"""
import re

import numpy as np
import pandas as pd

PAR_DAYS = 1095          # 기준값 계산 기간 (3년)
PAR_MIN_RACES = 8        # 기준값을 믿을 최소 경주 수 (부족하면 주로 상태 무시하고 거리만으로)

NEW_FEATURES = [
    # 속도지수 (이전 경주)
    "fig_last1", "fig_avg3", "fig_best5", "fig_trend", "figadj_avg3", "figadj_best5",
    "close_fig_avg3", "fig_at_dist",
    # 거리 적성
    "today_dist", "dist_change", "awd", "awd_gap", "ordpct_at_dist", "n_at_dist",
    # 배당 대비 성적 (이전 경주)
    "q_last1", "q_avg3", "odds_rank_last1", "beat_mkt_last3", "beat_mkt_avg",
    # 이번 경주 조건
    "wg_jk", "n_tools", "tool_new", "tool_removed", "age_days", "rating_now", "rating_now_rel",
    # 경주 안 비교
    "fig_avg3_rel", "figadj_best5_rel", "beat_mkt_last3_rel",
]
CAT_FEATURES_V5 = ["weather"]


def _state(track):
    m = re.match(r"\s*(\S+?)\s*\(", str(track))
    return m.group(1) if m else np.nan


def load_race_details(rd):
    """경주성적정보 원본(API214_1 응답을 그대로 저장한 표)을 정리"""
    d = rd.copy()
    d["date"] = d["rcDate"].astype(str)
    d["race_no"] = pd.to_numeric(d["rcNo"]).astype(int)
    d["hrNo"] = d["hrNo"].astype(str).str.strip().str.lstrip("0")
    d["rcDist"] = pd.to_numeric(d["rcDist"], errors="coerce")
    for c in ("winOdds", "plcOdds", "rating", "wgJk", "rcTime", "seG3fAccTime"):
        d[c] = pd.to_numeric(d.get(c), errors="coerce")
    d["hrTool"] = d["hrTool"].fillna("").astype(str)
    d["birthday"] = pd.to_datetime(d["birthday"].astype(str), format="%Y%m%d", errors="coerce")
    keep = ["date", "race_no", "hrNo", "rcDist", "winOdds", "plcOdds", "rating", "wgJk", "hrTool", "weather", "birthday", "track"]
    return d[keep].drop_duplicates(["date", "race_no", "hrNo"])


def _rolling_par(win, value_col):
    """(거리, 상태)별·거리별로 '그 날짜 이전 PAR_DAYS일' 우승마 평균값을 날짜마다 계산"""
    out = {}
    for keys, cols in ((["rcDist", "state"], "ds"), (["rcDist"], "d")):
        g = (win.groupby(keys + ["dt"])[value_col].agg(["sum", "count"]).reset_index().sort_values("dt"))
        res = []
        for k, sub in g.groupby(keys, sort=False):
            s = sub.set_index("dt")[["sum", "count"]].rolling(f"{PAR_DAYS}D", closed="left").sum()
            sub = sub.assign(par_sum=s["sum"].values, par_cnt=s["count"].values)
            res.append(sub)
        out[cols] = pd.concat(res)[keys + ["dt", "par_sum", "par_cnt"]]
    return out


def compute_v5(merged, rd_raw):
    """merged: merged.csv 형태 (date, race_no, hrNo, ord, rcTime, seG3fAccTime 포함)
    rd_raw: 경주성적정보 원본. 반환: (date, race_no, hrNo) 기준 v5 특징 표 (정상 완주 말만)"""
    rd = load_race_details(rd_raw)
    m = merged[["date", "race_no", "hrNo", "ord", "rcTime", "seG3fAccTime"]].copy()
    m["hrNo"] = m["hrNo"].astype(str).str.strip().str.lstrip("0")
    m = m.drop_duplicates(["date", "race_no", "hrNo"])
    df = m[m["ord"].between(1, 16)].merge(rd, on=["date", "race_no", "hrNo"], how="left")
    df["dt"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df["race_seq"] = df["date"].astype(int) * 100 + df["race_no"].astype(int)
    df["state"] = df["track"].map(_state)
    keys = ["date", "race_no"]
    n = df.groupby(keys)["hrNo"].transform("size")
    df["ord_pct"] = df["ord"] / n

    # ---- 기준값(par)과 속도지수: 기준값은 그 날짜 이전 3년 우승마로만 계산 ----
    win = df[(df["ord"] == 1) & (df["rcTime"] > 0) & df["rcDist"].notna()].copy()
    win["g3"] = win["seG3fAccTime"].where(win["seG3fAccTime"] > 0)
    for value_col, name in (("rcTime", "par"), ("g3", "par_g3")):
        w = win.dropna(subset=[value_col])
        pars = _rolling_par(w, value_col)
        ds = pars["ds"].rename(columns={"par_sum": "s1", "par_cnt": "c1"})
        d_ = pars["d"].rename(columns={"par_sum": "s2", "par_cnt": "c2"})
        tmp = df[["rcDist", "state", "dt"]].drop_duplicates()
        tmp = tmp.merge(ds, on=["rcDist", "state", "dt"], how="left").merge(d_, on=["rcDist", "dt"], how="left")
        tmp[name] = np.where(tmp["c1"] >= PAR_MIN_RACES, tmp["s1"] / tmp["c1"],
                             np.where(tmp["c2"] >= PAR_MIN_RACES, tmp["s2"] / tmp["c2"], np.nan))
        df = df.merge(tmp[["rcDist", "state", "dt", name]], on=["rcDist", "state", "dt"], how="left")

    t = df["rcTime"].where(df["rcTime"] > 0)
    df["_fig"] = 100 + (df["par"] - t) / 0.2
    # 그날 주로 빠르기: 그날 각 경주 우승마의 (기록 - 기준값)을 1000m당으로 환산한 중앙값
    w1 = df[(df["ord"] == 1)].assign(v=lambda x: (x["rcTime"] - x["par"]) / x["rcDist"] * 1000)
    variant = w1.groupby("date")["v"].median()
    df["_variant"] = df["date"].map(variant)
    df["_figadj"] = 100 + (df["par"] + df["_variant"] * df["rcDist"] / 1000 - t) / 0.2
    g3 = df["seG3fAccTime"].where(df["seG3fAccTime"] > 0)
    df["_close_fig"] = 100 + (df["par_g3"] - g3) / 0.2

    # ---- 배당 대비 성적: 그 경주 단승 배당으로 본 예상 순위 vs 실제 순위 ----
    inv = (1 / df["winOdds"].where(df["winOdds"] > 0))
    df["_q"] = inv / inv.groupby([df["date"], df["race_no"]]).transform("sum")
    rk = df["_q"].groupby([df["date"], df["race_no"]]).rank(ascending=False, method="average")
    cnt = df["_q"].groupby([df["date"], df["race_no"]]).transform("count")
    df["_odds_rank"] = (rk - 0.5) / cnt                       # 0에 가까울수록 인기마
    df["_beat_mkt"] = df["_odds_rank"] - (df["ord"] - 0.5) / n  # 양수 = 인기보다 잘 뜀

    # ---- 말별 시간순 '이전 경주' 요약 ----
    df = df.sort_values(["hrNo", "race_seq"]).reset_index(drop=True)
    g = df.groupby("hrNo")
    hr = df["hrNo"]

    def prev_stat(col, last=None, how="mean"):
        x = df[col]
        if how == "mean":
            has = x.notna().astype(float); v = x.fillna(0.0)
            sb = v.groupby(hr).cumsum() - v; cb = has.groupby(hr).cumsum() - has
            if last is not None:
                sb = sb - sb.groupby(hr).shift(last).fillna(0); cb = cb - cb.groupby(hr).shift(last).fillna(0)
            return sb / cb.replace(0, np.nan)
        # 최근 last 경주 최댓값 (이번 경주 제외)
        sh = x.groupby(hr).shift(1)
        return sh.groupby(hr).rolling(last, min_periods=1).max().reset_index(level=0, drop=True)

    df["fig_last1"] = g["_fig"].shift(1)
    df["fig_avg3"] = prev_stat("_fig", 3)
    df["fig_best5"] = prev_stat("_fig", 5, "max")
    df["fig_trend"] = df["fig_last1"] - df["fig_avg3"]
    df["figadj_avg3"] = prev_stat("_figadj", 3)
    df["figadj_best5"] = prev_stat("_figadj", 5, "max")
    df["close_fig_avg3"] = prev_stat("_close_fig", 3)
    df["q_last1"] = g["_q"].shift(1)
    df["q_avg3"] = prev_stat("_q", 3)
    df["odds_rank_last1"] = g["_odds_rank"].shift(1)
    df["beat_mkt_last3"] = prev_stat("_beat_mkt", 3)
    df["beat_mkt_avg"] = prev_stat("_beat_mkt")

    # ---- 거리 적성: 오늘 거리와 비슷한(±100m) 이전 경주 ----
    df["today_dist"] = df["rcDist"]
    df["dist_change"] = df["rcDist"] - g["rcDist"].shift(1)
    awd, gap, op, na, fd = (np.full(len(df), np.nan) for _ in range(5))
    dist = df["rcDist"].to_numpy(float); ordp = df["ord_pct"].to_numpy(float)
    won = (df["ord"] == 1).to_numpy(); fig = df["_fig"].to_numpy(float)
    for _, idx in g.indices.items():
        for k in range(1, len(idx)):
            prev = idx[:k]; cur = idx[k]
            pd_ = dist[prev]
            w = pd_[won[prev]]
            if len(w):
                awd[cur] = w.mean(); gap[cur] = dist[cur] - awd[cur]
            near = np.abs(pd_ - dist[cur]) <= 100
            if near.any():
                op[cur] = ordp[prev][near].mean(); na[cur] = near.sum()
                fv = fig[prev][near]; fv = fv[~np.isnan(fv)]
                if len(fv): fd[cur] = fv.mean()
            else:
                na[cur] = 0
    df["awd"], df["awd_gap"], df["ordpct_at_dist"], df["n_at_dist"], df["fig_at_dist"] = awd, gap, op, na, fd
    first = g.cumcount() == 0
    df.loc[first, "n_at_dist"] = 0

    # ---- 이번 경주 조건 ----
    df["wg_jk"] = df["wgJk"]
    tools = df["hrTool"].fillna("")
    df["n_tools"] = tools.map(lambda s: 0 if s in ("", "-", "nan") else
                              len([x for x in s.split(",") if x.strip() and not x.strip().endswith("-")]))   # 해지(-) 장구는 빼고 셈
    df["tool_new"] = tools.str.count(r"\+")
    df["tool_removed"] = tools.map(lambda s: sum(1 for x in s.split(",")
                                                 if len(x.strip()) > 1 and x.strip().endswith("-")))  # '-' 하나만 있으면 '장구 없음' 표시
    df["age_days"] = (df["dt"] - df["birthday"]).dt.days
    df["rating_now"] = df["rating"].where(df["rating"] > 0)          # 레이팅은 경주 전 공시값 (2015년~ 일부만 있음, 0은 없음)

    # ---- 경주 안 비교 ----
    k2 = [df["date"], df["race_no"]]
    for c in ("fig_avg3", "figadj_best5", "beat_mkt_last3", "rating_now"):
        df[f"{c}_rel"] = df[c] - df[c].groupby(k2).transform("mean")

    return df[["date", "race_no", "hrNo"] + NEW_FEATURES + CAT_FEATURES_V5]
