"""임시 확인: 조교·기수변경 API 주소와 현재 키로 열리는지 (끝나면 지움)"""
import json, os, re, sys, urllib.request, urllib.parse, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import kra_api

UA = {"User-Agent": "Mozilla/5.0"}
def page(i):
    for u in (f"https://www.data.go.kr/data/{i}/openapi.do", f"https://www.data.go.kr/en/data/{i}/openapi.do"):
        try:
            s = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=40).read().decode("utf-8", "replace")
        except Exception as e:
            print(i, u, "실패", type(e).__name__, e); continue
        hits = sorted(set(re.findall(r"B551015/(API\d+[\w]*/[A-Za-z_0-9]+)", s)))
        print(i, u, len(s), "paths:", hits)
        for m in re.finditer(r'"parameters"\s*:\s*(\[.*?\])\s*,\s*"responses"', s, re.S):
            try:
                ps = json.loads(m.group(1)); print("   params:", [(p.get("name"), p.get("required"), p.get("description"), p.get("x-example") or p.get("example")) for p in ps])
            except Exception:
                print("   params raw:", m.group(1)[:600])
        for m in re.finditer(r"(?:paths|operationId)[^\n]{0,300}", s):
            pass
        if hits: return hits
    return []

paths = {}
for i in ("15144727", "15133770", "15140265", "15160316"):
    paths[i] = page(i)

def call(path, params):
    try:
        d = kra_api.get(path, {**params, "pageNo": 1, "numOfRows": 5})
        it = kra_api.items(d)
        print("  OK", path, params, "total", kra_api.total_count(d), "first:", json.dumps(it[:2], ensure_ascii=False)[:900])
        return d
    except Exception as e:
        print("  ERR", path, params, type(e).__name__, str(e)[:200]); return None

for p in paths.get("15144727", []):
    call(p, {})
    for prm in ({"exer_dt": "20261104"}, {"exer_st_dt": "20261101", "exer_ed_dt": "20261107"}, {"st_dt": "20261101", "ed_dt": "20261107"}, {"exer_dt": "20190104"}):
        call(p, prm)
for p in paths.get("15133770", []):
    call(p, {}); call(p, {"race_dt": "20261107"}); call(p, {"race_dt": "20261107", "gb": "1"}); call(p, {"race_dt": "20261107", "gb": "2"}); call(p, {"race_dt": "20190105"})
for p in paths.get("15140265", []):
    call(p, {}); call(p, {"trng_dt": "20261030"}); call(p, {"trng_dt": "20190104"})
