"""경주 전개 시뮬레이션용 파일 만들기 → sim_날짜_R경주.json
만든 파일은 '경주 시뮬레이터' 페이지의 [경주 파일 열기] 로 엽니다.

사용 예 (PowerShell, 먼저 $env:KRA_API_KEY="발급받은Encoding키")
  # 다가오는 경주 (출전표 API). 배당을 넣으면 우승 확률이 '시장 결합 확률'로 맞춰집니다
  py -3.13 simulate_race.py --date 20261107 --race 5
  py -3.13 simulate_race.py --date 20261107 --race 5 --ask-odds --weather 맑음 --track "건조 (3%)"
  # 지난 경주: 그날 이전 기록만으로 예측하고, 실제 구간 기록도 함께 넣어 비교
  py -3.13 simulate_race.py --date 20261031 --race 7 --backtest

필요: predict_race.py, features_v5.py, race_feature_lib*.py, bet_probs.py, train_sectional_model.py,
      winner_history/win_model_v5.joblib, winner_history/sect_model_v1.joblib, merged.csv, race_details_all.csv.gz
"""
import argparse
import json
import os
import re
import sys

import joblib
import numpy as np
import pandas as pd

import features_v5 as fv
import predict_race as pr
import race_feature_lib as lib
import train_sectional_model as tsm

CORNERS = {"c1": ("se_1cAccTime", "sj_1cOrd", "1코너"), "c2": ("se_2cAccTime", "sj_2cOrd", "2코너"),
           "c3": ("se_3cAccTime", "sj_3cOrd", "3코너"), "c4": ("se_4cAccTime", "sj_4cOrd", "4코너")}
FIXED = {"s1f": ("seS1fAccTime", "sjS1fOrd", "200m", "출발 후 200m"), "g3f": ("seG3fAccTime", "sjG3fOrd", "600m 전", "결승 600m 전"),
         "g1f": ("seG1fAccTime", "sjG1fOrd", "200m 전", "결승 200m 전")}
EXTRA = [v[0] for v in CORNERS.values()] + [v[1] for v in CORNERS.values()] + ["sjS1fOrd", "sjG3fOrd", "sjG1fOrd", "diffUnit", "chulNo", "winOdds", "weather"]


def fixed_dist(key, dist):
    return {"s1f": 200, "g3f": dist - 600, "g1f": dist - 200, "fin": dist}[key]


def corner_positions(sec, date, dist):
    """그 날짜 이전 3년, 같은 거리 경주 기록으로 코너 측정 지점이 출발에서 몇 m 인지 추정"""
    lo = (pd.Timestamp(date) - pd.Timedelta(days=tsm.PAR_DAYS)).strftime("%Y%m%d")
    s = sec[(sec["date"] < date) & (sec["date"] >= lo) & (sec["rcDist"] == dist) & sec["ord"].between(1, 16)]
    s = s[np.logical_and.reduce([s[c] > 0 for c in tsm.SRC.values()])]
    out = {}
    for key, (tc, _, _) in CORNERS.items():
        x = s[s[tc] > 0]
        if len(x) < 50:
            continue
        D = np.array([0, 200, dist - 600, dist - 200, dist], float)
        T = x[["seS1fAccTime", "seG3fAccTime", "seG1fAccTime", "rcTime"]].to_numpy(float)
        d = [np.interp(t, np.r_[0, row], D) for t, row in zip(x[tc].to_numpy(float), T)]
        out[key] = round(float(np.median(d)), 1)
    return out


