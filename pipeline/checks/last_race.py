"""마지막 경주 효과 (2026-11-14): 그날 마지막 경주에서는 사람들이 배당 높은 말을 더 많이 삼 → 그 말들의 배당이 실제 확률보다 낮게 형성
1) 2001~2026 서울 단승: 배당 구간별 (실제 우승 수 ÷ 배당이 말하는 우승 수), 마지막 경주 vs 그 밖 — 기간 3개
2) 2001~2015 자료만으로 보정 계수(마지막 경주 ÷ 그 밖)를 구해 2016~2026 베팅 계획에 적용 (계획 검증 기간과 겹치지 않음)
   방식: (가) 지금 그대로 (나) 마지막 경주 건너뛰기 (다) 마지막 경주는 확률 × 보정 계수 뒤 같은 기준
3) 배당 반영 모델이 시장보다 나은 정도(우승마 로그 손실 차)를 거리·경주 순서별로
사용: python pipeline/checks/last_race.py
"""
import gzip, json, os
import numpy as np, pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
rng = np.random.default_rng(5)
d = pd.read_csv(os.path.join(ROOT, "work", "race_details_all.csv.gz"), dtype=str, usecols=["rcDate", "rcNo", "chulNo", "ord", "winOdds", "rcDist", "rank"])
for c in ("rcNo", "chulNo", "ord", "winOdds", "rcDist"):
    d[c] = pd.to_numeric(d[c], errors="coerce")
d = d[d["winOdds"] > 0].copy()
d["rid"] = d["rcDate"] + "_" + d["rcNo"].astype(int).astype(str)
g = d.groupby("rid")
ok = (g["winOdds"].transform("max") < 9999) & (g["ord"].transform(lambda s: (s == 1).sum()) == 1) & (g["chulNo"].transform("size") >= 5)
d = d[ok & ~d["rcDate"].between("20200223", "20211031") & (d["rcDate"] >= "20010101")].copy()
g = d.groupby("rid")
d["q"] = (1 / d["winOdds"]) / g["winOdds"].transform(lambda s: (1 / s).sum())
d["win"] = (d["ord"] == 1).astype(float)
last = d.groupby("rcDate")["rcNo"].transform("max")
d["last"] = d["rcNo"] == last
d["left"] = (last - d["rcNo"]).clip(upper=4)
BK = [1, 3, 5, 10, 20, 50, 1e9]
d["bk"] = pd.cut(d["winOdds"], BK, right=False, labels=False)
names = ["1~3배", "3~5배", "5~10배", "10~20배", "20~50배", "50배~"]
d["per"] = np.where(d["rcDate"] < "20110101", 0, np.where(d["rcDate"] < "20200301", 1, 2))

print("1) 실제 우승 ÷ 배당이 말하는 우승 (1보다 작으면 사람들이 너무 많이 산 말) — 전체 [기간 P1/P2/P3], 회수율")
for b in range(6):
    out = []
    for lab, m in (("그 밖", ~d["last"]), ("마지막", d["last"])):
        x = d[m & (d["bk"] == b)]
        r = x["win"].sum() / x["q"].sum()
        pr = [x[x["per"] == k]["win"].sum() / max(x[x["per"] == k]["q"].sum(), 1e-9) for k in range(3)]
        out.append(f"{lab} {r:.3f} [{pr[0]:.2f}/{pr[1]:.2f}/{pr[2]:.2f}] 회수 {(x['winOdds'] * x['win']).mean() * 100:5.1f}% ({len(x)})")
    print(f" {names[b]:>7}: " + " | ".join(out))
print("   남은 경주 수별 (20배 이상 말의 실제÷배당):", " ".join(f"{k if k < 4 else '4+'}경주 남음 {x['win'].sum() / x['q'].sum():.3f}" for k, x in d[d["winOdds"] >= 20].groupby("left")))

# 2001~2015 로만 계수
tr = d[d["rcDate"] < "20160101"]
fac = {}
for b in range(6):
    a = tr[tr["last"] & (tr["bk"] == b)]; o = tr[~tr["last"] & (tr["bk"] == b)]
    fac[b] = (a["win"].sum() / a["q"].sum()) / (o["win"].sum() / o["q"].sum())
