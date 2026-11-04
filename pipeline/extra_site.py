"""사이트 참고 정보 (예측에는 쓰지 않음) → site/data/extra/날짜.json

말마다: 최근 진료 2건 [날짜, 내용], 폐출혈 최근 2건, 조교 횟수(출전 신청 전 2~3주)와 경주 평균 대비, 출전 주기, 장구 변화, 특이사항
- 앞으로 열릴 날: API314(서울출전마현황)·API78(출전표정보)에서 받음 (날짜당 2번 호출)
- 지난 날: work/extra/api314.csv.gz, api78.csv.gz 에 모아 둔 기록에서

사용: python pipeline/extra_site.py --dates 20261107,20261108     (API)
      python pipeline/extra_site.py --archive-missing              (지난 날 중 파일이 없는 날, 기록에서)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
DATA, WORK = ROOT / "site" / "data", ROOT / "work"


def _num(x):
    m = re.search(r"-?\d+(?:\.\d+)?", str(x)) if x is not None else None
    return float(m.group()) if m else None


def _clean(x):
    s = "" if x is None else str(x).strip()
    return "" if s in ("-", "nan", "None") else s


def _trea(s):
    s = _clean(s)
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})\s*(.*)", s)
    return [f"{m.group(1)}{m.group(2)}{m.group(3)}", m.group(4).strip()] if m else ([None, s] if s else None)


def build(date: str, r314: list[dict], r78: list[dict]) -> dict:
    races: dict = {}
    for x in r314:
        rn, ch = _num(x.get("raceNo")), _num(x.get("pthrNo"))
        if rn is None or ch is None:
            continue
        o = races.setdefault(str(int(rn)), {}).setdefault(str(int(ch)), {})
        o["trea"] = [t for t in (_trea(x.get("latstTrea1Txt")), _trea(x.get("latstTrea2Txt"))) if t]
        o["bleed"] = [b for b in (_clean(x.get("latstBledg1")), _clean(x.get("latstBledg2"))) if b]
    for x in r78:
        rn, ch = _num(x.get("raceNo")), _num(x.get("gtno"))
        if rn is None or ch is None:
            continue
        o = races.setdefault(str(int(rn)), {}).setdefault(str(int(ch)), {})
        t = _num(x.get("trngTcnt"))
        o["trng"] = int(t) if t is not None else None
        c = _num(x.get("ptinCycl"))
        o["cycle"] = int(c) if c is not None else None
        o["equip"] = _clean(x.get("equipCrs"))
        o["spn"] = _clean(x.get("spn"))
    for rn, hs in races.items():                                   # 조교 횟수: 같은 경주 평균 대비
        ts = [h["trng"] for h in hs.values() if h.get("trng") is not None]
        if ts:
            m = sum(ts) / len(ts)
            for h in hs.values():
                if h.get("trng") is not None:
                    h["trngRel"] = round(h["trng"] - m, 1)
    return {"date": date, "races": races}


def write(date: str, obj: dict) -> bool:
    (DATA / "extra").mkdir(parents=True, exist_ok=True)
    f = DATA / "extra" / f"{date}.json"
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if f.exists() and f.read_text(encoding="utf-8") == s:          # 바뀐 게 없으면 그대로 (커밋이 쌓이지 않게)
        return False
    f.write_text(s, encoding="utf-8")
    return True


def from_api(date: str) -> bool:
    import kra_api
    r314 = kra_api.get_all("API314/textDataHoldSePtinInfo", {"race_dt": date}, rows=300)
    r78 = kra_api.get_all("API78/chulmainfo", {"rccrs_cd": 1, "race_dt": date}, rows=300)
    if not r314 and not r78:
        print(f"{date}: 참고 정보 없음 (아직 공개 전)")
        return False
    ch = write(date, build(date, r314, r78))
    print(f"{date}: 참고 정보 {len(r314)}·{len(r78)}두{' (바뀜)' if ch else ' (그대로)'}")
    return ch


def archive_missing() -> int:
    import pandas as pd
    a = pd.read_csv(WORK / "extra" / "api314.csv.gz", dtype=str)
    b = pd.read_csv(WORK / "extra" / "api78.csv.gz", dtype=str)
    have = {f.stem for f in (DATA / "extra").glob("*.json")} if (DATA / "extra").exists() else set()
    days = sorted(f.stem for f in (DATA / "entries").glob("*.json") if f.stem not in have)
    ga, gb = dict(tuple(a.groupby("date"))), dict(tuple(b.groupby("date")))
    n = 0
    for d in days:
        if d in ga or d in gb:
            r314 = ga[d].to_dict("records") if d in ga else []
            r78 = gb[d].to_dict("records") if d in gb else []
            n += write(d, build(d, r314, r78))
    print(f"지난 경주일 참고 정보: {n}일")
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", default="")
    ap.add_argument("--archive-missing", action="store_true")
    a = ap.parse_args()
    if a.archive_missing:
        archive_missing()
    for d in [x for x in a.dates.split(",") if x]:
        try:
            from_api(d)
        except Exception as e:                       # 참고 정보가 안 받아져도 나머지 업데이트는 계속
            print(f"{d}: 참고 정보 받기 실패: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
