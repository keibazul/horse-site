"""베팅 계획 과거 검증용 경주 속성: work/backtest/race_attrs.json.gz = {날짜: {경주: [거리 m, 그날 마지막 경주면 1]}}
경주성적정보(race_details_all.csv.gz + race_details/rd_*.csv)에서 2016년~. 마지막 경주 = 그날 실제로 치러진(단승 배당이 있는) 경주 중 번호가 가장 큰 것.
planner.js 가 마지막 경주와 1200m 이하 경주를 자동으로 빼므로 plan_backtest.js 가 mkt_win.json.gz 와 함께 읽음.
사용: python work/backtest_race_attrs.py   (work/ 안에서 실행해도 됨)
"""
import glob, gzip, json, os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
use = ["rcDate", "rcNo", "rcDist", "winOdds"]
parts = [pd.read_csv(os.path.join(HERE, "race_details_all.csv.gz"), dtype=str, usecols=use)]
for f in sorted(glob.glob(os.path.join(HERE, "race_details", "rd_*.csv"))):
    parts.append(pd.read_csv(f, dtype=str, usecols=lambda c: c in use))
d = pd.concat(parts, ignore_index=True)
d = d[d["rcDate"] >= "20160101"]
for c in ("rcNo", "rcDist", "winOdds"):
    d[c] = pd.to_numeric(d[c], errors="coerce")
d = d[d["winOdds"] > 0].drop_duplicates(["rcDate", "rcNo"])
last = d.groupby("rcDate")["rcNo"].transform("max")
out = {}
for dt, n, dist, il in zip(d["rcDate"], d["rcNo"].astype(int), d["rcDist"].fillna(0).astype(int), (d["rcNo"] == last).astype(int)):
    out.setdefault(dt, {})[str(n)] = [int(dist), int(il)]
p = os.path.join(HERE, "backtest", "race_attrs.json.gz")
with gzip.open(p, "wt", encoding="utf-8") as fh:
    json.dump(out, fh, separators=(",", ":"))
print(f"{p}: {len(out)}일 {sum(len(v) for v in out.values())}경주, {min(out)}~{max(out)}")
