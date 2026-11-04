"""경주 전 추가 정보 받기 → work/extra/api314.csv.gz, work/extra/api78.csv.gz

API314 서울출전마현황 (B551015/API314/textDataHoldSePtinInfo): 보조장구 1~5, 폐출혈 최근 1~2, 최근 진료 1~2 (날짜+내용)
API78  출전표정보   (B551015/API78/chulmainfo, rccrs_cd=1): 조교 횟수(출전 신청 전 2~3주), 출전 주기, 장구 변화(+신규/−해지), 특이사항

날짜당 API 하나에 1번 호출 (numOfRows 300). 이미 받은 날짜는 건너뛴다 (이어받기).
사용: python pipeline/fetch_extra.py --from 20190101 [--to 20261101] [--dates 20261107,20261108] [--limit 1400]
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kra_api  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "work" / "extra"
F314 = ["raceDt", "raceNo", "pthrNo", "hrnm", "asisEquip1", "asisEquip2", "asisEquip3", "asisEquip4", "asisEquip5",
        "latstBledg1", "latstBledg2", "latstTrea1Txt", "latstTrea2Txt"]
F78 = ["raceDt", "raceNo", "gtno", "hrnm", "trngTcnt", "ptinCycl", "equipCrs", "spn", "wgtIndec"]
KST = dt.timezone(dt.timedelta(hours=9))


def load(name: str) -> pd.DataFrame:
    f = OUT / f"{name}.csv.gz"
    return pd.read_csv(f, dtype=str) if f.exists() else pd.DataFrame(columns=["date"])


def race_dates(a: str, b: str) -> list[str]:
    m = pd.read_csv(ROOT / "work" / "merged.csv", dtype=str, usecols=["date"]).date.drop_duplicates()
    return sorted(d for d in m if a <= d <= b)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="a", default="20190101")
    ap.add_argument("--to", dest="b", default=dt.datetime.now(KST).strftime("%Y%m%d"))
    ap.add_argument("--dates", help="쉼표로 구분한 날짜 (출전표가 있는 앞으로 열릴 날 등)")
    ap.add_argument("--limit", type=int, default=1400, help="이번 실행 최대 호출 수")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    dates = a.dates.split(",") if a.dates else race_dates(a.a, a.b)
    calls = 0
    for name, path, extra, fields in (("api314", "API314/textDataHoldSePtinInfo", {}, F314),
                                      ("api78", "API78/chulmainfo", {"rccrs_cd": 1}, F78)):
        old = load(name)
        have = set(old["date"]) if len(old) else set()
        todo = [d for d in dates if d not in have or a.dates]        # --dates 로 준 날은 다시 받음 (당일 변경 반영)
        parts, n_ok = [], 0
        print(f"{name}: 받을 날 {len(todo)}일", flush=True)
        for d in todo:
            if calls >= a.limit:
                print("이번 실행 호출 한도에 도달 (다음에 이어받기)"); break
            try:
                rows = kra_api.get_all(path, {**extra, "race_dt": d}, rows=300)
                calls += 1
            except kra_api.ApiError as e:
                print(f"  {d} 실패: {e}"); calls += 1
                if "한도" in str(e) or "응답하지" in str(e):
                    break
                continue
            df = pd.DataFrame(rows)
            if df.empty:
                df = pd.DataFrame([{"date": d}])                   # 빈 날도 기록 (다시 묻지 않게)
            else:
                df = df.reindex(columns=fields).astype(str).assign(date=d)
            parts.append(df); n_ok += 1
            if n_ok % 50 == 0:
                print(f"  {d} 까지 {n_ok}일", flush=True)
            time.sleep(0.25)
        if parts:
            new = pd.concat(parts, ignore_index=True)
            if a.dates and len(old):
                old = old[~old["date"].isin(set(new["date"]))]
            allf = pd.concat([old, new], ignore_index=True).sort_values(["date"]).reset_index(drop=True)
            allf.to_csv(OUT / f"{name}.csv.gz", index=False, compression="gzip")
            print(f"{name}: {n_ok}일 추가 → 모두 {allf['date'].nunique()}일 {len(allf)}행", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
