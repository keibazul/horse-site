"""임시 확인 (끝나면 지움)"""
import html, json, os, re, sys, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import kra_api
UA = {"User-Agent": "Mozilla/5.0"}
for i in ("15144727", "15133770", "15140265"):
    s = urllib.request.urlopen(urllib.request.Request(f"https://www.data.go.kr/en/data/{i}/openapi.do", headers=UA), timeout=40).read().decode("utf-8", "replace")
    k = s.find("B551015/API")
    txt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s[max(0, k - 3000):k + 6000])))
    print(i, txt[:3500]); print("-----")
for d, rn, ch in (("DATE1", 0, 0),):
    pass
for d, pairs in (("20261031", [(5, 5), (8, 4)]), ("20261025", [(7, 1)])):
    try:
        e = kra_api.get_all("API26_2/entrySheet_2", {"meet": 1, "rc_date": d})
        print(d, "API26_2 rows", len(e), [(r.get("rcNo"), r.get("chulNo"), r.get("hrName"), r.get("jkName")) for r in e if (int(r.get("rcNo") or 0), int(r.get("chulNo") or 0)) in pairs])
        print("   per race counts", {n: sum(1 for r in e if int(r.get("rcNo") or 0) == n) for n, _ in pairs})
    except Exception as ex:
        print(d, "API26_2 ERR", ex)
    try:
        x = kra_api.get_all("API214_1/RaceDetailResult_1", {"meet": 1, "rc_date": d}, rows=1000)
        print(d, "API214 rows", len(x), [(r.get("rcNo"), r.get("chulNo"), r.get("hrName"), r.get("ord"), r.get("ordBigo")) for r in x if (int(r.get("rcNo") or 0), int(r.get("chulNo") or 0)) in pairs])
        print("   per race counts", {n: sum(1 for r in x if int(r.get("rcNo") or 0) == n) for n, _ in pairs})
    except Exception as ex:
        print(d, "API214 ERR", ex)
