"""지난 경주일의 모든 조합 확정 배당 (API160_1) → work/odds_full/날짜.csv.gz  (베팅 계획 검증용, 사이트에는 안 씀)

사용: python pipeline/fetch_odds_full.py --since 20251101 [--max 200] [--until 20251031 --history]
  --history: 경주일 목록을 예측 파일 대신 경주 기록(work/race_details_all.csv.gz + work/race_details/)에서 가져옴 (예전 날짜 채우기)
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
    ap.add_argument("--until", default="99999999")
    ap.add_argument("--history", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    days = []
    if a.history:
        import glob
        import gzip as gz
        seen = set()
        for p in [ROOT / "work" / "race_details_all.csv.gz"] + sorted(Path(x) for x in glob.glob(str(ROOT / "work" / "race_details" / "rd_*.csv"))):
            op = gz.open if p.suffix == ".gz" else open
            with op(p, "rt", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    seen.add(r.get("rcDate", ""))
        days = [d for d in sorted(seen) if a.since <= d <= a.until and len(d) == 8 and not (OUT / f"{d}.csv.gz").exists()]
    for f in ([] if a.history else sorted((ROOT / "site" / "data" / "pred").glob("*.json"))):
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