def main():
    ap = argparse.ArgumentParser(description="경주 전개 시뮬레이션 파일 만들기")
    ap.add_argument("--date", required=True)
    ap.add_argument("--race", type=int, required=True)
    ap.add_argument("--key", default=os.environ.get("KRA_API_KEY"))
    ap.add_argument("--entries-csv")
    ap.add_argument("--scratch", action="append", default=[])
    ap.add_argument("--raceday-csv")
    ap.add_argument("--track", help='당일 주로 상태, 예: "건조 (3%%)"')
    ap.add_argument("--weather", choices=["맑음", "흐림", "비", "눈", "안개"])
    ap.add_argument("--odds-csv")
    ap.add_argument("--ask-odds", action="store_true")
    ap.add_argument("--backtest", action="store_true", help="지난 경주: 그날 이전 기록만으로 예측 + 실제 구간 기록 포함")
    ap.add_argument("--history", default="merged.csv")
    ap.add_argument("--details", default="race_details_all.csv.gz")
    ap.add_argument("--details-dir", default="race_details")
    ap.add_argument("--models-dir", default="winner_history")
    ap.add_argument("--out")
    args = ap.parse_args()
    date, race = args.date, args.race
    if not re.fullmatch(r"\d{8}", date):
        sys.exit("--date 는 YYYYMMDD 형식이어야 합니다")

    win_art = joblib.load(os.path.join(args.models_dir, "win_model_v5.joblib"))
    sect_art = joblib.load(os.path.join(args.models_dir, "sect_model_v1.joblib"))
    history_all = fv.load_history(args.history)
    rd_all = fv.load_details(args.details, args.details_dir)
    sec = tsm.load_sectionals(args.details, args.details_dir, extra=EXTRA)

    # ---- 출전표 ----
    actual = None
    if args.backtest:
        day = history_all[(history_all["date"] == date) & (history_all["race_no"] == race) &
                          (history_all["ord"].between(1, 16) | history_all["ord"].between(91, 92))]
        if day.empty:
            sys.exit(f"{date} {race}경주 기록이 없습니다.")
        entries = pr.normalize_entries(pd.DataFrame({
            "rcNo": day["race_no"], "chulNo": day["chulNo"], "hrNo": day["hrNo"], "hrName": day["hrName"], "jkNo": day["jkNo"],
            "jkName": day["jkName"], "trNo": day["trNo"], "sex": day["sex"], "age": day["age"], "wgBudam": day["wgBudam"], "rank": day["rank"]}))
        d = rd_all[(rd_all["rcDate"] == date)].assign(rcNo=lambda x: pd.to_numeric(x["rcNo"]).astype(int))
        d = d[d["rcNo"] == race]
        for c in ("rcDist", "rating", "wgJk"):
            d[c] = pd.to_numeric(d[c], errors="coerce")
        # 경주 전에 공개되는 정보: 거리·레이팅·감량, 당일 날씨·주로 상태 (마체중은 쓰지 않음)
        entries = entries.drop(columns=["rcDist", "rating", "wgJk", "weather", "track"]).merge(
            d[["rcNo", "hrNo", "rcDist", "rating", "wgJk", "weather", "track"]], on=["rcNo", "hrNo"], how="left")
        odds = d.assign(chulNo=d["chulNo"].astype(str).str.lstrip("0"), winOdds=pd.to_numeric(d["winOdds"], errors="coerce"))[["rcNo", "chulNo", "winOdds"]]
        a = sec[(sec["date"] == date) & (sec["race_no"] == race)].copy()
        actual = a
    else:
        if args.entries_csv:
            entries = pr.normalize_entries(pd.read_csv(args.entries_csv, dtype=str))
        else:
            if not args.key:
                sys.exit("인증키가 필요합니다: --key 또는 환경변수 KRA_API_KEY (또는 --entries-csv)")
            entries = pr.normalize_entries(pr.fetch_entries_api(date, args.key))
        entries = entries[entries["rcNo"] == race]
        odds = None
    entries = pr.apply_scratches(entries[entries["rcNo"] == race], args.scratch)
    entries = pr.add_raceday_info(entries, None if args.backtest else args.raceday_csv, None if args.backtest else args.track, args.weather)
    if entries.empty:
        sys.exit("출전마가 없습니다.")
    if not args.backtest:
        if args.odds_csv:
            odds = pr.read_odds_csv(args.odds_csv)
        elif args.ask_odds:
            odds = pr.ask_odds(entries)
    dist = int(entries["rcDist"].dropna().iloc[0]) if entries["rcDist"].notna().any() else None
    if not dist:
        sys.exit("경주 거리를 알 수 없습니다 (출전표의 rcDist).")

    # ---- 우승 확률 (v5 + 시장 결합) ----
    print("특징 계산 중... (1~3분)", flush=True)
    feat, info = fv.entrant_features(history_all, rd_all, entries, date)
    X = pr.prepare_inputs(feat, win_art["cat_features"])
    p = pr.race_normalize(win_art["model"].predict_proba(X[win_art["features"]])[:, 1], pd.factorize(X["race_no"])[0])
    einfo = entries.rename(columns={"rcNo": "race_no"})[["race_no", "hrNo", "chulNo", "hrName", "jkName", "rcDist", "wgBudam", "age", "sex", "rating"]]
    res = feat[["race_no", "hrNo", "n_prior_races"]].assign(p_model=p).merge(einfo, on=["race_no", "hrNo"])
    res = pr.combine_market(res, odds, *pr.blend_coefs(win_art))

    # ---- 구간 기록 예측 ----
    Xs = pr.prepare_inputs(feat, fv.CAT)
    for k in tsm.KS:
        res[f"d_{k}"] = sect_art["models"][k].predict(Xs[sect_art["features"]])
    b = int(tsm.bucket_of([dist])[0])
    state = None
    tr = entries["track"].dropna()
    if len(tr):
        state = tsm.track_state(tr.iloc[:1]).iloc[0]
    med = tsm.race_medians(sec)
    par = tsm.par_times(med, date, dist, state) or tsm.par_times(med, date, dist)
    if par is None:
        sys.exit(f"{dist}m 기준 시간을 만들 경주가 부족합니다.")
    cps = [{"key": "s1f", "d": 200, "label": "200m", "long": "출발 후 200m"}]
    corner = corner_positions(sec, date, dist)
    for key in ("c1", "c2", "c3", "c4"):
        if key in corner and 200 < corner[key] < dist - 50:
            cps.append({"key": key, "d": corner[key], "label": CORNERS[key][2], "long": CORNERS[key][2]})
    cps += [{"key": "g3f", "d": dist - 600, "label": "600m 전", "long": "결승 600m 전"},
            {"key": "g1f", "d": dist - 200, "label": "200m 전", "long": "결승 200m 전"}]
    cps = sorted([c for c in cps if 0 < c["d"] < dist], key=lambda c: c["d"])

    horses = []
    for _, r in res.sort_values("chulNo", key=lambda s: pd.to_numeric(s)).iterrows():
        h = {"no": int(r["chulNo"]), "name": r["hrName"], "jk": r["jkName"], "wt": None if pd.isna(r["wgBudam"]) else float(r["wgBudam"]),
             "age": None if pd.isna(r["age"]) else int(r["age"]), "sex": r["sex"], "rating": None if pd.isna(r["rating"]) else int(r["rating"]),
             "nPrior": int(r["n_prior_races"]), "debut": int(r["n_prior_races"] == 0),
             "pModel": round(float(r["p_model"]), 4), "pComb": None if pd.isna(r["p_comb"]) else round(float(r["p_comb"]), 4),
             "odds": None if pd.isna(r["winOdds"]) else float(r["winOdds"]), "qMkt": None if pd.isna(r["q_market"]) else round(float(r["q_market"]), 4),
             "pred": {k: round(float(r[f"d_{k}"]), 3) for k in tsm.KS}}
        if actual is not None:
            a = actual[actual["hrNo"] == r["hrNo"]]
            if len(a):
                a = a.iloc[0]
                cp = {}
                for c in cps:
                    tc, oc = (FIXED[c["key"]][:2] if c["key"] in FIXED else CORNERS[c["key"]][:2])
                    if a[tc] > 0:
                        cp[c["key"]] = [int(a[oc]), float(a[tc])]
                h["actual"] = {"ord": int(a["ord"]), "diff": str(a["diffUnit"]), "rc": float(a["rcTime"]), "cp": cp}
        horses.append(h)
    meta_r = entries.iloc[0]
    out = {"version": 1, "date": date, "race": race, "dist": dist, "track": None if not len(tr) else str(tr.iloc[0]),
           "weather": args.weather or (None if actual is None or actual["weather"].isna().all() else str(actual["weather"].dropna().iloc[0])),
           "rank": None if pd.isna(meta_r.get("rank")) else str(meta_r.get("rank")), "n": len(horses),
           "target": "comb" if res["p_comb"].notna().all() else "model", "par": {k: round(v, 2) for k, v in par.items()},
           "cps": cps, "pools": {"0": sect_art["pools"][f"{b}0"].tolist(), "1": sect_art["pools"][f"{b}1"].tolist()},
           "pace": sect_art["pace"].get(str(b), np.ones((1, 4))).tolist(), "horses": horses,
           "hasActual": actual is not None and all("actual" in h for h in horses),
           "notes": {"toolsGuessed": info["tools_guessed"], "birthdayGuessed": info["birthday_guessed"], "oddsFinal": bool(args.backtest)}}
    if actual is not None:
        out["track"] = str(actual["track"].dropna().iloc[0]) if actual["track"].notna().any() else out["track"]
    path = args.out or f"sim_{date}_R{race}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    lead = res.sort_values("d_s1f").iloc[0]
    top = res.sort_values("p_win", ascending=False).iloc[0]
    print(f"저장: {path}  ({dist}m, {len(horses)}두, 우승 확률 기준: {'시장 결합' if out['target'] == 'comb' else '모델만'})")
    print(f"  초반 선두 예상: {int(lead['chulNo'])}번 {lead['hrName']} | 우승 확률 1위: {int(top['chulNo'])}번 {top['hrName']} ({top['p_win'] * 100:.1f}%)")
    print("  '경주 시뮬레이터' 페이지에서 [경주 파일 열기] 로 이 파일을 여세요.")


if __name__ == "__main__":
    main()
