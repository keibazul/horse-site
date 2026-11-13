"""기대값 보정 곡선 (2026-11-13): 모델이 말한 기대값(배당 반영 확률 × 확정 단승 배당) 구간마다 실제 회수율·적중이 어땠나
자료: work/backtest/mkt_win.json.gz (연도별 표본외), 확률 5% 이상인 말, 100원씩, 경주일 단위 부트스트랩
'실제/예측' = 실제 우승 수 ÷ 예측 확률 합 (1이면 그 구간에서 확률이 맞음, 1보다 작으면 모델이 과신)
사용: python pipeline/checks/plan_ev_curve.py
"""
import gzip, json, os
import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
D = json.load(gzip.open(os.path.join(ROOT, "work", "backtest", "mkt_win.json.gz"), "rt", encoding="utf-8"))
dates = sorted(D)
rows = []       # 날짜 번호, p, 배당, 우승
for di, d in enumerate(dates):
    for r in D[d].values():
        for i, p in r["p"].items():
            rows.append((di, p, r["odds"][i], int(i) == r["win"]))
R = np.array(rows, float)
di, p, o, w = R[:, 0].astype(int), R[:, 1], R[:, 2], R[:, 3]
ev = p * o
isA = np.array([d < "20230101" for d in dates])[di]
rng = np.random.default_rng(7)

def line(m):
    n = int(m.sum())
    if n == 0:
        return "      0장"
    day = np.zeros((len(dates), 2)); np.add.at(day[:, 0], di[m], 1); np.add.at(day[:, 1], di[m], (o * w)[m])
    b = day[rng.integers(0, len(dates), (1000, len(dates)))].sum(1)
    lo, hi = np.percentile(b[:, 1] / np.maximum(b[:, 0], 1), [2.5, 97.5])
    return f"{n:6d}장 회수 {(o * w)[m].sum() / n * 100:5.1f}% [{lo * 100:3.0f},{hi * 100:3.0f}] 예측EV {ev[m].mean():.2f} 실제/예측 {w[m].sum() / p[m].sum():.2f}"

B = [(0, .8), (.8, .9), (.9, 1), (1, 1.1), (1.1, 1.2), (1.2, 1.3), (1.3, 1.5), (1.5, 9)]
for name, base in (("확률 5% 이상", p >= 0.05), ("확률 5% 미만", p < 0.05)):
    print(f"\n== {name} ==")
    for a, b_ in B:
        m = base & (ev >= a) & (ev < b_)
        print(f"EV {a:.1f}~{b_ if b_ < 9 else '':<4} 전체 {line(m)}\n            A {line(m & isA)}\n            B {line(m & ~isA)}")
m = (p >= 0.05) & (ev >= 1.2)
print("\n산 마권(EV≥1.2, p≥5%) 켈리 비율 구간별:")
k = np.minimum(0.1, (ev - 1) / (o - 1))
for a, b_ in ((0, .01), (.01, .02), (.02, .04), (.04, .11)):
    mm = m & (k >= a) & (k < b_)
    print(f" k {a:.2f}~{b_:.2f}: {line(mm)}")
