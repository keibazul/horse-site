"""임시 확인: 일별 조교 기록이 얼마나 오래전까지 있는지, 기수변경·말취소 예 (끝나면 지움)"""
import json, os, sys, collections
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import kra_api
def call(path, params, n=3, rows=10):
    try:
        d = kra_api.get(path, {**params, "pageNo": 1, "numOfRows": rows}); it = kra_api.items(d)
        print("  OK", params, "total", kra_api.total_count(d), "rows", len(it))
        for r in it[:n]: print("     ", json.dumps(r, ensure_ascii=False)[:400])
        return it
    except Exception as e:
        print("  ERR", params, type(e).__name__, str(e)[:200]); return []
P338, P320 = "API338/textDataSeDalyExer", "API320/textDataHoldSeChgInfo"
for a, b in (("20261105", "20261111"), ("20260101", "20260107"), ("20250102", "20250108"), ("20230104", "20230110"), ("20210106", "20210112"), ("20190102", "20190108"), ("20150107", "20150113"), ("20120104", "20120110")):
    call(P338, {"exer_stdt": a, "exer_spdt": b}, n=1)
it = call(P338, {"exer_stdt": "20261101", "exer_spdt": "20261111"}, n=0, rows=1000)
print("  11/1~11/11 날짜별", sorted(collections.Counter(r.get("exerDt") for r in it).items()))
print("  remkTxt", collections.Counter(r.get("remkTxt") for r in it).most_common(12), "ridr", collections.Counter(r.get("ridr") for r in it).most_common(8), "belo", collections.Counter(r.get("belo") for r in it).most_common(5))
print("  exerTm", collections.Counter(r.get("exerTm") for r in it).most_common(15))
call(P338, {"hr_name": "벌교의스타", "exer_stdt": "20261001", "exer_spdt": "20261111"}, n=12, rows=100)
for d in ("20261108", "20261107", "20261101", "20261031", "20261025", "20261019", "20260104", "20250105", "20230107", "20190105"):
    call(P320, {"race_dt": d}, n=6, rows=100)
call(P320, {"race_dt": "20261031", "gb": "1"}, n=6, rows=100)
