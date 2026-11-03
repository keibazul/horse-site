"""승식별 적중 확률 계산 (한국마사회법 시행규칙 제4조 기준)

  단승   1착
  연승   출전 8두 이상: 3착 이내 / 5~7두: 2착 이내  (4두 이하는 발매 안 함)
  복승   1·2착, 순서 무관          쌍승   1·2착, 순서대로
  복연승 3착 이내 두 마리, 순서 무관 (5두 이상)
  삼복승 1~3착, 순서 무관          삼쌍승 1~3착, 순서대로   (4두 이상)

계산 방법: 한 경주 출전마들의 '강도'(우승 확률)로 1착부터 차례로 뽑는 Plackett-Luce(하빌) 모형.
  P(i가 1착) = p_i
  P(i 1착, j 2착) = p_i * q_j / (1 - q_i)          (q = 2착을 뽑을 때 쓰는 강도)
  P(i 1착, j 2착, k 3착) = 위 값 * r_k / (1 - r_i - r_j)
q, r 은 p 를 LAMBDA2, LAMBDA3 제곱한 뒤 다시 합 1로 맞춘 값입니다 (1이면 순수 하빌 모형).
하빌 모형은 인기마가 2·3착에도 너무 자주 들어온다고 보는 경향이 있어서, 1보다 작은 값을 쓰면 이를 줄일 수 있습니다.
"""
from itertools import combinations, permutations

import numpy as np
import pandas as pd

BET_NAMES = ["단승", "연승", "복승", "쌍승", "복연승", "삼복승", "삼쌍승"]
MIN_RUNNERS = {"단승": 2, "복승": 3, "쌍승": 3, "삼복승": 4, "삼쌍승": 4, "연승": 5, "복연승": 5}


def _norm(x):
    x = np.clip(np.asarray(x, float), 1e-12, None)
    return x / x.sum()


def order_tables(p, lam2=1.0, lam3=1.0):
    """1·2·3착 순서별 확률표를 돌려줌.
    T1[i]       : i 가 1착
    T2[i, j]    : i 1착, j 2착
    T3[i, j, k] : i 1착, j 2착, k 3착"""
    p = _norm(p)
    n = len(p)
    q, r = _norm(p ** lam2), _norm(p ** lam3)
    eye = np.eye(n, dtype=bool)
    # 2착: i 를 뺀 나머지 중에서 q 비율로
    T2 = p[:, None] * q[None, :] / np.clip(1 - q[:, None], 1e-12, None)
    T2[eye] = 0.0
    if n < 3:
        return p, T2, np.zeros((n, n, n))
    # 3착: i, j 를 뺀 나머지 중에서 r 비율로
    rest = np.clip(1 - r[:, None] - r[None, :], 1e-12, None)
    T3 = T2[:, :, None] * r[None, None, :] / rest[:, :, None]
    idx = np.arange(n)
    T3[idx, :, idx] = 0.0   # k == i
    T3[:, idx, idx] = 0.0   # k == j
    T3[idx, idx, :] = 0.0   # i == j
    return p, T2, T3


def bet_tables(p, lam2=1.0, lam3=1.0):
    """승식별 확률표 (말 순서는 p 의 순서). 발매하지 않는 승식은 None"""
    n = len(p)
    T1, T2, T3 = order_tables(p, lam2, lam3)
    top2 = T2.sum(1) + T2.sum(0)                  # 2착 이내
    top3 = top2 + T3.sum((0, 1))                  # 3착 이내
    out = {"단승": T1, "쌍승": T2, "복승": T2 + T2.T, "삼쌍승": T3,
           "top2": top2, "top3": top3}
    # 두 마리가 모두 3착 이내: (1,2착) (1,3착) (2,3착) 자리에 들어가는 모든 경우
    M12, M13, M23 = T3.sum(2), T3.sum(1), T3.sum(0)
    out["복연승"] = M12 + M12.T + M13 + M13.T + M23 + M23.T
    # 세 마리가 1~3착 (순서 무관): 6가지 순서의 합
    out["삼복승"] = sum(np.transpose(T3, ax) for ax in permutations(range(3)))
    out["연승"] = top3 if n >= 8 else top2
    for b, m in MIN_RUNNERS.items():
        if n < m:
            out[b] = None
    return out


def bet_rows(p, labels, lam2=1.0, lam3=1.0, top=None):
    """승식별로 (조합, 확률) 표를 만들어 돌려줌. labels 는 출전번호 등 말 이름표 (p 와 같은 순서).
    top 을 주면 승식마다 확률이 높은 순서로 그만큼만 남김"""
    tabs = bet_tables(p, lam2, lam3)
    labels = [str(x) for x in labels]
    n = len(labels)
    rows = []
    for b in BET_NAMES:
        t = tabs[b]
        if t is None:
            continue
        if b in ("단승", "연승"):
            items = [((i,), t[i]) for i in range(n)]
        elif b == "쌍승":
            items = [((i, j), t[i, j]) for i in range(n) for j in range(n) if i != j]
        elif b in ("복승", "복연승"):
            items = [((i, j), t[i, j]) for i, j in combinations(range(n), 2)]
        elif b == "삼복승":
            items = [((i, j, k), t[i, j, k]) for i, j, k in combinations(range(n), 3)]
        else:  # 삼쌍승
            items = [((i, j, k), t[i, j, k]) for i in range(n) for j in range(n) for k in range(n)
                     if len({i, j, k}) == 3]
        items.sort(key=lambda x: -x[1])
        if top:
            items = items[:top]
        sep = "→" if b in ("쌍승", "삼쌍승") else "-"
        for rk, (combo, pr) in enumerate(items, 1):
            rows.append({"승식": b, "순위": rk, "조합": sep.join(labels[c] for c in combo), "확률": float(pr),
                         "조합수": {"단승": n, "연승": n, "복승": n * (n - 1) // 2, "쌍승": n * (n - 1),
                                  "복연승": n * (n - 1) // 2, "삼복승": n * (n - 1) * (n - 2) // 6,
                                  "삼쌍승": n * (n - 1) * (n - 2)}[b]})
    return pd.DataFrame(rows)
