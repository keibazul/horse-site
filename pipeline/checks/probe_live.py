"""당일 경주 결과가 얼마나 빨리 올라오는지 (임시): API299 경주결과종합, API214 경주성적정보, 홈페이지 경주속보"""
import sys, re, datetime as dt, urllib.request, urllib.parse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kra_api
kst = dt.datetime.utcnow() + dt.timedelta(hours=9); d = kst.strftime("%Y%m%d")
print("KST", kst.strftime("%H:%M:%S"))
for path, params in [("API299/Race_Result_total", {"meet": 1, "rc_date": d}),
                     ("API299/Race_Result_total", {"meet": 1, "rc_year": d[:4], "rc_month": d[:6], "rc_date": d}),
                     ("API214_1/RaceDetailResult_1", {"meet": 1, "rc_date": d})]:
    try:
        rows = kra_api.get_all(path, params, rows=1000)
        done = sorted({int(r.get("rcNo") or r.get("rc_no") or 0) for r in rows if str(r.get("ord") or r.get("rcOrd") or "0") not in ("0", "")})
        print(path, list(params), "rows", len(rows), "races", done)
        if rows: print("  keys", sorted(rows[0].keys())[:60])
        last = [r for r in rows if int(r.get("rcNo") or r.get("rc_no") or 0) == (done[-1] if done else 0)]
        print("  last race", [(r.get("chulNo") or r.get("chul_no"), r.get("ord"), r.get("hrName")) for r in last][:5])
    except Exception as e:
        print(path, "ERR", e)
def get(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://race.kra.co.kr/"})
    return urllib.request.urlopen(req, timeout=20).read().decode("euc-kr", "replace")
for url in ["https://race.kra.co.kr/raceFastreport/ScoreRaceList.do?Act=03&Sub=1&meet=1",
            "https://race.kra.co.kr/raceFastreport/ScoreRaceInfoList.do?Act=03&Sub=1&meet=1",
            "https://race.kra.co.kr/raceFastreport/RaceResultList.do?Act=03&Sub=1&meet=1",
            "https://race.kra.co.kr/raceFastreport/ThisWeekResult.do?Act=03&Sub=1&meet=1",
            "https://race.kra.co.kr/raceFastreport/ChuljumaWeightList.do?Act=03&Sub=4&meet=1",
            "https://race.kra.co.kr/raceScore/ScoretableDetailList.do?Act=04&Sub=1&meet=1&realRcDate=" + d + "&realRcNo=10"]:
    try:
        h = get(url)
        links = sorted(set(re.findall(r'(?:href|action|src)\s*=\s*["\']([^"\']*(?:Fast|Score|Result|result)[^"\']*)', h)))
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", " ", h, flags=re.S)))
        i = max(t.find("착순"), t.find("순위"))
        print("\n", url, len(h), "|", t[max(0, i - 150): i + 500] if i >= 0 else t[:200])
        print("  links", links[:25])
        js = sorted(set(re.findall(r"(go\w+\([^)]*\))", h)))[:10]; print("  js", js)
    except Exception as e:
        print(url, "ERR", e)
