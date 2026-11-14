"""경주일 당일: 끝난 경주의 결과를 예측 파일에 바로 넣음 (경주 끝나고 몇 분~수십 분 안에 공공데이터에 올라옴)

경주성적정보(API214_1)에서 착순, 확정 단승 배당(winOdds), 연승 배당(plcOdds), 출전 취소를 받아
site/data/pred/오늘.json 의 races[n] 에 result / odds / plc / out 을 채운다. 예측(p)·시뮬레이션은 그대로.
저녁에 기록 갱신이 끝나면 run_all 이 실제 구간 기록을 넣어 예측 파일을 다시 만든다(그때 덮어씀).

사용: python pipeline/live_results.py [--date 20261108]
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
DATA = ROOT / "site" / "data"
KST = dt.timezone(dt.timedelta(hours=9))


def num(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    a = ap.parse_args()
    d = a.date or dt.datetime.now(KST).strftime("%Y%m%d")
    pf = DATA / "pred" / f"{d}.json"
    if not pf.exists() or not (DATA / "entries" / f"{d}.json").exists():
        return 0
    pred = json.loads(pf.read_text(encoding="utf-8"))
    if pred.get("backtestDone"):
        return 0                                   # 저녁 갱신이 이미 끝난 날
    try:
        rows = kra_api.get_all("API214_1/RaceDetailResult_1", {"meet": 1, "rc_date": d}, rows=1000)
    except kra_api.ApiError as e:
        print(f"{d}: 당일 결과 받기 실패 {e}")
        return 0
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(str(int(r.get("rcNo") or 0)), []).append(r)
    changed = []
    for rn, rs in sorted(by.items(), key=lambda x: int(x[0])):
        race = pred.get("races", {}).get(rn)
        if race is None:
            continue
        ords = {int(r["chulNo"]): int(r.get("ord") or 0) for r in rs}
        fin = sorted((o, c) for c, o in ords.items() if 1 <= o <= 16)
        if len(fin) < 3:
            continue
        res = [c for _, c in fin]
        odds = {str(int(r["chulNo"])): num(r.get("winOdds")) for r in rs if num(r.get("winOdds"))}
        plc = {str(int(r["chulNo"])): num(r.get("plcOdds")) for r in rs if num(r.get("plcOdds"))}
        # 출전 취소: 취소 코드(93 출발제외·94 경주제외·95 출전취소)이거나, 착순도 단승 배당도 없는 말.
        # 결과는 1~3착부터 올라오고 나머지 착순은 조금 뒤에 채워짐 → 착순이 아직 없어도 배당이 있으면 달린 말 (2026-11-14: 이런 말을 취소로 잘못 넣었음)
        gone = sorted(c for c, o in ords.items() if o in (93, 94, 95) or (o == 0 and str(c) not in odds))
        partial = any(o == 0 and str(c) in odds for c, o in ords.items())
        if "out0" not in race:
            race["out0"] = sorted(map(int, race.get("out", []))) if not race.get("live") else []      # 경주 전에 알려진 취소
        new = {"result": res, "odds": odds, "plc": plc, "out": sorted(set(race["out0"]) | set(gone)), "live": True, "partial": partial}
        if any(race.get(k) != v for k, v in new.items()):
            race.update(new)
            changed.append(int(rn))
    if changed:
        pf.write_text(json.dumps(pred, ensure_ascii=False), encoding="utf-8")
        print(f"{d}: 결과 들어온 경주 {changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
