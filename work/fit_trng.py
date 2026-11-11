"""조교 횟수 보정 계수를 최신 기록으로 맞춤 → winner_history/trng.json (매달 재학습 때 fit_day_bias.py 가 이어서 실행)

출전표정보(API78)의 조교 횟수(출전 신청 전 2~3주)가 같은 경주 말들의 평균보다 많은 말은 배당이 말해 주는 것보다 조금 더 이긴다.
모형 (경주별 조건부 로짓, 시장 배당 기준):  점수 = a·log 시장확률 + T·rel,   rel = 조교 횟수 − 그 경주 출전표 평균 (−6~+6 으로 자름)
학습: 2019년 ~ 마지막 경주일 (코로나 무관중 2020-02-23~2021-10-31 제외).
검증(2026-11-11): 2019~2022 로 맞춘 계수(0.0096)로 2023~2026 3,946경주 시장 대비 로그 손실 −0.0011 [−0.0018, −0.0005],
                  연도별로 따로 맞춘 계수는 8개 연도 모두 양수(0.004~0.049). 베팅 계획 회수율은 눈에 띄는 변화 없음(±1%p 안).
자료: extra/api78.csv.gz (2019~), 그 뒤 날짜는 ../site/data/extra/날짜.json 의 trngRel.
pipeline/run_all.py 가 T 를 읽어 모델 확률에 exp(T·rel) 을 곱함.
"""
import glob
import json
import os
import time

import numpy as np
import pandas as pd
from scipy.optimize import minimize

CLIP = 6.0


def load_rel() -> pd.DataFrame:
    """(rcDate, rcNo, chulNo, rel) — 보관 기록 + 사이트 참고 정보 파일"""
    a = pd.read_csv(os.path.join("extra", "api78.csv.gz"), dtype=str)
    a["rcNo"] = pd.to_numeric(a["raceNo"].str.extract(r"(\d+)")[0]); a["chulNo"] = pd.to_numeric(a["gtno"])
    a["trng"] = pd.to_numeric(a["trngTcnt"], errors="coerce")
    a = a.rename(columns={"date": "rcDate"}).dropna(subset=["rcNo", "chulNo"])
    a["rel"] = a["trng"] - a.groupby(["rcDate", "rcNo"])["trng"].transform("mean")
    parts, last = [a[["rcDate", "rcNo", "chulNo", "rel"]]], a["rcDate"].max()
    rows = []
    for f in sorted(glob.glob(os.path.join("..", "site", "data", "extra", "*.json"))):
        d = os.path.basename(f)[:8]
        if d <= last:
            continue
        try:
            races = json.load(open(f, encoding="utf-8")).get("races", {})
        except ValueError:
            continue
        for rn, hs in races.items():
            for ch, h in hs.items():
                if (h or {}).get("trngRel") is not None:
                    rows.append((d, int(rn), int(ch), float(h["trngRel"])))
    if rows:
        parts.append(pd.DataFrame(rows, columns=["rcDate", "rcNo", "chulNo", "rel"]))
    return pd.concat(parts, ignore_index=True).dropna(subset=["rel"])


def fit(df: pd.DataFrame) -> tuple[np.ndarray, int]:
    c, u = pd.factorize(df["rid"]); X = df[["lq", "relc"]].to_numpy(float); y = df["win"].to_numpy(); R = len(u)

    def nll(w):
        s = X @ w; m = np.full(R, -1e18); np.maximum.at(m, c, s); e = np.exp(s - m[c]); Z = np.zeros(R); np.add.at(Z, c, e)
        return -((s - m[c] - np.log(Z[c])) * y).sum() / R
    return minimize(nll, np.array([1.0, 0.0]), method="L-BFGS-B").x, R


def main() -> None:
    t0 = time.time()
    cols = ["rcDate", "rcNo", "chulNo", "ord", "winOdds"]
    rd = pd.concat([pd.read_csv("race_details_all.csv.gz", dtype=str, usecols=cols)] +
                   [pd.read_csv(f, dtype=str, usecols=lambda c: c in cols) for f in sorted(glob.glob(os.path.join("race_details", "rd_*.csv")))],
                   ignore_index=True).drop_duplicates(["rcDate", "rcNo", "chulNo"], keep="last")
    for c in ("rcNo", "chulNo", "ord", "winOdds"):
        rd[c] = pd.to_numeric(rd[c], errors="coerce")
    d = rd[(rd["ord"].between(1, 16) | rd["ord"].between(91, 92)) & (rd["winOdds"] > 0) & (rd["rcDate"] >= "20190101")]
    d = d.merge(load_rel(), on=["rcDate", "rcNo", "chulNo"], how="inner")
    d = d[~d["rcDate"].between("20200223", "20211031")].copy()
    d["rid"] = d["rcDate"] + "_" + d["rcNo"].astype(int).astype(str)
    d = d[d.groupby("rid")["chulNo"].transform("size") >= 5].copy()
    d["q"] = 1 / d["winOdds"]; d["q"] /= d.groupby("rid")["q"].transform("sum")
    d["win"] = (d["ord"] == 1).astype(float)
    d = d[d.groupby("rid")["win"].transform("sum") == 1].copy()
    d["lq"] = np.log(d["q"]); d["relc"] = d["rel"].clip(-CLIP, CLIP)
    w, R = fit(d)
    last = d["rcDate"].max()
    cut = str(int(last[:4]) - 2) + last[4:]
    w2, R2 = fit(d[d["rcDate"] >= cut])
    by = {y: round(float(fit(g)[0][1]), 4) for y, g in d.groupby(d["rcDate"].str[:4]) if g["rid"].nunique() >= 300}
    out = {"T": round(float(w[1]), 4), "clip": CLIP, "races": int(R), "through": last, "T_recent2y": round(float(w2[1]), 4), "races_recent2y": int(R2), "by_year": by}
    json.dump(out, open(os.path.join("winner_history", "trng.json"), "w"), ensure_ascii=False, indent=1)
    print(f"조교 횟수 보정: T {out['T']} (최근 2년 {out['T_recent2y']}), 연도별 {by}, {R:,}경주 ~{last} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