print("\n2) 2001~2015 로 구한 마지막 경주 보정 계수:", {names[b]: round(v, 3) for b, v in fac.items()})

D = json.load(gzip.open(os.path.join(ROOT, "work", "backtest", "mkt_win.json.gz"), "rt", encoding="utf-8"))
lastno = d.groupby("rcDate")["rcNo"].max().to_dict()
dist = d.drop_duplicates("rid").set_index("rid")["rcDist"].to_dict()
dates = sorted(D)
isA = np.array([x < "20230101" for x in dates])


def plan(mode):
    out = np.zeros((len(dates), 2))
    for di, dt in enumerate(dates):
        for n, r in D[dt].items():
            is_last = int(n) == lastno.get(dt, max(int(k) for k in D[dt]))
            if is_last and mode == "skip":
                continue
            for i, p in r["p"].items():
                o = r["odds"][i]
                if is_last and mode == "factor":
                    p = p * fac[int(np.searchsorted(BK, o, side="right") - 1)]
                if p >= 0.05 and p * o >= 1.2:
                    out[di, 0] += 1; out[di, 1] += o * (int(i) == r["win"])
    return out


def fmt(x):
    def one(m):
        z = x if m is None else x[m]
        idx = rng.integers(0, len(z), (1000, len(z)))
        b = z[idx].sum(1); lo, hi = np.percentile(b[:, 1] / np.maximum(b[:, 0], 1), [2.5, 97.5])
        return f"{int(z[:, 0].sum()):5d}장 {z[:, 1].sum() / z[:, 0].sum() * 100:5.1f}% [{lo * 100:3.0f},{hi * 100:3.0f}]"
    return f"전체 {one(None)} | 2016~2022 {one(isA)} | 2023~2026 {one(~isA)}"


for lab, mode in (("(가) 지금 그대로", "base"), ("(나) 마지막 경주 건너뛰기", "skip"), ("(다) 마지막 경주 확률 보정", "factor")):
    print(f" {lab}: {fmt(plan(mode))}")
x = plan("base") - plan("skip")
print(f"   마지막 경주에서 산 마권만: {fmt(x)}")
yrs = sorted({dt[:4] for dt in dates})
b0, b1 = plan("base"), plan("skip")
ya = np.array([dt[:4] for dt in dates])
print("   연도별 (지금 → 건너뛰기):", " ".join(f"{y} {b0[ya == y, 1].sum() / max(b0[ya == y, 0].sum(), 1) * 100:.0f}→{b1[ya == y, 1].sum() / max(b1[ya == y, 0].sum(), 1) * 100:.0f}" for y in yrs))

print("\n3) 모델 − 시장 우승마 로그 손실 차 (음수면 모델이 나음), 경주 단위 부트스트랩")
rows = []
for dt in dates:
    for n, r in D[dt].items():
        w = str(r["win"])
        if w not in r["p"]:
            continue
        s = sum(1 / v for v in r["odds"].values())
        rows.append((dt, int(n), -np.log(max(r["p"][w], 1e-9)) + np.log((1 / r["odds"][w]) / s), dist.get(f"{dt}_{int(n)}"), int(n) == lastno.get(dt)))
L = pd.DataFrame(rows, columns=["dt", "n", "dl", "dist", "last"])
def ll(m, lab):
    x = L[m]["dl"].to_numpy(); b = x[rng.integers(0, len(x), (1000, len(x)))].mean(1)
    print(f"  {lab}: {len(x):5d}경주 {x.mean():+.4f} [{np.percentile(b, 2.5):+.4f}, {np.percentile(b, 97.5):+.4f}]")
ll(np.ones(len(L), bool), "전체")
ll(L["last"], "마지막 경주"); ll(~L["last"], "그 밖")
for lab, lo, hi in (("~1200m", 0, 1200), ("1300~1400m", 1300, 1400), ("1600~1800m", 1600, 1800), ("1900m~", 1900, 9999)):
    ll(L["dist"].between(lo, hi), lab)
