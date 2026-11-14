"""사람들의 베팅 심리에서 오는 편향이 서울 단승·연승 배당에 있는지 (2026-11-14)
모델 없이 확정 배당과 결과만으로 봄: 어떤 상황의 말을 100원씩 샀을 때 회수율이 평소와 다른가.
  상황: 그날 경주 순서(마지막 경주 효과), 요일, 앞 경주 인기마 연패, 인기 기수·조교사, 감량 기수, 번호, 등급·두수·거리,
        직전 우승마, 첫 출전, 긴 휴식, 암말×계절, 주로 상태, 부담중량 방식, 대상경주
기간: P1 2001~2010, P2 2011~2020.2.22, P3 2021.11~2026 (코로나 무관중 2020-02-23~2021-10-31 제외). 구간은 경주일 단위 부트스트랩 95%.
2부: 베팅 계획이 고른 말(표본외 배당 반영 확률 5% 이상·기대값 1.2 이상, work/backtest/mkt_win.json.gz)의 회수율을 같은 상황별로.
사용: python pipeline/checks/crowd_bias.py
"""
import gzip
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
rng = np.random.default_rng(11)
use = ["rcDate", "rcNo", "chulNo", "ord", "winOdds", "plcOdds", "rcDay", "rank", "wgJk", "budam", "sex", "age", "ageCond", "track", "weather",
       "rcDist", "rcName", "jkNo", "trNo", "hrNo"]
d = pd.read_csv(os.path.join(ROOT, "work", "race_details_all.csv.gz"), dtype=str, usecols=use)
for c in ("rcNo", "chulNo", "ord", "winOdds", "plcOdds", "wgJk", "age", "rcDist"):
    d[c] = pd.to_numeric(d[c], errors="coerce")
d = d.sort_values(["rcDate", "rcNo", "chulNo"]).reset_index(drop=True)

# 말의 과거 (취소 포함 전 기록으로 계산 → 그 뒤에 유효 경주만 남김)
ran = d[d["winOdds"] > 0].copy()
g = ran.groupby("hrNo")
ran["n_prior"] = g.cumcount()
ran["prev_ord"] = g["ord"].shift(1)
ran["prev_date"] = g["rcDate"].shift(1)
ran["layoff"] = (pd.to_datetime(ran["rcDate"]) - pd.to_datetime(ran["prev_date"])).dt.days
d = ran
rid = d["rcDate"] + "_" + d["rcNo"].astype(int).astype(str)
d["rid"] = rid
g = d.groupby("rid")
d["n"] = g["chulNo"].transform("size")
ok = (g["winOdds"].transform("max") < 9999) & (g["ord"].transform(lambda s: (s == 1).sum()) == 1) & (d["n"] >= 5)
d = d[ok & ~d["rcDate"].between("20200223", "20211031") & (d["rcDate"] >= "20010101")].copy()
g = d.groupby("rid")
d["win"] = (d["ord"] == 1).astype(float)
d["plc"] = ((d["ord"] <= np.where(d["n"] >= 8, 3, 2)) & (d["plcOdds"] > 0)).astype(float)
d["orank"] = g["winOdds"].rank(method="min")
d["fav"] = d["orank"] == 1
d["period"] = np.where(d["rcDate"] < "20110101", 0, np.where(d["rcDate"] < "20200301", 1, 2))
day = pd.factorize(d["rcDate"])[0]
d["day"] = day
nday = day.max() + 1

# 상황
last = d.groupby("rcDate")["rcNo"].transform("max")
d["pos"] = np.where(d["rcNo"] == last, "마지막", np.where(d["rcNo"] == last - 1, "끝에서 둘째", np.where(d["rcNo"] == 1, "첫 경주", np.where(d["rcNo"] <= 3, "2~3경주", "가운데"))))
fr = d[d["fav"]].groupby("rid").agg(date=("rcDate", "first"), no=("rcNo", "first"), fw=("win", "max")).sort_values(["date", "no"])
streak = []
cur, cd = 0, None
for dt, fw in zip(fr["date"], fr["fw"]):
    if dt != cd:
        cur, cd = -1, dt          # 첫 경주: 앞 경주 없음
    streak.append(cur)
    cur = 0 if fw else (1 if cur < 0 else cur + 1)
