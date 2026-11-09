"""당일 주로 경향(안쪽·바깥쪽 유리) → site/data/bias/날짜.json

그날 앞서 끝난 경주들의 3착 안 말이 안쪽 게이트(출전번호 순서)였는지로 '안쪽 유리 정도'를 재고,
뒤 경주의 말마다 우승 확률에 곱할 보정값을 만든다.
  IB = (0.483 − 앞 경주 3착 안 말들의 게이트 위치 평균) / 0.0963     (게이트 위치: 안쪽 0 ~ 바깥 1, 앞 경주 2개 이상일 때)
  보정값 = exp(0.157 × IB × (0.5 − 게이트 위치))
검증: 2008~2019 로 정한 계수로 2022~2026 4,930경주에서 시장 대비 로그 손실 −0.0037 [−0.0052, −0.0025],
      사이트 모델(지난 1년 950경주) −0.0053 [−0.0085, −0.0019], 결합 −0.0037 [−0.0068, −0.0005].
오늘은 경주성적정보(API214_1)에서 끝난 경주 결과를 받아 계산(경주 끝나고 수십 분 안에 올라옴), 지난 날은 경주 기록(work/merged.csv)으로.
게이트 위치는 완주마(착순 1~16) 사이의 번호 순서, 앞 경주는 경주마다 3착 안 평균을 낸 뒤 경주들끼리 평균 (학습 특징과 같은 정의).

사용: python pipeline/live_bias.py [--date 20261108] [--past]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kra_api  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data"
OUT = DATA / "bias"
K, MU, SD, MIN_PREV = 0.157, 0.483, 0.0963, 2
KST = dt.timezone(dt.timedelta(hours=9))


def load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def live_results(d: str) -> dict[int, list[tuple[int, int]]]:
    """오늘 끝난 경주: {경주: [(번호, 착순), ...]} — 착순 1~16 인 완주마만"""
    rows = kra_api.get_all("API214_1/RaceDetailResult_1", {"meet": 1, "rc_date": d}, rows=1000)
    out: dict[int, list] = {}
    for r in rows:
        try:
            rn, ch, o = int(r.get("rcNo")), int(r.get("chulNo")), int(r.get("ord") or 0)
        except (TypeError, ValueError):
            continue
        if 1 <= o <= 16:
            out.setdefault(rn, []).append((ch, o))
    return {k: v for k, v in out.items() if len(v) >= 3}


def history_results(d: str) -> dict[int, list[tuple[int, int]]]:
    """지난 날: work/merged.csv 의 완주마 (번호, 착순)"""
    import csv
    f = ROOT / "work" / "merged.csv"
    out: dict[int, list] = {}
    if not f.exists():
        return out
    with f.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("date") != d:
                continue
            try:
                o = int(float(r["ord"]))
                if 1 <= o <= 16:
                    out.setdefault(int(r["race_no"]), []).append((int(float(r["chulNo"])), o))
            except (TypeError, ValueError, KeyError):
                continue
    return out


def build(d: str, results: dict[int, list]) -> dict | None:
    """학습(work/features_v5.day_bias_features)과 같은 정의:
       앞 경주마다 완주마 사이 게이트 위치(번호 순서, 0~1)로 3착 안 말 평균 → 경주들의 평균 → IB"""
    ent, pred = load(DATA / "entries" / f"{d}.json"), load(DATA / "pred" / f"{d}.json") or {}
    if not ent:
        return None
    races = sorted({int(r["rcNo"]) for r in ent["rows"]})
    top_gp = {}
    for n, fin in results.items():
        cs = sorted(c for c, _ in fin)
        pos = {c: i / max(len(cs) - 1, 1) for i, c in enumerate(cs)}
        tops = [pos[c] for c, o in fin if o <= 3]
        if tops:
            top_gp[n] = sum(tops) / len(tops)
    o = {"date": d, "done": sorted(top_gp), "races": {}}
    for n in races:
        gone = set(map(int, (pred.get("races", {}).get(str(n), {}) or {}).get("out", [])))
        ids = sorted(int(r["chulNo"]) for r in ent["rows"] if int(r["rcNo"]) == n and int(r["chulNo"]) not in gone)
        gp = {c: (i / (len(ids) - 1) if len(ids) > 1 else 0.5) for i, c in enumerate(ids)}
        prev = [top_gp[m] for m in races if m < n and m in top_gp]
        if len(prev) < MIN_PREV:
            o["races"][str(n)] = {"nprev": len(prev), "gp": {str(c): round(g, 4) for c, g in gp.items()}}
            continue
        ib = (MU - sum(prev) / len(prev)) / SD
        o["races"][str(n)] = {"nprev": len(prev), "ib": round(ib, 3), "gp": {str(c): round(g, 4) for c, g in gp.items()},
                              "f": {str(c): round(math.exp(K * ib * (0.5 - g)), 4) for c, g in gp.items()}}
    return o


def write(d: str, o: dict) -> bool:
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f"{d}.json"
    old = load(f)
    if old and {k: v for k, v in old.items() if k != "updated"} == o:
        return False
    o = {**o, "updated": dt.datetime.now(KST).strftime("%Y-%m-%dT%H:%M")}
    f.write_text(json.dumps(o, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--past", action="store_true", help="지난 날 중 파일 없는 날을 경주 기록(merged.csv)으로 채움")
    ap.add_argument("--force", action="store_true", help="--past 와 함께: 있는 파일도 다시")
    a = ap.parse_args()
    today = dt.datetime.now(KST).strftime("%Y%m%d")
    d = a.date or today
    if (DATA / "entries" / f"{d}.json").exists():
        res = history_results(d)
        if d == today and not res:
            try:
                res = live_results(d)
            except kra_api.ApiError as e:
                print(f"{d}: 당일 결과 받기 실패 {e}")
        o = build(d, res)
        if o and write(d, o):
            ibs = {k: v.get("ib") for k, v in o["races"].items() if "ib" in v}
            print(f"{d}: 끝난 경주 {o['done']}, 안쪽 유리 지수 {ibs}")
    if a.past:
        have = {f.stem for f in OUT.glob("*.json")} if OUT.exists() and not a.force else set()
        for f in sorted((DATA / "entries").glob("*.json")):
            if f.stem in have or f.stem >= today or not (DATA / "pred" / f"{f.stem}.json").exists():
                continue
            o = build(f.stem, history_results(f.stem))
            if o and o["done"]:
                write(f.stem, o)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
