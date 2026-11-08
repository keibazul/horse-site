"""경주 전 단승 배당이 API160_1(pool=WIN)에 실시간으로 바뀌며 올라오는지 확인 (임시): 3분 간격 두 번"""
import sys, time, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kra_api
kst = lambda: dt.datetime.utcnow() + dt.timedelta(hours=9)
d = kst().strftime("%Y%m%d")
snaps = []
for k in range(3):
    rows = kra_api.get_all("API160_1/integratedInfo_1", {"meet": 1, "rc_date": d, "pool": "WIN"}, rows=1000)
    m = {(int(r["rcNo"]), int(r["chulNo"])): r.get("odds") for r in rows}
    snaps.append((kst().strftime("%H:%M:%S"), m))
    print(kst().strftime("%H:%M:%S"), "rows", len(rows), "keys", sorted({k for k in rows[0].keys()}) if rows else None, flush=True)
    if k < 2: time.sleep(150)
races = sorted({r for r, _ in snaps[0][1]})
for r in races:
    a, b, c = (s[1] for s in snaps)
    ch = sum(1 for key in a if key[0] == r and (a.get(key) != b.get(key) or b.get(key) != c.get(key)))
    print(f"R{r}: 바뀐 말 {ch}", {key[1]: (a.get(key), c.get(key)) for key in sorted(a) if key[0] == r})
