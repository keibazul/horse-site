"""지난 경주일의 모든 조합 확정 배당 (API160_1) → work/odds_full/날짜.csv.gz  (베팅 계획 검증용, 사이트에는 안 씀)

사용: python pipeline/fetch_odds_full.py --since 20251101 [--max 200]
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kra_api  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "work" / "odds_full"
COLS = ["rcNo", "pool", "chulNo", "chulNo2", "chulNo3", "odds"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="20251101")
    ap.add_argument("--max", type=int, default=200)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    days = []
    for f in sorted((ROOT / "site" / "data" / "pred").glob("*.json")):
        if f.stem < a.since or (OUT / f"{f.stem}.csv.gz").exists():
            continue
        races = json.loads(f.read_text(encoding="utf-8")).get("races", {})
        if races and all(r.get("result") or r.get("void") for r in races.values()):   # 하루가 다 끝난 날만
            days.append(f.stem)
    for d in days[: a.max]:
        try:
            rows = kra_api.get_all("API160_1/integratedInfo_1", {"meet": 1, "rc_date": d}, rows=1000)
        except kra_api.ApiError as e:
            print(f"{d}: 실패 {e}")
            continue
        with gzip.open(OUT / f"{d}.csv.gz", "wt", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(COLS)
            for x in rows:
                w.writerow([x.get(c, "") for c in COLS])
        print(f"{d}: {len(rows)}행", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
