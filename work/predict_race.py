"""앞으로 열릴 서울 경마 경주의 우승 확률을 예측합니다 (v5 모델 + 시장 배당 결합).

사용 예 (PowerShell, 먼저 $env:KRA_API_KEY="발급받은Encoding키")
  # 1) 출전표 API로 그날 전체 경주 예측 (배당 없이 = 모델 확률만)
  py -3.13 predict_race.py --date 20261107
     → 배당 입력용 odds_input_20261107.csv 도 만들어 줍니다

  # 2) 경주 직전 단승 배당을 넣어 '결합 확률'로 예측 (가장 정확)
  py -3.13 predict_race.py --date 20261107 --race 5 --ask-odds          (화면에서 배당을 직접 입력)
  py -3.13 predict_race.py --date 20261107 --odds-csv odds_input_20261107.csv   (CSV의 winOdds 칸을 채운 뒤)

  # 3) 출전 취소마 빼기, 당일 마체중·주로·날씨 넣기
  py -3.13 predict_race.py --date 20261107 --race 5 --scratch 5:3 --raceday-csv raceday.csv --track "건조 (3%)" --weather 맑음

  # 4) 과거 날짜로 연습: 그 날 이전 기록만으로 예측하고 실제 결과·확정 배당과 함께 표시
  py -3.13 predict_race.py --date 20261031 --backtest

필요한 파일: merged.csv, race_details_all.csv.gz(+ race_details/rd_*.csv), winner_history/win_model_v5.joblib,
             features_v5.py, race_feature_lib.py, race_feature_lib_v4.py, race_feature_lib_v5.py, bet_probs.py
예전 모델(v2·v3 섞은 blend)은 --model blend 로 쓸 수 있습니다.
"""
import argparse
import json
import os
import re
import sys

import joblib
import numpy as np
import pandas as pd
import requests

import bet_probs as bp
import race_feature_lib as lib

# 승식 확률 계산에 쓰는 2·3착 강도 조정값 (bet_probs.py 설명 참고).
BET_LAMBDA2, BET_LAMBDA3 = 0.8, 0.7
BET_SAVE_TOP = 20     # 승식마다 CSV에 저장할 조합 수

API_URL = "https://apis.data.go.kr/B551015/API26_2/entrySheet_2"   # 한국마사회 출전표 상세정보

# 출전표 응답 항목 이름이 달라도 찾을 수 있도록 후보 이름을 적어 둠
ALIASES = {
    "rcNo": ["rcNo", "raceNo", "race_no"],
    "chulNo": ["chulNo", "gtno", "pthrNo"],
    "hrNo": ["hrNo", "hrno"],
    "hrName": ["hrName", "hrnm"],
    "jkNo": ["jkNo", "jckyNo"],
    "jkName": ["jkName", "jckyNm"],
    "trNo": ["trNo", "trarNo"],
    "trName": ["trName", "trarNm"],
    "sex": ["sex", "gndr", "gndrNm"],
    "age": ["age", "ag", "hrsAg"],
    "wgBudam": ["wgBudam", "burdWgt"],
    "rank": ["rank", "rcRank", "gun"],
    "rcDist": ["rcDist", "dist"],
    "rating": ["rating"],
    "wgJk": ["wgJk"],
    "wgHr": ["wgHr"],
    "track": ["track"],
    "hrTool": ["hrTool"],
    "weather": ["weather"],
    "stTime": ["stTime"],
}
REQUIRED = ["rcNo", "chulNo", "hrNo", "jkNo", "trNo", "wgBudam", "age", "sex"]
EV_NOTE = ("※ 기대값 = 결합 확률 × 단승 배당. 1을 넘어도 수익이 보장되지 않습니다: 2009~2026년 표본외 검증에서 "
           "기대값 1 이상 단승은 333번뿐이었고 회수율 95% 구간이 62~319%로 넓으며, 큰 배당 5경주를 빼면 49%였습니다.")


