"""당일 게이트 경향 보정 계수를 최신 기록으로 다시 맞춤 → winner_history/day_bias.json (매달 재학습 때 실행)

모형 (경주별 조건부 로짓, 시장 배당 기준):
  점수 = a·log 시장확률 + b·평소 초반 위치 + c·(평소 위치 없음) + d·게이트(0.5−위치) + K·IB·(0.5−게이트 위치)
  IB = (MU − 그날 앞 경주들의 3착 안 말 게이트 위치 평균) / SD   (앞 경주 2개 이상)
학습: 2008년 ~ 마지막 경주일 (코로나 무관중 2020-02-23~2021-10-31 제외). 최근 2년은 따로 맞춰 계수가 안정적인지도 기록.
pipeline/live_bias.py 가 이 파일의 K·MU·SD 를 씀 (없으면 처음 연구값 0.157·0.483·0.0963).
사용: python fit_day_bias.py
"""
import json
import time

import numpy as np
import pandas as pd
from scipy.optimize import minimize

import features_v5 as fv

t0 = time.time()
rd = fv.load_details("race_details_all.csv.gz", "race_details")
cols = ["rcDate", "rcNo", "chulNo", "hrNo", "ord", "winOdds"]
d = rd[cols].copy()
extra = pd.read_csv("race_details_all.csv.gz", usecols=["rcDate", "rcNo", "hrNo", "sjS1fOrd"], dtype=str)
for f in __import__("glob").glob("race_details/rd_*.csv"):
    try:
        extra = pd.concat([extra, pd.read_csv(f, usecols=["rcDate", "rcNo", "hrNo", "sjS1fOrd"], dtype=str)])
    except ValueError:
        pass
extra["hrNo"] = extra["hrNo"].astype(str).str.strip().str.lstrip("0")
d = d.merge(extra.drop_duplicates(["rcDate", "rcNo", "hrNo"]), on=["rcDate", "rcNo", "hrNo"], how="left")
for c in ["ord", "winOdds", "chulNo", "sjS1fOrd"]:
    d[c] = pd.to_numeric(d[c], errors="coerce")
d = d[(d["rcDate"] >= "20080101") & ~d["rcDate"].between("20200223", "20211031") & d["ord"].between(1, 16) & (d["winOdds"] > 0)].copy()
d["rid"] = d["rcDate"] + "_" + d["rcNo"].astype(str)
d["n"] = d.groupby("rid")["chulNo"].transform("size")
d = d[d["n"] >= 5]
d["gp"] = (d.groupby("rid")["chulNo"].rank(method="first") - 1) / (d["n"] - 1)
d["ep"] = np.where(d["sjS1fOrd"] > 0, (d["sjS1fOrd"] - 1) / (d["n"] - 1), np.nan)
d["q"] = 1 / d["winOdds"]; d["q"] /= d.groupby("rid")["q"].transform("sum")
d["win"] = (d["ord"] == 1).astype(float)
d = d.sort_values(["hrNo", "rcDate", "rcNo"])
d["style"] = d.groupby("hrNo")["ep"].transform(lambda s: s.shift(1).rolling(5, min_periods=1).mean())
top = d[d["ord"] <= 3].groupby(["rcDate", "rcNo", "rid"])["gp"].mean().rename("top_gp").reset_index()
top["rn"] = pd.to_numeric(top["rcNo"]); top = top.sort_values(["rcDate", "rn"])
g = top.groupby("rcDate")["top_gp"]
top["nprev"] = g.cumcount(); top["prev"] = g.transform(lambda s: s.shift(1).expanding().mean())
MU, SD = float(top["top_gp"].mean()), float(top["top_gp"].std())
d = d.merge(top[["rid", "nprev", "prev"]], on="rid", how="left")
d["IB"] = np.where(d["nprev"] >= 2, (MU - d["prev"]) / SD, 0.0)
d["lq"] = np.log(d["q"]); d["S"] = (0.5 - d["style"]).fillna(0); d["Sna"] = d["style"].isna().astype(float)
d["G"] = 0.5 - d["gp"]; d["IBG"] = d["IB"] * d["G"]
d = d[d.groupby("rid")["win"].transform("sum") == 1]
X_COLS = ["lq", "S", "Sna", "G", "IBG"]


def fit(df):
    c, u = pd.factorize(df["rid"]); X = df[X_COLS].to_numpy(float); y = df["win"].to_numpy(); R = len(u)
    def nll(w):
        s = X @ w; m = np.zeros(R); np.maximum.at(m, c, s); e = np.exp(s - m[c]); Z = np.zeros(R); np.add.at(Z, c, e)
        return -((s - m[c] - np.log(Z[c])) * y).sum() / R
    w0 = np.zeros(len(X_COLS)); w0[0] = 1
    return minimize(nll, w0, method="L-BFGS-B").x, R


w, R = fit(d)
last = d["rcDate"].max()
cut = str(int(last[:4]) - 2) + last[4:]
w2, R2 = fit(d[d["rcDate"] >= cut])
out = {"K": round(float(w[-1]), 4), "MU": round(MU, 4), "SD": round(SD, 4), "races": int(R), "through": last,
       "K_recent2y": round(float(w2[-1]), 4), "races_recent2y": int(R2), "coef": dict(zip(X_COLS, np.round(w, 4).tolist()))}
json.dump(out, open("winner_history/day_bias.json", "w"), ensure_ascii=False, indent=1)
print(f"당일 게이트 보정: K {out['K']} (최근 2년 {out['K_recent2y']}), MU {out['MU']}, SD {out['SD']}, {R:,}경주 ~{last} ({time.time() - t0:.0f}s)")

# 조교 횟수 보정 계수도 같이 (winner_history/trng.json). 실패해도 위 결과는 그대로 둠
try:
    import fit_trng
    fit_trng.main()
except Exception as e:  # noqa: BLE001
    print(f"조교 횟수 보정 계수 맞춤 실패: {type(e).__name__}: {e}")
