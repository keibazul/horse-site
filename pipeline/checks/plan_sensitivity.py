"""베팅 계획(단승 p≥5%·기대값≥1.2) 추가 검증 (2026-11-13)
자료: work/backtest/mkt_win.json.gz (연도별 표본외 배당 반영 확률, 확정 단승 배당, 1착) — 100원씩, 경주일 단위 부트스트랩

1) 살 때 배당 ≠ 확정 배당 민감도
   살 때 배당 = 확정 배당 × e^ε. 살 때 확률은 p × (살 때 시장 비중 / 확정 시장 비중)^0.85 로 근사 (모델이 배당을 입력으로 쓰므로).
   고르기는 살 때 값으로, 환급은 확정 배당으로.
   (가) 무작위 흔들림 ε ~ N(0, σ)   (나) 정보 있는 막판 돈: 우승마는 살 때 배당이 e^δ 배 높았음 (막판에 내려감) + 흔들림
2) 배당 상한 / 3) 1위 확률이 낮은 경주 건너뛰기: 2016~2022(A)에서 95% 하한이 가장 높은 값을 고르고 2023~2026(B)에서 확인
사용: python pipeline/checks/plan_sensitivity.py
"""
import gzip
import json
import os

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
D = json.load(gzip.open(os.path.join(ROOT, "work", "backtest", "mkt_win.json.gz"), "rt", encoding="utf-8"))
BETA = 0.85
rng = np.random.default_rng(7)

races = []          # (날짜 번호, p, 배당, 우승 여부)
dates = sorted(D)
for di, d in enumerate(dates):
    for n, r in D[d].items():
        ids = list(r["p"])
        races.append((di, np.array([r["p"][i] for i in ids]), np.array([r["odds"][i] for i in ids], float), np.array([int(i) == r["win"] for i in ids])))
isA = np.array([d < "20230101" for d in dates])


def run(eps_fn=None, min_p=0.05, min_ev=1.2, cap=None, floor=None, min_top=0.0):
    """→ 날짜별 [산 장수, 환급(장 단위)]"""
    out = np.zeros((len(dates), 2))
    for di, p, o, w in races:
        if eps_fn is None:
            pb, ob = p, o
        else:
            ob = np.maximum(1.05, o * np.exp(eps_fn(w)))
            qf, qb = (1 / o) / (1 / o).sum(), (1 / ob) / (1 / ob).sum()
            pb = p * (qb / qf) ** BETA
            pb = pb / pb.sum()
        if pb.max() < min_top:
            continue
        sel = (pb >= min_p) & (pb * ob >= min_ev)
        if cap:
            sel &= ob <= cap
        if floor:
            sel &= ob >= floor
        out[di, 0] += sel.sum()
        out[di, 1] += (o[sel] * w[sel]).sum()
    return out


def stat(x, mask=None, ci=True):
    x = x if mask is None else x[mask]
    roi = x[:, 1].sum() / max(x[:, 0].sum(), 1)
    if not ci:
        return int(x[:, 0].sum()), roi, None
    idx = rng.integers(0, len(x), (1000, len(x)))
    b = x[idx].sum(1)
    lo, hi = np.percentile(b[:, 1] / np.maximum(b[:, 0], 1), [2.5, 97.5])
    return int(x[:, 0].sum()), roi, (lo, hi)


def fmt(x):
    def one(m):
        n, r, c = stat(x, m)
        return f"{n:5d}장 {r * 100:5.1f}% [{c[0] * 100:3.0f},{c[1] * 100:3.0f}]"
    return f"전체 {one(None)} | A {one(isA)} | B {one(~isA)}"


print("기준 (확정 배당으로 고름):", fmt(run()))
print("\n1) 살 때 배당 흔들림 (20번 반복 평균, 회수율 %) — 열: 기대값 기준 1.2 / 1.3 / 1.4 / 1.5")
def rep(fn, ev):
    xs = [run(fn, min_ev=ev) for _ in range(20)]
    return np.mean([stat(x, ci=False)[1] for x in xs]), np.mean([stat(x, ~isA, ci=False)[1] for x in xs]), np.mean([x[:, 0].sum() for x in xs])
for sg in (0.05, 0.1, 0.2, 0.3):
    row = [rep(lambda w: rng.normal(0, sg, len(w)), ev) for ev in (1.2, 1.3, 1.4, 1.5)]
    print(f" (가) σ={sg:.2f} (변화 중앙값 {np.expm1(0.6745 * sg) * 100:4.1f}%):", " / ".join(f"{a * 100:5.1f} (B {b * 100:5.1f}, {n:5.0f}장)" for a, b, n in row))
for dl, sg in ((0.05, 0.1), (0.1, 0.1), (0.1, 0.2), (0.2, 0.2)):
    row = [rep(lambda w: rng.normal(0, sg, len(w)) + dl * w, ev) for ev in (1.2, 1.3, 1.4, 1.5)]
    print(f" (나) 우승마 막판 하락 {np.expm1(dl) * 100:4.1f}%, σ={sg:.2f}:", " / ".join(f"{a * 100:5.1f} (B {b * 100:5.1f}, {n:5.0f}장)" for a, b, n in row))

print("\n2) 배당 상한 (그 배당 이하만 삼)")
for cap in (None, 100, 50, 30, 20, 15, 10):
    print(f"  상한 {cap or '없음':>4}:", fmt(run(cap=cap)))
print("   배당 구간별:")
for lo, hi in ((1, 5), (5, 10), (10, 20), (20, 50), (50, 1e9)):
    print(f"  {lo:>3}~{hi if hi < 1e8 else '':<4}:", fmt(run(floor=lo, cap=hi - 1e-9)))
print("\n3) 그 경주 1위 확률이 이 값 미만이면 건너뛰기")
for t in (0, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5):
    print(f"  {t:.2f}:", fmt(run(min_top=t)))
print("   반대로 1위 확률이 이 값 이상이면 건너뛰기 (혼전만 삼)")
for t in (0.3, 0.4, 0.5):
    x = np.zeros((len(dates), 2))
    for di, p, o, w in races:
        if p.max() >= t:
            continue
        sel = (p >= 0.05) & (p * o >= 1.2)
        x[di, 0] += sel.sum(); x[di, 1] += (o[sel] * w[sel]).sum()
    print(f"  {t:.2f}:", fmt(x))