# =====================================================
# 출전표 가져오기 / 정리
# =====================================================
def fetch_entries_api(date, key, show_raw=False):
    """출전표 API에서 그날 전체 경주의 출전마를 받아옴 (경주번호 없이 날짜만으로 한 번에)"""
    rows, page = [], 1
    while True:
        url = f"{API_URL}?serviceKey={key}&pageNo={page}&numOfRows=300&meet=1&rc_date={date}&_type=json"
        res = requests.get(url, timeout=30)
        res.raise_for_status()
        try:
            data = res.json()
        except ValueError:
            raise RuntimeError(f"API 응답이 JSON이 아닙니다 (인증키/활용신청을 확인하세요): {res.text[:200]}")
        resp = data.get("response", data)
        header = resp.get("header", {})
        if show_raw:
            print(f"[{page}페이지] resultCode={header.get('resultCode')} resultMsg={header.get('resultMsg')} "
                  f"totalCount={resp.get('body', {}).get('totalCount')}")
        if str(header.get("resultCode", "00")) not in ("00", "03"):
            raise RuntimeError(f"API 오류 {header.get('resultCode')}: {header.get('resultMsg')}")
        body = resp.get("body", {})
        items = body.get("items")
        if not items:
            break
        item = items["item"] if isinstance(items, dict) else items
        rows += [item] if isinstance(item, dict) else list(item)
        if len(rows) >= int(body.get("totalCount", 0)) or page >= 10:
            break
        page += 1
    df = pd.DataFrame(rows)
    if show_raw:
        if len(df):
            raw_path = f"entries_raw_{date}.csv"
            df.to_csv(raw_path, index=False, encoding="utf-8-sig")
            print(f"받은 행 수: {len(df)} (원본 그대로 {raw_path} 에 저장)")
            print("응답 항목:", list(df.columns))
            print(df.head(2).T.to_string())
        else:
            print(f"{date} 출전표가 비어 있습니다. 경마가 없는 날이거나 아직 출전표가 나오지 않은 날일 수 있어요.")
    for c in df.columns:
        if c.lower() in ("rcdate", "racedt"):
            df = df[df[c].astype(str).str.replace("-", "") == date]
    return df


def normalize_entries(df):
    """API/CSV 표를 이 프로그램이 쓰는 이름과 형식으로 정리"""
    cols = {c.lower(): c for c in df.columns}
    out = pd.DataFrame(index=df.index)
    for std, names in ALIASES.items():
        for n in names:
            if n.lower() in cols:
                out[std] = df[cols[n.lower()]]
                break
    missing = [c for c in REQUIRED if c not in out.columns]
    if missing:
        raise ValueError(f"출전표에서 필요한 항목을 찾지 못했습니다: {missing}\n응답에 있는 항목: {list(df.columns)}\n"
                         f"predict_race.py 위쪽의 ALIASES 에 맞는 이름을 추가해 주세요 (--show-raw 로 항목 이름을 볼 수 있습니다)")
    for c in ("hrName", "jkName", "trName", "rank", "wgHr", "track", "hrTool", "weather", "stTime"):
        if c not in out.columns:
            out[c] = None
    for c in ("rcDist", "rating", "wgJk"):
        if c not in out.columns:
            out[c] = np.nan
    # 기수명 앞의 '(-2)' 는 견습기수 감량 → wgJk (출전표에는 따로 없음)
    jk = out["jkName"].astype(str)
    allow = pd.to_numeric(jk.str.extract(r"^\s*\((-?\d+)\)")[0], errors="coerce")
    out["wgJk"] = pd.to_numeric(out["wgJk"], errors="coerce").fillna(allow).fillna(0.0)
    out["jkName"] = out["jkName"].where(out["jkName"].isna(), jk.str.replace(r"^\s*\(-?\d+\)\s*", "", regex=True))
    out["rcNo"] = out["rcNo"].astype(str).str.extract(r"(\d+)")[0].astype(int)
    out["chulNo"] = out["chulNo"].astype(str).str.extract(r"(\d+)")[0]
    out["age"] = pd.to_numeric(out["age"].astype(str).str.extract(r"(\d+)")[0])
    out["wgBudam"] = pd.to_numeric(out["wgBudam"].astype(str).str.replace(r"[^0-9.]", "", regex=True), errors="coerce")
    out["rcDist"] = pd.to_numeric(out["rcDist"], errors="coerce")
    out["rating"] = pd.to_numeric(out["rating"], errors="coerce")       # '-' → 빈칸
    for c in ("hrNo", "jkNo", "trNo"):
        out[c] = lib.normalize_id(out[c].astype(str).where(out[c].notna()))
    out["sex"] = out["sex"].astype(str).str.strip()
    out = out[out["hrNo"].notna() & out["chulNo"].notna()].drop_duplicates(["rcNo", "hrNo"])
    return out.reset_index(drop=True)


