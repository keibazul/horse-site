"""v4 추가 특징: 구간 통과순위·구간기록(경주 거리 없이도 계산 가능한 것)과 Elo 레이팅.

모든 값은 '그 경주 이전' 기록만으로 계산합니다 (이번 경주 기록은 쓰지 않음).
merged.csv 의 서울 구간 열을 씁니다:
  sjS1fOrd  출발 후 200m 지점 순위      seS1fAccTime 출발 후 200m 기록
  sj_4cOrd  4코너 순위                  seG3fAccTime 결승 전 600m 구간 기록(끝걸음)
  sjG1fOrd  결승 전 200m 지점 순위
값이 0이면 기록 없음으로 처리합니다.
"""
import numpy as np
import pandas as pd

V4_COLS = ["sjS1fOrd", "sj_4cOrd", "sjG1fOrd", "seS1fAccTime", "seG3fAccTime"]

ELO_K = 384.0         # Elo 갱신 폭 (2021~22년 검증으로 선택: 16~512 중 우승마 손실 최소)
ELO_INIT = 1500.0

NEW_FEATURES = [
    # 주행 스타일 / 끝걸음 (이전 경주 평균)
    "early_pos_last3", "early_pos_avg", "front_rate",          # 출발 200m 순위비율(0=선두), 선두권(2위 이내) 비율
    "late_pos_last3",                                          # 4코너 순위비율
    "close_rank_last3", "close_rank_avg",                      # 종반 600m 기록의 경주 내 순위비율 (0=가장 빠름)
    "close_rel_last3",                                         # 종반 600m 기록 - 그 경주 중앙값 (초, 음수가 빠름)
    "early_rel_last3",                                         # 출발 200m 기록 - 그 경주 중앙값 (초)
    "gain_last3",                                              # (4코너 순위 - 최종 순위)/두수 : 막판에 올라온 정도
    # 경주 안 비교 / 페이스
    "early_pos_rel", "close_rank_rel", "n_front_in_race", "front_and_lone",
    # Elo
    "elo", "elo_rel", "elo_best",
]


def _race_pct(df, col):
    """경주 안에서 col 값의 순위비율 (작을수록 빠름/앞섬). 기록 없으면 NaN"""
    v = df[col].where(df[col] > 0)
    n = v.groupby([df["date"], df["race_no"]]).transform("count")
    r = v.groupby([df["date"], df["race_no"]]).rank(method="average")
    return (r - 0.5) / n


