"""지난 경주일을 사이트에 채워 넣기 (출전표·예측·시뮬레이션).

출전표 API 대신 경주성적정보(race_details)와 경주 기록(merged.csv)으로 그날 출전표를 다시 만든다
(출전 취소마 포함, 마체중·날씨 등 경주 직전 정보는 넣지 않음). 예측은 site_export.export 와 같고,
경주일보다 앞에서 학습이 끝난 모델(winner_history_bt)을 쓰므로 '경주 전에 낸 예측'과 같은 조건이다.

사용: python backfill.py --start 20251101 --end 20261031 [--part 0 --parts 4] [--force]
결과: ../site/data/entries/날짜.json, ../site/data/pred/날짜.json, ../site/data/sim/sim_날짜_R*.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

import pandas as pd

import site_export as se

DATA = Path(__file__).resolve().parents[1] / "site" / "data"
KST = dt.timezone(dt.timedelta(hours=9))
KEEP = ["rcDate", "rcNo", "chulNo", "hrNo", "hrName", "jkNo", "jkName", "trNo", "trName", "sex", "age", "wgBudam",
        "rank", "rcDist", "rating", "wgJk", "budam", "ageCond", "rcName"]


def entries_from_records(date: str, rd: pd.DataFrame, hist: pd.DataFrame) -> list[dict]:
    d = pd.read_csv(Path(se.DETAILS_DIR) / f"rd_{date}.csv", dtype=str) if (Path(se.DETAILS_DIR) / f"rd_{date}.csv").exists() else None
    if d is None:
        d = _rd_full(date)
    d = d[[c for c in KEEP if c in d.columns]].copy()
    st = _start_times().get(date, {})
    d["stTime"] = pd.to_numeric(d["rcNo"]).astype(int).map(st).fillna("")
    d["meet"] = "서울"
    d = d.assign(_r=pd.to_numeric(d["rcNo"]), _c=pd.to_numeric(d["chulNo"])).sort_values(["_r", "_c"]).drop(columns=["_r", "_c"])
    rows = []
    for r in d.to_dict("records"):
        out = {}
        for k, v in r.items():
            if pd.isna(v):
                continue
            if k in ("rcNo", "chulNo", "age", "rcDist", "rating"):
                try:
                    v = int(float(v))
                except ValueError:
                    pass
            elif k in ("wgBudam", "wgJk"):
                try:
                    v = float(v)
                except ValueError:
                    pass
            out[k] = v
        rows.append(out)
    return rows


_rd_all = None
_st = None


def _start_times() -> dict:
    """merged.csv 의 schStTime('2025-11-02T10:35:00+09:00') → {날짜: {경주: '10:35'}}"""
    global _st
    if _st is None:
        m = pd.read_csv(se.HISTORY, dtype=str, usecols=["date", "race_no", "schStTime"]).dropna().drop_duplicates(["date", "race_no"])
        _st = {}
        for d, r, t in zip(m["date"], m["race_no"], m["schStTime"]):
            if "T" in t:
                _st.setdefault(d, {})[int(float(r))] = t[11:16]
    return _st


def _rd_full(date: str) -> pd.DataFrame:
    """race_details_all.csv.gz 에서 그날 행 전체 (출전표에 쓸 열 포함)"""
    global _rd_all
    if _rd_all is None:
        _rd_all = pd.read_csv(se.DETAILS, dtype=str, usecols=lambda c: c in KEEP)
    return _rd_all[_rd_all["rcDate"] == date]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--part", type=int, default=0, help="여러 대로 나눠 돌릴 때 몇 번째 몫인지 (0부터)")
    ap.add_argument("--parts", type=int, default=1)
    ap.add_argument("--force", action="store_true", help="이미 만든 날도 다시")
    a = ap.parse_args()
    hist, rd = se._load()
    dates = sorted(d for d in hist["date"].unique() if a.start <= d <= a.end)
    dates = dates[a.part::a.parts]
    for sub in ("entries", "pred", "sim"):
        (DATA / sub).mkdir(parents=True, exist_ok=True)
    print(f"대상 {len(dates)}일 (몫 {a.part + 1}/{a.parts}): {dates[:1]} ~ {dates[-1:]}", flush=True)
    t0 = time.time()
    for k, d in enumerate(dates, 1):
        pf = DATA / "pred" / f"{d}.json"
        if pf.exists() and not a.force:
            j = json.loads(pf.read_text(encoding="utf-8"))
            if j.get("v", 1) >= 2 and j.get("backtestDone") and j.get("modelDir") == se.pick_model(d):
                continue
        ef = DATA / "entries" / f"{d}.json"
        if ef.exists():                      # 출전표 API 로 받아 둔 날은 그대로 사용
            rows = json.loads(ef.read_text(encoding="utf-8"))["rows"]
        else:
            rows = entries_from_records(d, rd, hist)
            ef.write_text(json.dumps({"date": d, "fetched": "기록으로 재구성", "rows": rows}, ensure_ascii=False), encoding="utf-8")
        res = se.export(d, rows, DATA)
        res["date"] = d
        res["made"] = dt.datetime.now(KST).isoformat(timespec="minutes")
        pf.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
        print(f"[{k}/{len(dates)}] {d} 완료 · 모델 {res['modelDir']} · 누적 {time.time() - t0:.0f}초", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