def apply_scratches(entries, scratches):
    for s in scratches:
        m = re.fullmatch(r"(\d+):(\d+)", s.strip())
        if not m:
            sys.exit(f"--scratch 형식이 올바르지 않습니다: '{s}' (예: 5:3 = 5경주 3번)")
        race, num = int(m.group(1)), m.group(2).lstrip("0")
        hit = (entries["rcNo"] == race) & (entries["chulNo"].str.lstrip("0") == num)
        print(f"출전 제외: {race}경주 {num}번 ({int(hit.sum())}두)")
        entries = entries[~hit]
    return entries.reset_index(drop=True)


def add_raceday_info(entries, raceday_csv, track, weather):
    """당일 정보 입력. raceday.csv 열: rcNo, chulNo, wgHr(예: 441(-9)), [track], [hrTool(예: 망사+,계란형큰)]"""
    if raceday_csv:
        rd = pd.read_csv(raceday_csv, dtype=str)
        rd["rcNo"] = rd["rcNo"].astype(int)
        rd["chulNo"] = rd["chulNo"].str.lstrip("0")
        cols = ["rcNo", "chulNo"] + [c for c in ("wgHr", "track", "hrTool") if c in rd.columns]
        e = entries.assign(_k=entries["chulNo"].str.lstrip("0"))
        e = e.drop(columns=[c for c in cols[2:] if c in e.columns]).merge(
            rd[cols].rename(columns={"chulNo": "_k"}), on=["rcNo", "_k"], how="left").drop(columns="_k")
        entries = e
    if track:
        entries["track"] = entries["track"].fillna(track) if "track" in entries else track
    if weather:
        entries["weather"] = weather
    return entries


# =====================================================
# 배당 입력 / 시장 결합
# =====================================================
def read_odds_csv(path):
    o = pd.read_csv(path, dtype=str)
    need = {"rcNo", "chulNo", "winOdds"}
    if not need <= set(o.columns):
        sys.exit(f"{path} 에 rcNo, chulNo, winOdds 열이 필요합니다")
    o = o.assign(rcNo=pd.to_numeric(o["rcNo"]).astype(int), chulNo=o["chulNo"].str.lstrip("0"),
                 winOdds=pd.to_numeric(o["winOdds"], errors="coerce"))
    return o[["rcNo", "chulNo", "winOdds"]]


def ask_odds(entries):
    rows = []
    for race, g in entries.groupby("rcNo"):
        g = g.assign(n=pd.to_numeric(g["chulNo"])).sort_values("n")
        print(f"\n[{race}경주 단승 배당 입력]  " + "  ".join(f"{int(n)}번 {h}" for n, h in zip(g["n"], g["hrName"].fillna(""))))
        while True:
            s = input(f"  {len(g)}두의 단승 배당을 출주번호 순서대로 (쉼표나 띄어쓰기로 구분, 엔터 = 이 경주는 배당 없이): ").strip()
            if not s:
                break
            vals = [v for v in re.split(r"[,\s]+", s) if v]
            try:
                vals = [float(v) for v in vals]
            except ValueError:
                print("  숫자만 입력해 주세요 (예: 3.2, 12.5, 4.1 ...)"); continue
            if len(vals) != len(g):
                print(f"  {len(g)}개를 입력해야 합니다 (지금 {len(vals)}개)"); continue
            rows += [{"rcNo": race, "chulNo": str(int(n)), "winOdds": v} for n, v in zip(g["n"], vals)]
            break
    return pd.DataFrame(rows, columns=["rcNo", "chulNo", "winOdds"])


BLEND_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "winner_history", "blend.json")


