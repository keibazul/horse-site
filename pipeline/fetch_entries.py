"""앞으로 열릴 서울 경주 출전표(API26_2/entrySheet_2)를 받아 site/data/entries/날짜.json 으로 저장.

사용: python pipeline/fetch_entries.py [--days 8] [--date YYYYMMDD]
오늘(한국 시간)부터 --days 일 안의 날짜를 하나씩 조회해서 출전표가 있는 날만 저장한다.
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
OUT = ROOT / "site" / "data" / "entries"
KST = dt.timezone(dt.timedelta(hours=9))


def today_kst() -> dt.date:
    return dt.datetime.now(KST).date()


def fetch_day(d: str) -> list[dict]:
    rows = kra_api.get_all("API26_2/entrySheet_2", {"meet": 1, "rc_date": d})
    rows = [r for r in rows if str(r.get("rcDate", d)).replace("-", "")[:8] == d and str(r.get("meet", "서울")) in ("1", "서울")]
    return rows


def jockey_changes(old: dict, rows: list[dict], at: str) -> dict:
    """출전표가 처음 나온 뒤 기수가 바뀐 말: {"경주-번호": {"jk": [처음 기수, 지금 기수], "wg": [처음 부담중량, 지금], "at": 알게 된 시각}}
    출전표 API 는 기수가 바뀌면 새 기수·부담중량으로 고쳐 주므로(예측은 새 기수로 다시 계산됨) 처음 값을 여기 남겨 사이트에 표시"""
    chg = dict(old.get("chg") or {})
    prev = {(str(r.get("rcNo")), str(r.get("chulNo"))): r for r in old.get("rows") or []}
    for r in rows:
        k = (str(r.get("rcNo")), str(r.get("chulNo")))
        o, key = prev.get(k), f"{k[0]}-{k[1]}"
        if not o or str(o.get("hrNo")) != str(r.get("hrNo")):
            chg.pop(key, None)                    # 말이 바뀐 자리(출전표 재편성)는 기록하지 않음
            continue
        if str(o.get("jkNo")) == str(r.get("jkNo")):
            continue
        first = chg.get(key, {"jk": [o.get("jkName")], "wg": [o.get("wgBudam")], "no": str(o.get("jkNo"))})
        if first.get("no") == str(r.get("jkNo")):
            chg.pop(key, None)                    # 처음 기수로 되돌아옴
        else:
            chg[key] = {"jk": [first["jk"][0], r.get("jkName")], "wg": [first["wg"][0], r.get("wgBudam")], "no": first.get("no"), "at": at}
    return chg


def clean(v):
    if isinstance(v, str):
        v = v.strip()
    return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=8)
    ap.add_argument("--date", help="한 날짜만 (YYYYMMDD)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    dates = [a.date] if a.date else [(today_kst() + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range(a.days)]
    found = []
    for d in dates:
        try:
            rows = fetch_day(d)
        except kra_api.ApiError as e:
            print(f"{d}: 출전표 조회 실패 → {e}")
            continue
        if not rows:
            print(f"{d}: 출전표 없음")
            continue
        rows = [{k: clean(v) for k, v in r.items()} for r in rows]
        rows.sort(key=lambda r: (int(r.get("rcNo") or 0), int(r.get("chulNo") or 0)))
        races = sorted({int(r["rcNo"]) for r in rows})
        print(f"{d}: {len(races)}개 경주, {len(rows)}두 (항목 {len(rows[0])}개)")
        found.append(d)
        f = OUT / f"{d}.json"
        old = {}
        try:
            old = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
            if old.get("rows") == rows:
                continue          # 내용이 같으면 파일을 그대로 둠 (시각만 바뀐 커밋·배포를 만들지 않음)
        except ValueError:
            pass
        now = dt.datetime.now(KST)
        obj = {"date": d, "fetched": now.isoformat(timespec="minutes"), "rows": rows}
        chg = jockey_changes(old, rows, now.strftime("%m-%d %H:%M"))
        if chg:
            obj["chg"] = chg
        f.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    print("출전표 저장:", ", ".join(found) if found else "없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
