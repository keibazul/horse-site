"""출전마 지난 성적 → site/data/form/날짜.json (사이트에서 말 이름을 누르면 펼쳐 보는 자료)

말: 그날 이전 최근 5경주 [날짜, 경주, 거리, 등급, 착순, 두수, 기록(초), 단승 배당, 마체중, 기수, 주로]
기수: 그날 이전 최근 100회 [기승, 1착, 3착 안], 최근 30일 [기승, 1착]
모두 그날 이전 기록만 쓴다 (예측과 같은 조건).

사용: python pipeline/form.py [--date 20261107 ...] [--missing]   (--missing: 출전표는 있는데 form 파일이 없는 날 모두)
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA, WORK = ROOT / "site" / "data", ROOT / "work"
_hist = None


def load():
    global _hist
    if _hist is not None:
        return _hist
    m = pd.read_csv(WORK / "merged.csv", dtype=str,
                    usecols=["date", "race_no", "hrNo", "jkNo", "jkName", "ord", "rcTime", "rank", "wgHr", "track", "chulNo"])
    m["hrNo"] = m.hrNo.str.strip().str.lstrip("0")
    m["jkNo"] = m.jkNo.str.strip().str.lstrip("0")
    m["race_no"] = pd.to_numeric(m.race_no).astype(int)
    m["ord"] = pd.to_numeric(m.ord, errors="coerce")
    m["rcTime"] = pd.to_numeric(m.rcTime, errors="coerce")
    cols = ["rcDate", "rcNo", "hrNo", "rcDist", "winOdds"]
    parts = [pd.read_csv(WORK / "race_details_all.csv.gz", dtype=str, usecols=cols)]
    parts += [pd.read_csv(f, dtype=str, usecols=cols) for f in glob.glob(str(WORK / "race_details" / "rd_*.csv"))]
    rd = pd.concat(parts).rename(columns={"rcDate": "date"})
    rd["race_no"] = pd.to_numeric(rd.rcNo).astype(int)
    rd["hrNo"] = rd.hrNo.str.strip().str.lstrip("0")
    rd = rd.drop_duplicates(["date", "race_no", "hrNo"], keep="last")[["date", "race_no", "hrNo", "rcDist", "winOdds"]]
    m = m.merge(rd, on=["date", "race_no", "hrNo"], how="left")
    ran = m.ord.between(1, 16) | m.ord.between(91, 92)
    m = m[ran].copy()
    m["n"] = m.groupby(["date", "race_no"]).hrNo.transform("size")
    m = m.sort_values(["date", "race_no"]).reset_index(drop=True)
    _hist = m
    return m


def num(x, f=float):
    try:
        v = f(float(x))
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def build(date: str, rows: list[dict]) -> dict:
    m = load()
    before = m[m.date < date]
    out = {"date": date, "races": {}}
    hr_ids = {str(r.get("hrNo", "")).strip().lstrip("0") for r in rows}
    jk_ids = {str(r.get("jkNo", "")).strip().lstrip("0") for r in rows}
    h = before[before.hrNo.isin(hr_ids)].groupby("hrNo").tail(5)
    hmap = {k: g for k, g in h.groupby("hrNo")}
    j = before[before.jkNo.isin(jk_ids)]
    lo30 = (pd.Timestamp(date) - pd.Timedelta(days=30)).strftime("%Y%m%d")
    jmap = {}
    for k, g in j.groupby("jkNo"):
        t = g.tail(100)
        r30 = g[g.date >= lo30]
        jmap[k] = [len(t), int((t.ord == 1).sum()), int((t.ord <= 3).sum()), len(r30), int((r30.ord == 1).sum())]
    for r in rows:
        rn, ch = str(int(r["rcNo"])), str(int(r["chulNo"]))
        hk = str(r.get("hrNo", "")).strip().lstrip("0")
        g = hmap.get(hk)
        starts = []
        if g is not None:
            for x in g.iloc[::-1].itertuples():
                starts.append([x.date, int(x.race_no), num(x.rcDist, int), (x.rank or "").replace("등급", ""),
                               int(x.ord), int(x.n), num(x.rcTime), num(x.winOdds), x.wgHr if isinstance(x.wgHr, str) else None,
                               x.jkName if isinstance(x.jkName, str) else None,
                               (x.track.split("(")[0].strip() if isinstance(x.track, str) else None)])
        out["races"].setdefault(rn, {})[ch] = {"h": starts, "j": jmap.get(str(r.get("jkNo", "")).strip().lstrip("0"))}
    return out


def write(date: str) -> bool:
    ef = DATA / "entries" / f"{date}.json"
    if not ef.exists():
        return False
    rows = json.loads(ef.read_text(encoding="utf-8"))["rows"]
    (DATA / "form").mkdir(exist_ok=True)
    (DATA / "form" / f"{date}.json").write_text(json.dumps(build(date, rows), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", action="append", default=[])
    ap.add_argument("--missing", action="store_true")
    a = ap.parse_args()
    dates = list(a.date)
    if a.missing:
        have = {f.stem for f in (DATA / "form").glob("*.json")} if (DATA / "form").exists() else set()
        dates += [f.stem for f in sorted((DATA / "entries").glob("*.json")) if f.stem not in have]
    n = sum(write(d) for d in dict.fromkeys(dates))
    print(f"지난 성적 파일: {n}일")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