def blend_coefs(art=None):
    """결합 계수 (alpha, beta, gamma): winner_history/blend.json (2026-11-12, 비인기마 편향 항 γ 추가) → 없으면 모델 파일 값"""
    try:
        with open(BLEND_FILE, encoding="utf-8") as fh:
            c = json.load(fh)
        return float(c["alpha"]), float(c["beta"]), float(c.get("gamma", 0.0))
    except (OSError, ValueError, KeyError):
        return (art or {}).get("alpha", 0.1689), (art or {}).get("beta", 0.9219), 0.0


def combine_market(result, odds, alpha, beta, gamma=0.0):
    """결합 확률 ∝ exp(alpha·log 모델 + beta·log 시장 + gamma·(log 시장)²). 시장 확률 = (1/배당)을 경주 안에서 합 1로"""
    r = result.drop(columns=[c for c in ("winOdds",) if c in result.columns])
    r = r.assign(_k=r["chulNo"].astype(str).str.lstrip("0"))
    if odds is not None and len(odds):
        r = r.merge(odds.rename(columns={"rcNo": "race_no", "chulNo": "_k"}), on=["race_no", "_k"], how="left")
    else:
        r["winOdds"] = np.nan
    r = r.drop(columns="_k")
    r["q_market"] = np.nan
    r["p_comb"] = np.nan
    for race, idx in r.groupby("race_no").groups.items():
        od = r.loc[idx, "winOdds"]
        if not (od > 0).all():
            if od.notna().any():
                print(f"(주의) {race}경주: 배당이 빠진 말이 있어 시장 결합을 하지 않았습니다")
            continue
        q = (1 / od) / (1 / od).sum()
        lq = np.log(q)
        s = alpha * np.log(np.clip(r.loc[idx, "p_model"], 1e-9, None)) + beta * lq + gamma * lq * lq
        e = np.exp(s - s.max())
        r.loc[idx, "q_market"] = q
        r.loc[idx, "p_comb"] = e / e.sum()
    r["p_win"] = r["p_comb"].fillna(r["p_model"])
    r["ev"] = r["p_comb"] * r["winOdds"]
    return r


# =====================================================
# 예측 (예전 모델 v2/v3/blend)
# =====================================================
def load_history_old(path):
    raw = pd.read_csv(path, usecols=lib.USE_COLS + ["jkName"],
                      dtype={"date": str, "hrNo": str, "chulNo": str, "jkNo": str, "trNo": str})
    raw["race_seq"] = raw["date"].astype(int) * 100 + raw["race_no"].astype(int)
    return raw


def entrant_features_old(history, entries, date):
    e = entries.copy()
    e["date"] = date
    e["race_no"] = e["rcNo"]
    e["ord"] = e.groupby("rcNo")["chulNo"].transform(lambda s: pd.to_numeric(s).rank(method="first")).astype(int).clip(upper=16)
    e["rcTime"] = 60.0 + e["ord"]
    e["race_seq"] = int(date) * 100 + 99
    cols = lib.USE_COLS + ["race_seq"]
    feat = lib.compute_features(pd.concat([history[cols], e[cols]], ignore_index=True))
    return feat[feat["date"] == date].copy()


def race_normalize(p, codes):
    return p / np.bincount(codes, weights=p)[codes]


def prepare_inputs(feat, cat_cols):
    """범주형은 문자열/빈칸으로, 숫자는 소수 12자리로 반올림 (계산 순서 차이로 확률이 흔들리지 않게)"""
    X = feat.copy()
    for c in cat_cols:
        X[c] = X[c].astype(object).where(X[c].notna(), None)
    num = [c for c in X.columns if c not in cat_cols and pd.api.types.is_numeric_dtype(X[c])]
    X[num] = X[num].round(12)
    return X


def apply_bin_edges(A, edges):
    out = np.empty(A.shape, dtype=np.float32)
    for j, e in enumerate(edges):
        col = A[:, j]
        b = np.searchsorted(e, col, side="left").astype(np.float32)
        b[np.isnan(col)] = np.nan
        out[:, j] = b
    return out


