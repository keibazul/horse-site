"""경주 당일 마체중 받기 (KRA 경마 홈페이지 '출전마체중') → site/data/weights/날짜.json

마체중은 경주일 아침부터 경주마다 차례로 입력된다. 목록 페이지에서 '입력완료'인 경주만 골라
경주별 상세(POST /raceFastreport/ChuljumaWeightList.do)를 받는다. 이미 받은 경주는 다시 받지 않는다.
요청 사이에 쉬어 사이트에 부담을 주지 않는다 (한 번 실행에 많아야 경주 수 + 1번).

사용: python pipeline/fetch_weights.py --date 20261107 [--all]   (--all: 입력여부와 상관없이 모든 경주, 지난 날 확인용)
결과: {"date", "fetched", "races": {"1": {"3": {"kg": 510, "chg": 7, "hrNo": "1412323", "note": "-"}, ...}}}
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site" / "data" / "weights"
BASE = "https://race.kra.co.kr"
UA = {"User-Agent": "Mozilla/5.0 (horse-site; personal research; weekly race-day updates)"}
KST = dt.timezone(dt.timedelta(hours=9))


def get(url: str, data: dict | None = None, tries: int = 3) -> str:
    body = urllib.parse.urlencode(data).encode() if data else None
    for k in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers=UA)
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("euc-kr", "replace")
        except Exception:
            if k + 1 == tries:
                raise
            time.sleep(5 * (k + 1))


def list_status(date: str) -> dict[int, bool]:
    """목록 페이지: 그날 서울 경주별 입력 완료 여부"""
    s = get(f"{BASE}/thisweekrace/ThisWeekWeight.do?Act=04&Sub=2&meet=1")
    out = {}
    for row in re.findall(r"<tr>(.*?)</tr>", s, re.S):
        m = re.search(r'goDetail\("(\d+)","(\d{8})","1"\)', row)
        if m and m.group(2) == date:
            out[int(m.group(1))] = "입력완료" in row
    return out


def _cells(row: str) -> list[str]:
    return [html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]


def race_weights(date: str, rc_no: int) -> dict[str, dict]:
    s = get(f"{BASE}/raceFastreport/ChuljumaWeightList.do", {"rcNo": rc_no, "date": date, "meet": 1, "Act": "03", "Sub": "4"})
    t = re.search(r"금일출전마체중.*?<tbody>(.*?)(?:</tbody>|$)", s, re.S)
    if not t:
        return {}
    out = {}
    for row in re.findall(r"<tr>(.*?)</tr>", t.group(1), re.S):
        c = _cells(row)
        hr = re.search(r"goHorse\('(\d+)'", row)
        if len(c) < 4 or not c[0].isdigit():
            continue
        try:
            kg, chg = int(c[2] or 0), int(c[3] or 0)
        except ValueError:
            continue
        if kg <= 0:                      # 아직 입력 전
            continue
        out[c[0]] = {"kg": kg, "chg": chg, "hrNo": hr.group(1) if hr else None, "note": c[9] if len(c) > 9 else ""}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.datetime.now(KST).strftime("%Y%m%d"))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--races", help="경주 번호들 (--all 과 함께, 예: 1,2,3)")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f"{a.date}.json"
    saved = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"date": a.date, "races": {}}
    try:
        if a.all:
            todo = [int(x) for x in a.races.split(",")] if a.races else list(range(1, 16))
        else:
            st = list_status(a.date)
            if not st:
                print(f"{a.date}: 출전마체중 목록에 이 날 서울 경주가 없습니다")
                return 0
            done = [n for n, ok in st.items() if ok]
            todo = [n for n in done if len(saved["races"].get(str(n), {})) == 0]
            print(f"{a.date}: 입력완료 {len(done)}/{len(st)}경주, 새로 받을 경주 {todo}")
        for n in todo:
            time.sleep(1.0)
            w = race_weights(a.date, n)
            if not w and a.all and n > 12:
                break
            if w:
                saved["races"][str(n)] = w
                print(f"  {n}경주 {len(w)}두: " + ", ".join(f"{k}번 {v['kg']}({v['chg']:+d})" for k, v in list(w.items())[:4]) + " …")
                save(f, saved)                       # 경주마다 저장 (중간에 끊겨도 받은 만큼은 남김)
    except Exception as e:      # 홈페이지가 안 열려도 나머지 업데이트는 계속
        print(f"마체중 받기 실패 (받은 경주 {len(saved['races'])}개는 저장): {type(e).__name__}: {e}")
    return 0


def save(f: Path, saved: dict) -> None:
    saved["fetched"] = dt.datetime.now(KST).isoformat(timespec="minutes")
    f.write_text(json.dumps(saved, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
