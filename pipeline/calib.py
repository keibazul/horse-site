"""모델 상태 점검 → site/data/calib.json  (수익 검증 페이지 '모델 상태')

표본외 경주(그날보다 앞서 학습을 끝낸 모델의 예측)만 씀.
1) 확률 구간별: 예측 평균 vs 실제 우승 비율 (모델 / 배당과 결합) — 전체 기간과 최근 8주
2) 주별: 경주 수, 1순위 우승 비율(모델·결합·인기마), 우승마 평균 로그 손실(모델·결합·시장)
사용: python pipeline/calib.py
"""
from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data"
ALPHA, BETA = 0.1689, 0.9219
BINS = [0, .05, .10, .15, .20, .30, .40, 1.01]


def races():
    for f in sorted((DATA / "pred").glob("*.json")):
        j = json.loads(f.read_text(encoding="utf-8"))
        d = f.stem
        if not (j.get("trained_through") and j["trained_through"] < d):
            continue
        for r in j.get("races", {}).values():
            res, p = r.get("result"), r.get("p") or {}
            if not res or not p:
                continue
            out = set(map(str, r.get("out", [])))
            live = {k: v for k, v in p.items() if k not in out}
            s = sum(live.values())
            if not s:
                continue
            pm = {k: v / s for k, v in live.items()}
            od = r.get("odds") or {}
            pc = q = None
            if all(k in od and od[k] > 1 for k in live):
                si = sum(1 / od[k] for k in live)
                q = {k: (1 / od[k]) / si for k in live}
                v = {k: math.exp(ALPHA * math.log(max(pm[k], 1e-9)) + BETA * math.log(q[k])) for k in live}
                t = sum(v.values())
                pc = {k: x / t for k, x in v.items()}
            yield d, str(res[0]), pm, pc, q


def week(d: str) -> str:
    t = dt.date(int(d[:4]), int(d[4:6]), int(d[6:]))
    return (t - dt.timedelta(days=t.weekday())).strftime("%Y%m%d")


def reliability(rows, which):
    b = [[0, 0.0, 0] for _ in BINS[:-1]]
    for _, w, pm, pc, _ in rows:
        P = pm if which == "m" else pc
        if not P:
            continue
        for k, v in P.items():
            i = next(i for i in range(len(BINS) - 1) if BINS[i] <= v < BINS[i + 1])
            b[i][0] += 1; b[i][1] += v; b[i][2] += (k == w)
    return [{"lo": BINS[i], "hi": min(BINS[i + 1], 1), "n": n, "pred": round(s / n, 4) if n else None, "act": round(h / n, 4) if n else None}
            for i, (n, s, h) in enumerate(b)]


def main() -> int:
    rows = list(races())
    if not rows:
        return 0
    last = max(r[0] for r in rows)
    cut = (dt.date(int(last[:4]), int(last[4:6]), int(last[6:])) - dt.timedelta(weeks=8)).strftime("%Y%m%d")
    recent = [r for r in rows if r[0] > cut]
    weeks: dict[str, dict] = {}
    for d, w, pm, pc, q in rows:
        x = weeks.setdefault(week(d), {"races": 0, "m": 0, "c": 0, "k": 0, "lm": 0.0, "lc": 0.0, "lk": 0.0, "nc": 0})
        x["races"] += 1
        x["m"] += max(pm, key=pm.get) == w
        x["lm"] += -math.log(max(pm.get(w, 1e-9), 1e-9))
        if pc:
            x["nc"] += 1
            x["c"] += max(pc, key=pc.get) == w
            x["k"] += max(q, key=q.get) == w
            x["lc"] += -math.log(max(pc[w], 1e-9))
            x["lk"] += -math.log(max(q[w], 1e-9))
    wk = []
    for k in sorted(weeks):
        x = weeks[k]
        n, nc = x["races"], max(x["nc"], 1)
        wk.append({"week": k, "races": n, "model": round(x["m"] / n, 4), "comb": round(x["c"] / nc, 4), "fav": round(x["k"] / nc, 4),
                   "lossM": round(x["lm"] / n, 4), "lossC": round(x["lc"] / nc, 4), "lossK": round(x["lk"] / nc, 4)})
    out = {"updated": last, "races": len(rows), "recentFrom": cut, "recentRaces": len(recent),
           "all": {"m": reliability(rows, "m"), "c": reliability(rows, "c")},
           "recent": {"m": reliability(recent, "m"), "c": reliability(recent, "c")}, "weeks": wk}
    (DATA / "calib.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"모델 상태: 표본외 {len(rows)}경주, 최근 8주 {len(recent)}경주")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
