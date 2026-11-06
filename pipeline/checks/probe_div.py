"""API160_1 확정배당 응답 모양 확인용 (임시)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kra_api
P = "API160_1/integratedInfo_1"
for params in [{"meet": 1, "rc_date": "20261101"},
               {"meet": 1, "rc_date": "20261101", "pool": "단승식"},
               {"meet": 1, "rc_date": "20261101", "pool": "WIN"},
               {"meet": 1, "rc_date": "20261101", "pool": "1"},
               {"meet": 1, "rc_date": "20261101", "rc_no": 7},
               {"meet": 1, "rc_date": "202611"}]:
    try:
        d = kra_api.get(P, {**params, "pageNo": 1, "numOfRows": 5})
        b = d.get("response", {}).get("body", {})
        it = b.get("items")
        it = (it or {}).get("item") if isinstance(it, dict) else it
        print(params, "total", b.get("totalCount"))
        print(json.dumps(it if isinstance(it, list) else [it], ensure_ascii=False)[:1500])
    except Exception as e:
        print(params, "ERR", e)