fr["streak"] = streak
d["streak"] = d["rid"].map(fr["streak"])
d["stk"] = np.select([d["streak"] < 0, d["streak"] == 0, d["streak"] == 1, d["streak"] == 2], ["(첫 경주)", "앞 경주 인기마 우승", "인기마 1연패 뒤", "인기마 2연패 뒤"], "인기마 3연패 이상 뒤")
# 그 전까지 그날 인기마가 몇 번 이겼나 (인기마가 잘 들어오는 날 / 이변이 많은 날)
d["year"] = d["rcDate"].str[:4].astype(int)
for who, col in (("jk", "jkNo"), ("tr", "trNo")):
    w = d[d["win"] == 1].groupby(["year", col]).size().rename("w").reset_index()
    w["rk"] = w.groupby("year")["w"].rank(ascending=False, method="min")
    w["year"] += 1                                        # 지난해 다승 순위
    d = d.merge(w[["year", col, "rk"]].rename(columns={"rk": who + "_rk"}), on=["year", col], how="left")
    d[who + "_fame"] = np.select([d[who + "_rk"] <= 3, d[who + "_rk"] <= 10], ["지난해 다승 1~3위", "4~10위"], "그 밖")
d["gate"] = pd.cut(d["chulNo"], [0, 2, 4, 6, 8, 10, 20], labels=["1~2번", "3~4번", "5~6번", "7~8번", "9~10번", "11번~"]).astype(str)
d["cls"] = d["rank"].str.replace("등급", "", regex=False).str.replace(r"^혼.*", "혼합", regex=True).where(lambda s: s.isin(["국6", "국5", "국4", "국3", "국2", "국1", "혼합"]), "그 밖")
d["field"] = pd.cut(d["n"], [0, 8, 11, 20], labels=["8두 이하", "9~11두", "12두 이상"]).astype(str)
d["dist"] = pd.cut(d["rcDist"], [0, 1200, 1400, 1800, 9999], labels=["~1200m", "1300~1400m", "1600~1800m", "1900m~"]).astype(str)
d["hist"] = np.select([d["n_prior"] == 0, d["prev_ord"] == 1, d["layoff"] > 90], ["첫 출전", "직전 우승", "90일 넘게 쉼"], "그 밖")
d["exper"] = pd.cut(d["n_prior"], [-1, 0, 3, 9, 999], labels=["첫 출전", "1~3전", "4~9전", "10전 이상"]).astype(str)
mon = d["rcDate"].str[4:6].astype(int)
d["mare"] = np.where(d["sex"] == "암", np.where(mon.between(3, 6), "암말 3~6월", "암말 그 밖"), "수·거세")
moist = pd.to_numeric(d["track"].str.extract(r"\((\d+)%\)")[0], errors="coerce")
d["wet"] = np.where(moist >= 15, "주로 함수율 15%↑", np.where(moist <= 5, "5%↓", "6~14%"))
d["hcap"] = np.where(d["budam"] == "핸디캡", "핸디캡", np.where(d["budam"] == "마령", "마령", "별정"))
d["appr"] = np.where(d["wgJk"] < 0, "감량 기수", "일반 기수")
stakes_day = d.groupby("rcDate")["rcName"].transform(lambda s: (~s.fillna("일반").isin(["일반", "", "-"])).any())
d["stk_day"] = np.where(~d["rcName"].fillna("일반").isin(["일반", "", "-"]), "대상·특별경주", np.where(stakes_day, "대상경주 있는 날의 일반경주", "보통 날"))
d["age2"] = np.where(d["ageCond"] == "2세", "2세 경주", "그 밖")
d["dow"] = d["rcDay"]


def roi(m, col="win", odds="winOdds"):
    m = np.asarray(m)
    n = int(m.sum())
    if n < 30:
        return None
    ret = (d[odds].to_numpy() * d[col].to_numpy())[m]
    dy = d["day"].to_numpy()[m]
    s = np.bincount(dy, minlength=nday).astype(float)
    r = np.bincount(dy, weights=ret, minlength=nday)
    idx = rng.integers(0, nday, (400, nday))
    b = r[idx].sum(1) / np.maximum(s[idx].sum(1), 1)
    per = []
    pp = d["period"].to_numpy()[m]
    for k in range(3):
        per.append(ret[pp == k].mean() * 100 if (pp == k).sum() >= 30 else float("nan"))
    return n, ret.mean() * 100, np.percentile(b, 2.5) * 100, np.percentile(b, 97.5) * 100, per


def show(label, m, **kw):
    x = roi(m, **kw)
    if x is None:
        return f"{label}: (표본 적음)"
    n, r, lo, hi, per = x
    return f"{label}: {n:6d}장 {r:5.1f}% [{lo:3.0f},{hi:3.0f}] 기간별 {per[0]:4.0f}/{per[1]:4.0f}/{per[2]:4.0f}"


