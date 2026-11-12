"""지난 경주일 '이렇게 샀다면' 계산 → site/data/strategy.json

경주마다 1회 100원씩 샀다고 보고 확정 배당으로 돌려받은 금액을 셈한다.
- 배당은 마감 후 확정 배당(경주성적정보 winOdds·plcOdds). 실제로 받는 돈도 이 값이므로 환급 계산은 정확하다.
- 단, 고를 때 배당을 쓰는 전략(인기마·결합·기대값)은 마감 배당을 미리 안다고 가정하므로 실제보다 유리하다.
- 연승: 출전 8두 이상 3착 안, 5~7두 2착 안.
- 회수율의 95% 구간은 경주일 단위로 다시 뽑기(부트스트랩)로 구한다.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import blend_coef  # noqa: E402  (결합 계수: work/winner_history/blend.json)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data"
UNIT = 100

STRATS = [
    # id, 이름, 승식, 고를 때 배당을 쓰는지, 설명
    ("m1_win", "모델 1순위 단승", "win", False, "모델 확률이 가장 높은 말 (경주 전에 알 수 있음)"),
    ("fav_win", "인기마 단승", "win", True, "단승 배당이 가장 낮은 말"),
    ("c1_win", "결합 1순위 단승", "win", True, "모델과 배당을 섞은 확률이 가장 높은 말"),
    ("ev_win", "기대값 1 이상 단승", "win", True, "결합 확률 × 단승 배당 ≥ 1 인 말 모두"),
    ("m1_plc", "모델 1순위 연승", "plc", False, "모델 1순위 말의 연승"),
    ("fav_plc", "인기마 연승", "plc", True, "단승 배당이 가장 낮은 말의 연승"),
    ("c1_plc", "결합 1순위 연승", "plc", True, "결합 확률 1순위 말의 연승"),
]


def race_bets(r: dict) -> dict[str, list[tuple[float, float]]] | None:
    """경주 하나에서 전략별 (건 돈, 돌려받은 돈) 목록"""
    res, p, od, pl = r.get("result"), r.get("p") or {}, r.get("odds") or {}, r.get("plc") or {}
    if not res or not od:
        return None
    live = [k for k in p if k in od and od[k] > 0]
    if len(live) < 2:
        return None
    n = len(live)
    win = str(res[0])
    placed = {str(x) for x in res[: (3 if n >= 8 else 2)]}
    s = sum(1 / od[k] for k in live)
    comb = {k: blend_coef.score(p[k], (1 / od[k]) / s) for k in live}
    z = max(comb.values())
    tot = sum(math.exp(v - z) for v in comb.values())
    cp = {k: math.exp(comb[k] - z) / tot for k in live}
    m1 = max(live, key=lambda k: p[k])
    fav = min(live, key=lambda k: od[k])
    c1 = max(live, key=lambda k: cp[k])

    def w(k):
        return (UNIT, UNIT * od[k] if k == win else 0.0)

    def pl_(k):
        if k not in pl:
            return None
        return (UNIT, UNIT * pl[k] if k in placed else 0.0)

    out = {"m1_win": [w(m1)], "fav_win": [w(fav)], "c1_win": [w(c1)],
           "ev_win": [w(k) for k in live if cp[k] * od[k] >= 1]}
    for sid, k in (("m1_plc", m1), ("fav_plc", fav), ("c1_plc", c1)):
        b = pl_(k)
        out[sid] = [b] if b and n >= 5 else []
    return out


def build() -> dict | None:
    days = []
    for f in sorted((DATA / "pred").glob("*.json")):
        j = json.loads(f.read_text(encoding="utf-8"))
        per = {sid: [0.0, 0.0, 0, 0] for sid, *_ in STRATS}   # 건 돈, 받은 돈, 건수, 적중
        nr = 0
        for r in j.get("races", {}).values():
            b = race_bets(r)
            if b is None:
                continue
            nr += 1
            for sid, lst in b.items():
                for st, rt in lst:
                    per[sid][0] += st; per[sid][1] += rt; per[sid][2] += 1; per[sid][3] += rt > 0
        if nr:
            days.append((j["date"], nr, per))
    if not days:
        return None
    rng = random.Random(0)
    out = []
    for sid, name, pool, uses_odds, desc in STRATS:
        stake = sum(d[2][sid][0] for d in days); ret = sum(d[2][sid][1] for d in days)
        bets = sum(d[2][sid][2] for d in days); hits = sum(d[2][sid][3] for d in days)
        cum, series = 0.0, []
        for date, _, per in days:
            cum += per[sid][1] - per[sid][0]
            series.append(round(cum))
        boots = []
        for _ in range(2000):
            smp = [days[rng.randrange(len(days))][2][sid] for _ in days]
            st = sum(x[0] for x in smp)
            if st:
                boots.append(sum(x[1] for x in smp) / st)
        boots.sort()
        ci = [boots[int(0.025 * len(boots))], boots[int(0.975 * len(boots)) - 1]] if boots else None
        out.append({"id": sid, "name": name, "pool": pool, "usesOdds": uses_odds, "desc": desc,
                    "bets": bets, "hits": hits, "stake": round(stake), "ret": round(ret),
                    "roi": round(ret / stake, 4) if stake else None,
                    "ci": [round(c, 4) for c in ci] if ci else None, "series": series})
    return {"from": days[0][0], "to": days[-1][0], "days": len(days), "races": sum(d[1] for d in days),
            "unit": UNIT, "dates": [d[0] for d in days], "strategies": out}


def write() -> None:
    s = build()
    if s:
        (DATA / "strategy.json").write_text(json.dumps(s, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"전략 계산: {s['days']}일 {s['races']}경주")


if __name__ == "__main__":
    write()
    s = json.loads((DATA / "strategy.json").read_text(encoding="utf-8"))
    for x in s["strategies"]:
        print(f"{x['name']:<14} {x['bets']:>5}건 적중 {x['hits']:>4}  회수율 {x['roi'] * 100:6.1f}%  95% {x['ci'][0] * 100:5.1f}~{x['ci'][1] * 100:5.1f}%  손익 {x['ret'] - x['stake']:>+9,}원")
