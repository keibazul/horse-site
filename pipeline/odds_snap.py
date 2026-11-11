"""경주일 당일: 공공데이터의 단승 배당(API160_1, pool=WIN)을 시각과 함께 모아 둠 → work/odds_snap/날짜.csv

목적: 이 배당이 경주 전에 바뀌는 값인지(그러면 사이트 배당 칸을 자동으로 채울 수 있음),
      아니면 한 번 정해지는 초기 값인지(그러면 초기 배당 → 확정 배당 변화가 예측에 도움이 되는지 나중에 검증).
저장: 처음 본 값과 그 뒤 바뀐 값만 한 줄씩 (t, rcNo, chulNo, odds). 실행마다 work/odds_snap/날짜.log 에 (t, 받은 행 수, 바뀐 행 수).
사이트에는 쓰지 않음. 사용: python pipeline/odds_snap.py [--date 20261114]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kra_api  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "work" / "odds_snap"
KST = dt.timezone(dt.timedelta(hours=9))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    a = ap.parse_args()
    now = dt.datetime.now(KST)
    d = a.date or now.strftime("%Y%m%d")
    if not (ROOT / "site" / "data" / "entries" / f"{d}.json").exists():
        return 0                                    # 경주일이 아님
    try:
        rows = kra_api.get_all("API160_1/integratedInfo_1", {"meet": 1, "rc_date": d, "pool": "WIN"}, rows=1000)
    except kra_api.ApiError as e:
        print(f"{d}: 단승 배당 받기 실패 {e}")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f"{d}.csv"
    last: dict[tuple[int, int], str] = {}
    if f.exists():
        with f.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                last[(int(r["rcNo"]), int(r["chulNo"]))] = r["odds"]
    t = now.strftime("%H:%M")
    new = []
    for x in rows:
        try:
            k = (int(x.get("rcNo")), int(x.get("chulNo")))
            od = str(float(x.get("odds")))
        except (TypeError, ValueError):
            continue
        if last.get(k) != od:
            new.append((t, k[0], k[1], od))
            last[k] = od
    if new:
        fresh = not f.exists()
        with f.open("a", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            if fresh:
                w.writerow(["t", "rcNo", "chulNo", "odds"])
            w.writerows(sorted(new, key=lambda r: (r[1], r[2])))
    with (OUT / f"{d}.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{t},{len(rows)},{len(new)}\n")
    print(f"{d} {t}: 단승 배당 {len(rows)}행, 바뀐 값 {len(new)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