def predict_old(feat, models_dir, which):
    X = prepare_inputs(feat, ("sex", "rank", "track_state"))
    codes = pd.factorize(X["race_no"])[0]
    probs = {}
    if which in ("v2", "blend"):
        art = joblib.load(os.path.join(models_dir, "win_model_v2.joblib"))
        probs["v2"] = race_normalize(art["model"].predict_proba(X[art["features"]])[:, 1], codes)
    if which in ("v3", "blend"):
        art = joblib.load(os.path.join(models_dir, "win_model_v3.joblib"))
        num = X[art["num_features"]].to_numpy(float)
        if art.get("bin_edges") is not None:
            num = apply_bin_edges(num, art["bin_edges"])
        xn = np.hstack([art["encoder"].transform(X[art["cat_features"]]), num]).astype(np.float32)
        s = art["learning_rate"] * sum(t.predict(xn) for t in art["trees"])
        probs["v3"] = race_normalize(np.exp(s - pd.Series(s).groupby(codes).transform("max").to_numpy()), codes)
    if which == "blend":
        s = 0.5 * np.log(np.clip(probs["v2"], 1e-9, None)) + 0.5 * np.log(np.clip(probs["v3"], 1e-9, None))
        return race_normalize(np.exp(s - pd.Series(s).groupby(codes).transform("max").to_numpy()), codes)
    return probs[which]


# =====================================================
# 출력
# =====================================================
def race_bets(result, top):
    out = []
    for race_no, g in result.groupby("race_no"):
        g = g.sort_values("p_win", ascending=False)
        labels = pd.to_numeric(g["chulNo"]).astype(int).tolist()
        b = bp.bet_rows(g["p_win"].to_numpy(), labels, BET_LAMBDA2, BET_LAMBDA3, top=top)
        b.insert(0, "race_no", race_no)
        out.append(b)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def pct(x):
    return "" if pd.isna(x) else f"{x * 100:.1f}%"


def show(result, backtest, bets=None, show_top=3, odds_label="배당"):
    for race_no, g in result.groupby("race_no"):
        g = g.sort_values("p_win", ascending=False)
        dist = g["rcDist"].dropna()
        has_mkt = g["p_comb"].notna().all()
        head = f"\n=== {race_no}경주" + (f" ({int(dist.iloc[0])}m)" if len(dist) else "") + f" | 출전 {len(g)}두"
        head += (" | 시장 결합 확률" if has_mkt else " | 모델 확률 (배당 없음)") + " ==="
        print(head)
        t = pd.DataFrame({"예상순위": range(1, len(g) + 1), "번호": pd.to_numeric(g["chulNo"]).astype(int).values,
                          "마명": g["hrName"].fillna("").values, "기수": g["jkName"].fillna("").values})
        if has_mkt:
            t["결합확률"] = [pct(v) for v in g["p_comb"]]
            t["모델"] = [pct(v) for v in g["p_model"]]
            t["시장"] = [pct(v) for v in g["q_market"]]
            t[odds_label] = g["winOdds"].round(1).values
            t["기대값"] = g["ev"].round(2).values
        else:
            t["우승확률"] = [pct(v) for v in g["p_model"]]
        t["이전출주"] = g["n_prior_races"].astype(int).values
        if backtest:
            t["실제순위"] = g["actual_ord"].astype("Int64").astype(str).values
        print(t.to_string(index=False))
        if (g["n_prior_races"] == 0).any():
            print("  * 이전출주 0: 기록이 없는 말(신마 등)이라 확률의 신뢰도가 낮습니다")
        if bets is not None and show_top > 0 and len(bets):
            rb = bets[(bets["race_no"] == race_no) & (bets["순위"] <= show_top)]
            n = len(g)
            print(f"  [승식별 확률 상위 {show_top}]  (연승 = {'3' if n >= 8 else '2'}착 이내)")
            for name in bp.BET_NAMES:
                r = rb[rb["승식"] == name]
                if r.empty:
                    continue
                txt = "   ".join(f"{c} ({p * 100:.1f}%)" for c, p in zip(r["조합"], r["확률"]))
                print(f"   {name:<4} {txt}   [전체 {int(r['조합수'].iloc[0])}조합]")
        if backtest:
            fin = g.dropna(subset=["actual_ord"]).sort_values("actual_ord")
            top3 = pd.to_numeric(fin[fin["actual_ord"] <= 3]["chulNo"]).astype(int).tolist()
            if top3:
                print("  실제 1~3착: " + "→".join(map(str, top3)))