def compute_v4(raw):
    """merged.csv 형태(정상 완주 기록, race_seq 열 선택)에서 v4 특징을 계산해 (date, race_no, hrNo) 기준 표로 돌려줌.
    raw 에는 date, race_no, hrNo, ord 와 V4_COLS 가 있어야 함."""
    df = raw[["date", "race_no", "hrNo", "ord"] + V4_COLS + (["race_seq"] if "race_seq" in raw.columns else [])].copy()
    df["hrNo"] = df["hrNo"].astype(str).str.strip().str.lstrip("0")
    df = df.drop_duplicates(["date", "race_no", "hrNo"])
    df = df[df["ord"].between(1, 16)].copy()
    if "race_seq" not in df.columns:
        df["race_seq"] = df["date"].astype(int) * 100 + df["race_no"].astype(int)
    keys = [df["date"], df["race_no"]]
    n = df.groupby(["date", "race_no"])["hrNo"].transform("size")

    # ---- 이번 경주의 '결과' 값 (다음 경주들의 특징 재료로만 씀) ----
    # 통과 순위는 완주하지 못한 말까지 센 번호라 완주 두수로 나누지 않고, 경주 안에서 다시 순위를 매김
    df["_early_pos"] = _race_pct(df, "sjS1fOrd")
    df["_late_pos"] = _race_pct(df, "sj_4cOrd")
    df["_close_rank"] = _race_pct(df, "seG3fAccTime")
    g3 = df["seG3fAccTime"].where(df["seG3fAccTime"] > 0)
    s1 = df["seS1fAccTime"].where(df["seS1fAccTime"] > 0)
    df["_close_rel"] = g3 - g3.groupby(keys).transform("median")
    df["_early_rel"] = s1 - s1.groupby(keys).transform("median")
    df["_gain"] = df["_late_pos"] - (df["ord"] - 0.5) / n          # 4코너 순위비율 - 최종 순위비율 (양수 = 막판에 올라옴)
    df["_front"] = (df["sjS1fOrd"].between(1, 2)).astype(float).where(df["sjS1fOrd"] > 0)

    # ---- 말별 시간순으로 '이전 경주' 평균 ----
    df = df.sort_values(["hrNo", "race_seq"]).reset_index(drop=True)
    g = df.groupby("hrNo")

    def prev_mean(col, last=None):
        x = df[col]
        has = x.notna().astype(float)
        v = x.fillna(0.0)
        if last is None:
            s = v.groupby(df["hrNo"]).cumsum() - v
            c = has.groupby(df["hrNo"]).cumsum() - has
        else:
            sb = v.groupby(df["hrNo"]).cumsum() - v
            cb = has.groupby(df["hrNo"]).cumsum() - has
            s = sb - sb.groupby(df["hrNo"]).shift(last).fillna(0)
            c = cb - cb.groupby(df["hrNo"]).shift(last).fillna(0)
        return s / c.replace(0, np.nan)

    df["early_pos_last3"] = prev_mean("_early_pos", 3)
    df["early_pos_avg"] = prev_mean("_early_pos")
    df["front_rate"] = prev_mean("_front")
    df["late_pos_last3"] = prev_mean("_late_pos", 3)
    df["close_rank_last3"] = prev_mean("_close_rank", 3)
    df["close_rank_avg"] = prev_mean("_close_rank")
    df["close_rel_last3"] = prev_mean("_close_rel", 3)
    df["early_rel_last3"] = prev_mean("_early_rel", 3)
    df["gain_last3"] = prev_mean("_gain", 3)

    # ---- 이번 경주 출전마끼리 비교 / 페이스 압력 ----
    keys = [df["date"], df["race_no"]]
    df["early_pos_rel"] = df["early_pos_last3"] - df["early_pos_last3"].groupby(keys).transform("mean")
    df["close_rank_rel"] = df["close_rank_last3"] - df["close_rank_last3"].groupby(keys).transform("mean")
    is_front = (df["early_pos_last3"] < 0.25).astype(float)
    df["n_front_in_race"] = is_front.groupby(keys).transform("sum")
    df["front_and_lone"] = ((is_front == 1) & (df["n_front_in_race"] == 1)).astype(float)

    # ---- Elo: 경주를 시간순으로, 같은 경주 안 모든 말 쌍의 승패로 갱신 ----
    elo_before = np.full(len(df), np.nan)
    elo_best = np.full(len(df), np.nan)
    rating, best = {}, {}
    order = df.groupby("race_seq", sort=True).indices        # 값: df 안의 위치 (정렬하지 않은 원래 표 기준)
    hr = df["hrNo"].to_numpy(); od = df["ord"].to_numpy(float)
    for seq in sorted(order):
        idx = order[seq]
        if len(idx) < 2:
            continue
        r = np.array([rating.get(h, ELO_INIT) for h in hr[idx]])
        elo_before[idx] = r
        elo_best[idx] = [best.get(h, ELO_INIT) for h in hr[idx]]
        e = 1.0 / (1.0 + 10 ** ((r[None, :] - r[:, None]) / 400.0))       # e[i,j] = i가 j를 이길 기대값
        s = (od[idx][:, None] < od[idx][None, :]).astype(float) + 0.5 * (od[idx][:, None] == od[idx][None, :])
        np.fill_diagonal(e, 0); np.fill_diagonal(s, 0)
        new = r + ELO_K * (s - e).sum(1) / (len(idx) - 1)
        for h, v in zip(hr[idx], new):
            rating[h] = v
            best[h] = max(best.get(h, ELO_INIT), v)
    df["elo"] = elo_before
    df["elo_best"] = elo_best
    df["elo_rel"] = df["elo"] - df["elo"].groupby(keys).transform("mean")

    return df[["date", "race_no", "hrNo"] + NEW_FEATURES]