fav = d["fav"].to_numpy()
o = d["winOdds"].to_numpy()
mid, lng = (o >= 5) & (o < 20), o >= 20
print(f"유효 {d['rid'].nunique():,}경주 {len(d):,}마리 ({d['rcDate'].min()}~{d['rcDate'].max()})")
print("기준 |", show("인기 1위 단승", fav), "|", show("5~20배", mid), "|", show("20배↑", lng), "|", show("인기 1위 연승", fav, col="plc", odds="plcOdds"))
for name, col in (("그날 경주 순서", "pos"), ("요일", "dow"), ("앞 경주 인기마", "stk"), ("기수", "jk_fame"), ("조교사", "tr_fame"), ("기수 감량", "appr"), ("번호", "gate"),
                  ("등급", "cls"), ("두수", "field"), ("거리", "dist"), ("말의 이력", "hist"), ("암말·계절", "mare"), ("주로", "wet"), ("부담중량", "hcap"),
                  ("경주 종류", "stk_day"), ("연령 조건", "age2")):
    print(f"\n== {name} ==")
    for v in sorted(d[col].dropna().unique()):
        m = (d[col] == v).to_numpy()
        allm = show("전체", m)
        print(f"[{v}] {show('인기1위', m & fav)} | {show('5~20배', m & mid)} | {show('20배↑', m & lng)} | {allm}")

# ---------- 2부: 베팅 계획이 고른 말 ----------
D = json.load(gzip.open(os.path.join(ROOT, "work", "backtest", "mkt_win.json.gz"), "rt", encoding="utf-8"))
rows = []
for dt, R in D.items():
    for n, r in R.items():
        for i, p in r["p"].items():
            if p >= 0.05 and p * r["odds"][i] >= 1.2:
                rows.append((dt, int(n), int(i), p, r["odds"][i], int(i) == r["win"]))
B = pd.DataFrame(rows, columns=["rcDate", "rcNo", "chulNo", "p", "o", "w"])
cols = ["pos", "dow", "stk", "jk_fame", "tr_fame", "appr", "gate", "cls", "field", "dist", "hist", "exper", "mare", "wet", "hcap", "stk_day", "age2", "fav"]
B = B.merge(d[["rcDate", "rcNo", "chulNo", "day"] + cols], on=["rcDate", "rcNo", "chulNo"], how="left")
print(f"\n\n===== 2부: 베팅 계획이 고른 말 {len(B)}장 (속성 연결 {B['day'].notna().sum()}) — A 2016~2022 / B 2023~2026 =====")
B = B[B["day"].notna()].copy()
B["A"] = B["rcDate"] < "20230101"
B["orank1"] = np.where(B["fav"], "인기 1위", "그 밖")


def roi2(m):
    x = B[m]
    if len(x) < 40:
        return None
    ret = (x["o"] * x["w"]).to_numpy()
    dy = pd.factorize(x["rcDate"])[0]
    s = np.bincount(dy).astype(float); r = np.bincount(dy, weights=ret)
    idx = rng.integers(0, len(s), (600, len(s)))
    b = r[idx].sum(1) / s[idx].sum(1)
    a, bb = x[x["A"]], x[~x["A"]]
    f = lambda z: (z["o"] * z["w"]).mean() * 100 if len(z) >= 20 else float("nan")
    return len(x), ret.mean() * 100, np.percentile(b, 2.5) * 100, np.percentile(b, 97.5) * 100, f(a), len(a), f(bb), len(bb), x["w"].sum() / x["p"].sum()


for name, col in (("그날 경주 순서", "pos"), ("요일", "dow"), ("앞 경주 인기마", "stk"), ("기수", "jk_fame"), ("기수 감량", "appr"), ("번호", "gate"), ("등급", "cls"),
                  ("두수", "field"), ("거리", "dist"), ("말의 이력", "hist"), ("출전 경험", "exper"), ("암말·계절", "mare"), ("주로", "wet"), ("부담중량", "hcap"),
                  ("경주 종류", "stk_day"), ("연령 조건", "age2"), ("인기", "orank1")):
    print(f"\n== {name} ==")
    for v in sorted(B[col].dropna().unique()):
        x = roi2((B[col] == v).to_numpy())
        print(f"[{v}] " + ("(표본 적음)" if x is None else f"{x[0]:5d}장 {x[1]:6.1f}% [{x[2]:3.0f},{x[3]:3.0f}]  A {x[4]:6.1f}% ({x[5]})  B {x[6]:6.1f}% ({x[7]})  실제/예측 {x[8]:.2f}"))
