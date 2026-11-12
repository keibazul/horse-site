"""모델·시장 결합 계수 한 곳에서: work/winner_history/blend.json (없으면 예전 값)

결합 점수 = α·log 모델 + β·log 시장 + γ·(log 시장)²   (γ: 시장의 비인기마 편향 — 배당 100배 안팎 말은 배당이 말하는 것보다 덜 이김)
"""
from __future__ import annotations

import json
import math
from pathlib import Path

_F = Path(__file__).resolve().parents[1] / "work" / "winner_history" / "blend.json"
ALPHA, BETA, GAMMA = 0.1689, 0.9219, 0.0
try:
    _c = json.loads(_F.read_text(encoding="utf-8"))
    ALPHA, BETA, GAMMA = float(_c["alpha"]), float(_c["beta"]), float(_c.get("gamma", 0.0))
except (OSError, ValueError, KeyError):
    pass


def score(pm: float, q: float) -> float:
    """pm: 모델 확률, q: 시장 확률(1/배당을 경주 안에서 합 1로) → 결합 점수(경주 안에서 exp 후 정규화)"""
    lq = math.log(max(q, 1e-12))
    return ALPHA * math.log(max(pm, 1e-9)) + BETA * lq + GAMMA * lq * lq


def combine(pm: dict, q: dict) -> dict:
    sc = {k: score(pm[k], q[k]) for k in pm}
    z = max(sc.values())
    e = {k: math.exp(v - z) for k, v in sc.items()}
    t = sum(e.values())
    return {k: v / t for k, v in e.items()}
