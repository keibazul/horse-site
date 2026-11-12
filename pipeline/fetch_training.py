"""서울 일별 조교 기록 (공공데이터 '서울일별조교현황', API338) → work/training/연월.csv.gz

하루 1요청(약 700~900행). 날짜 범위로 물으면 시작일만 돌려줘서 하루씩 받는다. 개발 계정은 하루 3,000요청.
열: exerDt, hrnm, trarNm, belo, exerNo, exerTm(조교 시간 h:mm), admTim(입장), wkotTim(퇴장), remkTxt, ridr(탄 사람 구분), seq
사용: python pipeline/fetch_training.py --since 20220101 [--until 20261111] [--max 2800]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kra_api  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "work" / "training"
COLS = ["exerDt", "hrnm", "trarNm", "belo", "exerNo", "exerTm", "admTim", "wkotTim", "remkTxt", "ridr", "seq"]
KST = dt.timezone(dt.timedelta(hours=9))


def have_days(f: Path) -> set[str]:
    if not f.exists():
        return set()
    with gzip.open(f, "rt", encoding="utf-8") as fh:
        return {r["exerDt"] for r in csv.DictReader(fh)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", default=(dt.datetime.now(KST) - dt.timedelta(days=1)).strftime("%Y%m%d"))
    ap.add_argument("--max", type=int, default=2800)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    d0, d1 = dt.datetime.strptime(a.since, "%Y%m%d"), dt.datetime.strptime(a.until, "%Y%m%d")
    done: dict[str, set[str]] = {}
    empty = OUT / "empty_days.txt"                       # 조교가 없던 날(휴장 등)은 다시 묻지 않음
    skip = set(empty.read_text().split()) if empty.exists() else set()
    n = 0
    d = d0
    buf: dict[str, list] = {}
    def flush(m):
        rows = buf.pop(m, [])
        if not rows:
            return
        f = OUT / f"{m}.csv.gz"
        old = []
        if f.exists():
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                old = list(csv.DictReader(fh))
        with gzip.open(f, "wt", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(sorted(old + rows, key=lambda r: (str(r["exerDt"]), int(r.get("seq") or 0))))
    cur_m = None
    while d <= d1 and n < a.max:
        ds, m = d.strftime("%Y%m%d"), d.strftime("%Y%m")
        if m != cur_m:
            if cur_m:
                flush(cur_m)
            cur_m = m
            done[m] = have_days(OUT / f"{m}.csv.gz")
        d += dt.timedelta(days=1)
        if ds in done[m] or ds in skip:
            continue
        try:
            rows = kra_api.get_all("API338/textDataSeDalyExer", {"exer_stdt": ds, "exer_spdt": ds}, rows=1000)
        except kra_api.ApiError as e:
            print(f"{ds}: 실패 {e}", flush=True)
            if "LIMITED" in str(e).upper() or "초과" in str(e):
                break
            continue
        n += 1
        rows = [r for r in rows if str(r.get("exerDt")) == ds]
        if not rows:
            skip.add(ds)
            continue
        buf.setdefault(m, []).extend({c: r.get(c, "") for c in COLS} for r in rows)
        if n % 50 == 0:
            print(f"{ds}: 요청 {n}", flush=True)
    if cur_m:
        flush(cur_m)
    empty.write_text("\n".join(sorted(skip)))
    print(f"끝: 요청 {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
