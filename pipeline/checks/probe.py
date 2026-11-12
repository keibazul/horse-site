"""임시 확인: 신청한 API 가 열리는지 (끝나면 지움)"""
import html, json, os, re, sys, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import kra_api
UA = {"User-Agent": "Mozilla/5.0"}
for i in ("15144727", "15133770", "15140265"):
    s = urllib.request.urlopen(urllib.request.Request(f"https://www.data.go.kr/en/data/{i}/openapi.do", headers=UA), timeout=40).read().decode("utf-8", "replace")
    txt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s)))
    a = txt.find("Request Parameter"); b = txt.find("Sample Data", a)
    print(i, txt[a:a + 2500]); print("-----")
def call(path, params):
    try:
        d = kra_api.get(path, {**params, "pageNo": 1, "numOfRows": 10})
        it = kra_api.items(d)
        print("  OK", path, params, "total", kra_api.total_count(d), "rows", len(it))
        for r in it[:3]: print("     ", json.dumps(r, ensure_ascii=False)[:700])
    except Exception as e:
        print("  ERR", path, params, type(e).__name__, str(e)[:200])
P338, P320, P329 = "API338/textDataSeDalyExer", "API320/textDataHoldSeChgInfo", "API329/textDataSeGtscol"
for p in (P338, P320, P329):
    call(p, {})
for prm in ({"exer_dt": "20261108"}, {"exer_dt": "20261110"}, {"trng_dt": "20261110"}, {"dt": "20261110"}, {"exer_dt": "20190104"}, {"exer_dt": "20120104"}):
    call(P338, prm)
for prm in ({"rc_date": "20261108"}, {"race_dt": "20261108"}, {"rc_date": "20261031"}, {"rc_date": "20190105"}, {"meet": "1"}):
    call(P320, prm)
