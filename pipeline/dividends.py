"""끝난 경주의 확정 배당 (적중 조합만) → site/data/div/날짜.json  (마권 기록장 정산용)

확정배당율 통합정보 API160_1/integratedInfo_1 을 승식마다 받아, 실제 1~3착으로 적중 조합을 골라 배당만 남긴다.
  단승 1착 / 연승 3착 안(7두 이하 2착 안) 말마다 / 복승 1·2착(순서 무관) / 쌍승 1→2착
  복연승 3착 안 두 마리 3조합 / 삼복승 1~3착(순서 무관) / 삼쌍승 1→2→3착
배당은 원금 포함 배수 (100원 × 배당 = 환급금).

사용: python pipeline/dividends.py --date 20261101   또는 --missing (예측 파일에 결과가 있는데 div 파일이 없는 날, 한 번에 4일)
"""
from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kra_api  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data"
POOLS = ["단승식", "연승식", "복승식", "쌍승식", "복연승식", "삼복승식", "삼쌍승식"]


def key(pool: str, nums: list[int]) -> str:
    if pool in ("쌍승식", "삼쌍승식"):
        return ">".join(map(str, nums))
    return "-".join(map(str, sorted(nums)))


def winning(pool: str, res: list[int], n: int) -> list[list[int]]:
    top = res[:3]
    if pool == "단승식":
        return [[res[0]]]
    if pool == "연승식":
        return [[x] for x in res[: (3 if n >= 8 else 2)]]
    if pool in ("복승식", "쌍승식"):
        return [res[:2]]
    if pool == "복연승식":
        return [list(c) for c in combinations(top, 2)]
    return [top]                                          # 삼복승식, 삼쌍승식


def build(date: str) -> dict | None:
    pf = DATA / "pred" / f"{date}.json"
    if not pf.exists():
        return None
    races = json.loads(pf.read_text(encoding="utf-8"))["races"]
    if not any(r.get("result") for r in races.values()):
        return None
    table: dict = {}
    for pool in POOLS:
        rows = kra_api.get_all("API160_1/integratedInfo_1", {"meet": 1, "rc_date": date, "pool": pool}, rows=1000)
        for x in rows:
            if str(x.get("pool", pool)) != pool:
                continue
            nums = [int(x.get(c) or 0) for c in ("chulNo", "chulNo2", "chulNo3")]
            nums = [v for v in nums if v > 0]
            try:
                od = float(x.get("odds"))
            except (TypeError, ValueError):
                continue
            table.setdefault(str(int(x.get("rcNo"))), {}).setdefault(pool, {})[key(pool, nums)] = od
    out = {"date": date, "races": {}}
    for rno, r in races.items():
        res = r.get("result")
        if not res or len(res) < 3:
            if r.get("void"):
                out["races"][rno] = {"void": r["void"]}
            continue
        n = len(r.get("odds") or {}) or (len(r.get("p", {})) - len(r.get("out", [])))   # 실제로 뛴 두수
        t = table.get(rno, {})
        o = {"result": res, "runners": n, "out": r.get("out", []), "pay": {}}
        for pool in POOLS:
            for w in winning(pool, res, n):
                k = key(pool, w)
                if k in t.get(pool, {}):
                    o["pay"].setdefault(pool, {})[k] = t[pool][k]
        out["races"][rno] = o
    return out


def write(date: str) -> bool:
    try:
        o = build(date)
    except kra_api.ApiError as e:
        print(f"{date}: 확정 배당 받기 실패: {e}")
        return False
    if not o:
        return False
    if not any(r.get("pay") for r in o["races"].values()):
        print(f"{date}: 확정 배당이 아직 없음")
        return False
    (DATA / "div").mkdir(parents=True, exist_ok=True)
    (DATA / "div" / f"{date}.json").write_text(json.dumps(o, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{date}: 확정 배당 {len(o['races'])}경주")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", action="append", default=[])
    ap.add_argument("--missing", action="store_true")
    ap.add_argument("--max", type=int, default=4)
    a = ap.parse_args()
    dates = list(a.date)
    if a.missing:
        have = {f.stem for f in (DATA / "div").glob("*.json")} if (DATA / "div").exists() else set()
        cand = []
        for f in sorted((DATA / "pred").glob("*.json"), reverse=True):     # 최근 날부터
            if f.stem in have:
                continue
            races = json.loads(f.read_text(encoding="utf-8")).get("races", {})
            if any(r.get("result") for r in races.values()):
                cand.append(f.stem)
        dates += cand[: a.max]
    for d in dict.fromkeys(dates):
        write(d)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
