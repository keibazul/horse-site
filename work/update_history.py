"""경주 기록을 최신으로 맞춤 (GitHub Actions 용, PC 의 kra_race_collector → merge_to_excel → fetch_race_details 를 대신함).

1. merged.zip(2026-10-31까지) 을 풀고, results/rr_날짜.csv(그 뒤 경주 결과)를 붙여 merged.csv 를 만든다.
2. 마지막 경주일 다음 날 ~ 어제(한국 시간) 사이에 경주가 있었으면
   - 경주결과(API299, 날짜 단위) → results/rr_날짜.csv  (merged.csv 와 같은 열)
   - 경주성적정보(API214_1) → race_details/rd_날짜.csv  (features_v5.load_details 가 자동으로 읽음)
   를 받아 저장하고 merged.csv 에 붙인다.
작은 날짜별 파일만 저장소에 커밋하므로 저장소가 크게 늘지 않는다.

사용: python update_history.py [--no-fetch]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import zipfile
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
import kra_api  # noqa: E402

KST = dt.timezone(dt.timedelta(hours=9))
RES_DIR, RD_DIR = HERE / "results", HERE / "race_details"


def build_merged() -> pd.DataFrame:
    with zipfile.ZipFile(HERE / "merged.zip") as z:
        with z.open("merged.csv") as f:
            base = pd.read_csv(f, dtype=str)
    cols = list(base.columns)
    last = base["date"].max()
    parts = [base]
    for f in sorted(RES_DIR.glob("rr_*.csv")):
        if f.stem[3:] > last:
            parts.append(pd.read_csv(f, dtype=str).reindex(columns=cols))
    m = pd.concat(parts, ignore_index=True)
    return m


def fetch_results(d: str) -> pd.DataFrame:
    rows = kra_api.get_all("API299/Race_Result_total", {"meet": 1, "rc_year": d[:4], "rc_month": d[:6], "rc_date": d})
    rows = [r for r in rows if str(r.get("rcDate", d)) == d]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df.insert(0, "file_no", "")
    df.insert(0, "race_no", pd.to_numeric(df["rcNo"]).astype(int))
    df.insert(0, "date", d)
    return df.sort_values(["race_no", "ord"], key=lambda s: pd.to_numeric(s, errors="coerce")).reset_index(drop=True)


def fetch_details(d: str) -> pd.DataFrame:
    return pd.DataFrame(kra_api.get_all("API214_1/RaceDetailResult_1", {"meet": 1, "rc_date": d}, rows=1000))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true", help="API 를 부르지 않고 merged.csv 만 다시 만든다")
    a = ap.parse_args()
    RES_DIR.mkdir(exist_ok=True)
    RD_DIR.mkdir(exist_ok=True)
    m = build_merged()
    last = m["date"].max()
    print(f"경주 기록: ~{last} ({len(m):,}행)")

    if not a.no_fetch:
        yday = dt.datetime.now(KST).date() - dt.timedelta(days=1)
        d0 = dt.datetime.strptime(last, "%Y%m%d").date() + dt.timedelta(days=1)
        new = []
        while d0 <= yday:
            d = d0.strftime("%Y%m%d")
            d0 += dt.timedelta(days=1)
            try:
                r = fetch_results(d)
            except kra_api.ApiError as e:
                print(f"{d}: 경주결과 조회 실패 → {e}")
                break
            if r.empty:
                continue
            fin = pd.to_numeric(r["ord"], errors="coerce").between(1, 16).sum()
            if fin == 0:
                print(f"{d}: 결과가 아직 확정되지 않음 (다음 실행 때 다시)")
                break
            r.to_csv(RES_DIR / f"rr_{d}.csv", index=False)
            print(f"{d}: 경주결과 {r['race_no'].nunique()}경주 {len(r)}행 저장")
            if not (RD_DIR / f"rd_{d}.csv").exists():
                try:
                    det = fetch_details(d)
                    if len(det):
                        det.to_csv(RD_DIR / f"rd_{d}.csv", index=False)
                        print(f"{d}: 경주성적정보 {len(det)}행 저장")
                    else:
                        print(f"{d}: 경주성적정보가 아직 없음")
                except kra_api.ApiError as e:
                    print(f"{d}: 경주성적정보 조회 실패 → {e}")
            new.append(d)
        if new:
            m = build_merged()
        # 결과는 있는데 경주성적정보를 못 받은 날 다시 시도
        for f in sorted(RES_DIR.glob("rr_*.csv")):
            d = f.stem[3:]
            if not (RD_DIR / f"rd_{d}.csv").exists():
                try:
                    det = fetch_details(d)
                    if len(det):
                        det.to_csv(RD_DIR / f"rd_{d}.csv", index=False)
                        print(f"{d}: 경주성적정보 {len(det)}행 저장 (재시도)")
                except kra_api.ApiError as e:
                    print(f"{d}: 경주성적정보 재시도 실패 → {e}")

    m.to_csv(HERE / "merged.csv", index=False)
    print(f"merged.csv: ~{m['date'].max()} ({len(m):,}행)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