# =====================================================
# main
# =====================================================
def main():
    ap = argparse.ArgumentParser(description="서울 경마 경주 우승 확률 예측")
    ap.add_argument("--date", required=True, help="경주일자 YYYYMMDD")
    ap.add_argument("--race", type=int, help="특정 경주 번호만 (생략하면 그날 전체)")
    ap.add_argument("--key", default=os.environ.get("KRA_API_KEY"), help="공공데이터포털 인증키. 환경변수 KRA_API_KEY 도 가능")
    ap.add_argument("--entries-csv", help="API 대신 직접 만든 출전표 CSV (열: rcNo,chulNo,hrNo,jkNo,trNo,wgBudam,age,sex,[hrName,jkName,rank,rcDist,rating])")
    ap.add_argument("--scratch", action="append", default=[], help="출전 제외 말 '경주번호:출전번호' (예: --scratch 5:3)")
    ap.add_argument("--raceday-csv", help="당일 정보 CSV (열: rcNo,chulNo,wgHr[,track,hrTool]), wgHr 예: 441(-9)")
    ap.add_argument("--track", help='당일 주로 상태, 예: "건조 (3%%)"')
    ap.add_argument("--weather", choices=["맑음", "흐림", "비", "눈", "안개"], help="당일 날씨")
    ap.add_argument("--odds-csv", help="단승 배당 CSV (열: rcNo,chulNo,winOdds) → 시장 결합 확률로 예측")
    ap.add_argument("--ask-odds", action="store_true", help="경주마다 단승 배당을 화면에서 직접 입력")
    ap.add_argument("--backtest", action="store_true", help="과거 날짜로 연습: 그 날 이전 기록만으로 예측, 실제 결과·확정 배당 표시")
    ap.add_argument("--with-raceday", action="store_true", help="(--backtest) 실제 마체중/주로/날씨도 입력으로 사용")
    ap.add_argument("--model", choices=["v5", "blend", "v2", "v3"], default="v5", help="사용할 모델 (기본 v5)")
    ap.add_argument("--history", default="merged.csv", help="과거 경주 기록 파일")
    ap.add_argument("--details", default="race_details_all.csv.gz", help="경주성적정보 합친 파일")
    ap.add_argument("--details-dir", default="race_details", help="경주성적정보 날짜별 파일 폴더")
    ap.add_argument("--models-dir", default="winner_history")
    ap.add_argument("--out", help="결과 CSV 경로 (기본: predictions_날짜.csv)")
    ap.add_argument("--show-raw", action="store_true", help="출전표 API 응답 항목 이름을 출력하고 종료")
    ap.add_argument("--bets", type=int, default=3, help="화면에 보여줄 승식별 상위 조합 수 (0이면 표시 안 함)")
    args = ap.parse_args()

    if not re.fullmatch(r"\d{8}", args.date):
        sys.exit("--date 는 YYYYMMDD 형식이어야 합니다 (예: 20261107)")
    v5mode = args.model == "v5"
    if v5mode:
        import features_v5 as fv
        art_path = os.path.join(args.models_dir, "win_model_v5.joblib")
        if not os.path.exists(art_path):
            sys.exit(f"{art_path} 가 없습니다. train_win_model_v5.py 로 학습하거나 받은 파일을 winner_history 폴더에 넣어 주세요.")
        art = joblib.load(art_path)
        history_all = fv.load_history(args.history)
        rd_all = fv.load_details(args.details, args.details_dir)
    else:
        history_all = load_history_old(args.history)
        rd_all = None

    # ---- 과거 기록 (예측할 날짜보다 이전 것만 사용) ----
    history = history_all[history_all["date"] < args.date]
    last = history["date"].max()
    gap = (pd.Timestamp(args.date) - pd.Timestamp(last)).days
    print(f"과거 기록: {last}까지 ({len(history):,}행)" + (f", 경주성적정보: {rd_all.loc[rd_all['rcDate'] < args.date, 'rcDate'].max()}까지" if v5mode else ""))
    if gap > 8 and not args.backtest:
        print(f"(주의) 기록이 예측일보다 {gap}일 전까지만 있습니다. kra_race_collector.py → merge_to_excel.py → fetch_race_details.py 로 갱신하면 더 정확합니다.")
    if v5mode and rd_all.loc[rd_all["rcDate"] < args.date, "rcDate"].max() < last:
        print("(주의) 경주성적정보가 경주 기록보다 오래됐습니다. fetch_race_details.py 를 실행해 주세요 (거리·속도지수 특징이 빠짐).")

    # ---- 출전표 ----
    actual, final_odds = None, None
    if args.backtest:
        day = history_all[(history_all["date"] == args.date) & (history_all["ord"].between(1, 16) | history_all["ord"].between(91, 95))]
        if day.empty:
            sys.exit(f"{args.date} 에 해당하는 과거 경주 기록이 없습니다.")
        day = day[~day["ord"].between(93, 95)]                       # 출전 취소·제외마는 빼고
        entries = pd.DataFrame({"rcNo": day["race_no"], "chulNo": day["chulNo"], "hrNo": day["hrNo"], "hrName": day["hrName"],
                                "jkNo": day["jkNo"], "jkName": day["jkName"], "trNo": day["trNo"], "trName": None,
                                "sex": day["sex"], "age": day["age"], "wgBudam": day["wgBudam"], "rank": day["rank"],
                                "wgHr": day["wgHr"] if args.with_raceday else None,
                                "track": day["track"] if args.with_raceday else None})
        entries = normalize_entries(entries)
        actual = day.assign(hrNo=lib.normalize_id(day["hrNo"]))[["race_no", "hrNo", "ord"]].rename(columns={"ord": "actual_ord"})
        actual["actual_ord"] = actual["actual_ord"].where(actual["actual_ord"].between(1, 16))
        if v5mode:      # 경주 전에 공개되는 정보(거리·레이팅·감량, 선택: 날씨)와 확정 단승 배당은 경주성적정보에서
            d = rd_all[rd_all["rcDate"] == args.date].assign(rcNo=lambda x: pd.to_numeric(x["rcNo"]).astype(int))
            keep = ["rcNo", "hrNo", "rcDist", "rating", "wgJk"] + (["weather"] if args.with_raceday else [])
            entries = entries.drop(columns=["rcDist", "rating", "wgJk"] + (["weather"] if args.with_raceday else [])).merge(
                d[keep].assign(rcDist=lambda x: pd.to_numeric(x["rcDist"], errors="coerce"),
                               rating=lambda x: pd.to_numeric(x["rating"], errors="coerce"),
                               wgJk=lambda x: pd.to_numeric(x["wgJk"], errors="coerce")), on=["rcNo", "hrNo"], how="left")
            final_odds = d.assign(chulNo=d["chulNo"].astype(str).str.lstrip("0"),
                                  winOdds=pd.to_numeric(d["winOdds"], errors="coerce"))[["rcNo", "chulNo", "winOdds"]]
    elif args.entries_csv:
        entries = normalize_entries(pd.read_csv(args.entries_csv, dtype=str))
    else:
        if not args.key:
            sys.exit("인증키가 필요합니다: --key 로 넣거나 환경변수 KRA_API_KEY 를 설정하세요 (또는 --entries-csv 사용)")
        raw_entries = fetch_entries_api(args.date, args.key, args.show_raw)
        if args.show_raw:
            return
        if raw_entries.empty:
            sys.exit(f"{args.date} 에 서울 경마 출전표가 없습니다 (경마 시행일이 아니거나 아직 출전표가 확정되지 않았을 수 있어요).")
        entries = normalize_entries(raw_entries)

    if args.race:
        entries = entries[entries["rcNo"] == args.race]
    entries = apply_scratches(entries, args.scratch)
    entries = add_raceday_info(entries, None if args.backtest else args.raceday_csv, None if args.backtest else args.track,
                               args.weather if not (args.backtest and args.with_raceday) else None)
    if entries.empty:
        sys.exit("예측할 출전마가 없습니다.")
    notes = []
    if entries["wgHr"].isna().all():
        notes.append("당일 마체중·주로 정보 없음 (--raceday-csv, --track 로 넣으면 조금 더 정확)")
    if v5mode and entries["weather"].isna().all():
        notes.append("날씨 정보 없음 (--weather 맑음/흐림/비)")
    if v5mode and entries["rcDist"].isna().any():
        notes.append("경주 거리가 빠진 말이 있음 → 거리 적성 특징이 빈칸")

    # ---- 특징 계산 -> 예측 ----
    info_cols = ["race_no", "hrNo", "chulNo", "hrName", "jkName", "rcDist"]
    einfo = entries.rename(columns={"rcNo": "race_no"})[info_cols]
    if v5mode:
        print("특징 계산 중... (1~3분)", flush=True)
        feat, info = fv.entrant_features(history_all, rd_all, entries, args.date)
        if info["tools_guessed"]:
            notes.append("장구는 직전 경주 장구를 그대로 쓴다고 가정 (raceday.csv 의 hrTool 열로 넣을 수 있음)")
        if info["birthday_guessed"]:
            notes.append(f"첫 출전마 {info['birthday_guessed']}두는 생일을 나이로 추정")
        X = prepare_inputs(feat, art["cat_features"])
        codes = pd.factorize(X["race_no"])[0]
        p = race_normalize(art["model"].predict_proba(X[art["features"]])[:, 1], codes)
    else:
        feat = entrant_features_old(history, entries, args.date)
        p = predict_old(feat, args.models_dir, args.model)
    result = feat[["race_no", "hrNo", "n_prior_races"]].assign(p_model=p).merge(einfo, on=["race_no", "hrNo"])
    if actual is not None:
        result = result.merge(actual, on=["race_no", "hrNo"], how="left")

    # ---- 배당 → 시장 결합 ----
    odds, odds_label = None, "배당"
    if args.backtest and v5mode:
        odds, odds_label = final_odds, "확정배당"
    elif args.odds_csv:
        odds = read_odds_csv(args.odds_csv)
    elif args.ask_odds:
        odds = ask_odds(entries)
    if v5mode:
        result = combine_market(result, odds, *blend_coefs(art))
        if odds is not None and len(odds) and result["p_comb"].isna().all() and not args.backtest:
            print("(주의) 입력한 배당에 예측하는 경주의 말이 없습니다 (경주번호 rcNo·출주번호 chulNo 를 확인하세요)")
    else:
        result = result.assign(winOdds=np.nan, q_market=np.nan, p_comb=np.nan, p_win=result["p_model"], ev=np.nan)

    bets = race_bets(result, BET_SAVE_TOP)
    for n in notes:
        print(f"(안내) {n}")
    show(result, args.backtest, bets, args.bets, odds_label)

    out_path = args.out or f"predictions_{args.date}.csv"
    cols = ["race_no", "chulNo", "hrName", "jkName", "rcDist", "n_prior_races", "p_model", "winOdds", "q_market", "p_comb", "ev", "p_win"] + \
           (["actual_ord"] if args.backtest else []) + ["hrNo"]
    result.sort_values(["race_no", "p_win"], ascending=[True, False])[cols].round(4).to_csv(out_path, index=False, encoding="utf-8-sig")
    bets_path = os.path.join(os.path.dirname(out_path), f"bets_{os.path.basename(out_path)}")
    bets.assign(확률=bets["확률"].round(5)).to_csv(bets_path, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료: {out_path} (말별 확률), {bets_path} (승식별 상위 {BET_SAVE_TOP}조합)")
    if v5mode and odds is None and not args.backtest:
        tpl = f"odds_input_{args.date}.csv"
        if not os.path.exists(tpl):
            (result.assign(rcNo=result["race_no"], winOdds="").sort_values(["race_no", "chulNo"], key=lambda s: pd.to_numeric(s, errors="coerce"))
             [["rcNo", "chulNo", "hrName", "winOdds"]].to_csv(tpl, index=False, encoding="utf-8-sig"))
            print(f"배당 입력용 {tpl} 를 만들었습니다. 경주 직전 단승 배당을 winOdds 칸에 채운 뒤 --odds-csv {tpl} 로 다시 실행하면 시장 결합 확률이 나옵니다.")
    if result["p_comb"].notna().any():
        print(EV_NOTE)
    print("※ 확률은 과거 성적과 (입력했다면) 배당으로 낸 추정값입니다. 18년 검증에서 꾸준히 수익을 낸 승식·전략은 없었습니다 "
          "(손실이 가장 작은 것: 연승 모델 1순위 회수율 약 89%, 단승 모델 1순위 약 86%).")


if __name__ == "__main__":
    main()
