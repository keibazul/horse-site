"""베팅 계획 과거 검증용 자료 → work/backtest/mkt_win.json.gz
연도별 표본외 배당 반영 확률(그 전 해까지 학습한 mkt 모델, 2016~2026)과 확정 단승 배당·1착.
만드는 법: 연도별 모델 예측(mkt_oos.pkl, train_mkt_model.py 와 같은 설정으로 해마다 학습)을 경주·번호로 정리.
사용: python backtest_mkt_data.py 경로/mkt_oos.pkl"""
import glob, gzip, json, sys
import pandas as pd
import race_feature_lib as lib

o = pd.read_pickle(sys.argv[1])
cols = ["rcDate", "rcNo", "chulNo", "hrNo", "ord"]
rd = pd.concat([pd.read_csv("race_details_all.csv.gz", dtype=str, usecols=cols)] + [pd.read_csv(f, dtype=str, usecols=cols) for f in sorted(glob.glob("race_details/rd_*.csv"))]).drop_duplicates(["rcDate", "rcNo", "hrNo"], keep="last")
rd["hrNo"] = lib.normalize_id(rd["hrNo"]); rd["rid"] = rd["rcDate"] + "_" + pd.to_numeric(rd["rcNo"]).astype(int).astype(str); rd["chulNo"] = pd.to_numeric(rd["chulNo"]).astype(int)
o["hrNo"] = lib.normalize_id(o["hrNo"].astype(str))
o = o.merge(rd[["rid", "hrNo", "chulNo"]], on=["rid", "hrNo"], how="left").dropna(subset=["chulNo"])
days: dict = {}
for rid, g in o.groupby("rid"):
    d, n = rid.split("_")
    w = g[g["is_win"] == 1]["chulNo"]
    days.setdefault(d, {})[n] = {"p": {str(int(c)): round(float(v), 6) for c, v in zip(g["chulNo"], g["pA"])},
                                 "odds": {str(int(c)): float(v) for c, v in zip(g["chulNo"], g["winOdds"])}, "win": int(w.iloc[0]) if len(w) else None}
with gzip.open("backtest/mkt_win.json.gz", "wt", encoding="utf-8") as fh:
    json.dump(days, fh, separators=(",", ":"))
print("경주일", len(days), "경주", sum(len(v) for v in days.values()))
