"""경주일 변경 사항: 공공데이터 '서울기수변경말취소'(API320) → site/data/changes/날짜.json

말취소(출전 취소)와 기수변경을 이유와 함께 받는다 (예: "마체이상", "6R 후 왼팔 통증").
출전표정보(API78)의 특이사항과 함께 run_all.pre_race_changes 가 읽어 취소마를 빼고 예측한다.
저장: {date, fetched, rows:[{race, no, name, kind:"말취소"|"기수변경", before, after, wgt, why}]}
사용: python pipeline/changes.py --dates 20261114,20261115
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kra_api  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "data" / "changes"
KST = dt.timezone(dt.timedelta(hours=9))


def clean(v):
    v = "" if v is None else str(v).strip()
    return "" if v == "-" else v


def fetch(d: str) -> list[dict]:
    rows = kra_api.get_all("API320/textDataHoldSeChgInfo", {"race_dt": d}, rows=200)
    out = []
    for r in rows:
        try:
            out.append({"race": int(r.get("raceNo")), "no": int(r.get("pthrNo")), "name": clean(r.get("hrnm")), "kind": clean(r.get("gbNm")),
                        "before": clean(r.get("chbfJcky")), "after": clean(r.get("chafJcky")), "wgt": clean(r.get("burdWgt")), "why": clean(r.get("rs"))})
        except (TypeError, ValueError):
            continue
    return sorted(out, key=lambda x: (x["race"], x["no"], x["kind"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", required=True)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for d in [x for x in a.dates.split(",") if x]:
        try:
            rows = fetch(d)
        except kra_api.ApiError as e:
            print(f"{d}: 기수변경·말취소 받기 실패 {e}")
            continue
        f = OUT / f"{d}.json"
        try:
            if f.exists() and json.loads(f.read_text(encoding="utf-8")).get("rows") == rows:
                continue
        except ValueError:
            pass
        f.write_text(json.dumps({"date": d, "fetched": dt.datetime.now(KST).isoformat(timespec="minutes"), "rows": rows}, ensure_ascii=False), encoding="utf-8")
        print(f"{d}: 기수변경·말취소 {len(rows)}건 " + ", ".join(f"{x['race']}R {x['no']}번 {x['kind']}" for x in rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
