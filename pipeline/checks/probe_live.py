"""당일 경주 결과가 경주 중에 공공데이터/홈페이지에 바로 올라오는지 확인 (임시)"""
import sys, datetime as dt, re, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kra_api
d = (dt.datetime.utcnow() + dt.timedelta(hours=9)).strftime("%Y%m%d")
print("KST", (dt.datetime.utcnow() + dt.timedelta(hours=9)).strftime("%H:%M"), d)
for path, params in [("API214_1/RaceDetailResult_1", {"meet": 1, "rc_date": d}),
                     ("API299/Race_Result_total", {"meet": 1, "rc_year": d[:4], "rc_month": d[:6], "rc_date": d}),
                     ("API160_1/integratedInfo_1", {"meet": 1, "rc_date": d, "pool": "WIN"})]:
    try:
        rows = kra_api.get_all(path, params, rows=1000)
        races = sorted({int(r.get("rcNo", 0)) for r in rows if str(r.get("ord", "1")) not in ("0", "")})
        print(path, len(rows), "races with rows", races[:20])
        if rows: print("  sample", {k: rows[0].get(k) for k in ("rcNo", "chulNo", "ord", "sjS1fOrd", "winOdds", "odds")})
    except Exception as e:
        print(path, "ERR", e)
for url in ["https://race.kra.co.kr/raceScore/ScoreRaceInfoList.do?Act=04&Sub=1&meet=1",
            "https://race.kra.co.kr/raceScore/ScoreRaceList.do?Act=04&Sub=1&meet=1",
            "https://race.kra.co.kr/raceFastreport/ScoreRaceInfoList.do?Act=03&Sub=2&meet=1",
            "https://race.kra.co.kr/raceFastreport/ProvisionalRaceResult.do?Act=03&Sub=1&meet=1"]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        h = urllib.request.urlopen(req, timeout=20).read().decode("euc-kr", "replace")
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))
        i = t.find("착순")
        print(url, len(h), "착순@", i, t[max(0, i - 200): i + 600] if i >= 0 else t[:300])
        print("  links", sorted(set(re.findall(r'(?:href|action)="([^"]*(?:Score|Result|Fast)[^"]*)"', h)))[:20])
    except Exception as e:
        print(url, "ERR", e)
