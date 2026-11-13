"""사이트용 예측 내보내기 (pipeline/run_all.py 가 work/ 폴더 안에서 호출).

export(date, entries_rows, data_dir)
  - entries_rows: 출전표 API(API26_2) 응답 행 그대로 (site/data/entries/날짜.json 의 rows)
  - predict_race.py 와 같은 방법(v5)으로 그날 모든 경주의 모델 우승 확률을 계산
  - 경주마다 simulate_race.py 로 전개 시뮬레이션 파일(data_dir/sim/sim_날짜_R경주.json)을 만듦
  - 반환: {"races": {"1": {"p": {"3": 0.21, ...}, "n": {"3": 5, ...}, "sim": "sim_..json"}}, "model": "v5", ...}
배당은 사이트에서 사용자가 넣으면 브라우저에서 결합하므로 여기서는 모델 확률만 만든다.

모델 고르기: 경주일이 기본 모델(winner_history)의 학습 기간 안이면, 그보다 앞까지만 학습한
winner_history_bt/ 모델을 써서 지난 경주도 '경주 전에 낸 예측'과 같은 조건으로 만든다.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import time
from pathlib import Path

import joblib
import pandas as pd

import features_v5 as fv
import predict_race as pr
import train_sectional_model as tsm

HISTORY, DETAILS, DETAILS_DIR = "merged.csv", "race_details_all.csv.gz", "race_details"
MODEL_DIRS = ["winner_history", "winner_history_bt"]     # 최신 모델 → 과거 검증용 모델 순서
_cache: dict = {}


def _load():
    if "hist" not in _cache:
        t = time.time()
        _cache["hist"] = fv.load_history(HISTORY)
        _cache["rd"] = fv.load_details(DETAILS, DETAILS_DIR)
        print(f"  기록 불러오기 {time.time() - t:.0f}초 (경주 기록 ~{_cache['hist']['date'].max()}, 경주성적 ~{_cache['rd']['rcDate'].max()})", flush=True)
    return _cache["hist"], _cache["rd"]


def _art(d: str):
    if d not in _cache:
        _cache[d] = joblib.load(os.path.join(d, "win_model_v5.joblib"))
    return _cache[d]


def _mkt():
    """배당 반영 모델(work/train_mkt_model.py) — 없으면 None"""
    if "mkt" not in _cache:
        f = os.path.join("winner_history", "win_mkt_v1.joblib")
        _cache["mkt"] = joblib.load(f) if os.path.exists(f) else None
    return _cache["mkt"]


def export_mkx(date: str, X: pd.DataFrame, chul: pd.Series, data_dir: Path) -> None:
    """배당 반영 모델이 쓰는 말마다 특징(시장 특징 빼고) → data_dir/mkx/날짜.json. 브라우저(assets/mktmodel.js)가
    사용자가 넣은 단승 배당과 합쳐 직접 계산. 모델 학습이 그날보다 앞에서 끝났을 때만 (지난 날 검증과 같은 조건)."""
    mk = _mkt()
    if not mk or str(mk.get("trained_through")) >= date:
        return
    import json
    import numpy as np
    enc = mk["model"].named_steps["prep"].named_transformers_["cat"]
    base = [f for f in mk["features"] if f not in mk["market"]]
    codes = enc.transform(X[mk["cat_features"]].astype(object).where(X[mk["cat_features"]].notna(), None))
    nums = X[base[len(mk["cat_features"]):]].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    M = np.column_stack([codes, nums])
    races: dict = {}
    for (rno, c), row in zip(zip(X["race_no"], chul), M):
        if pd.isna(c):
            continue
        races.setdefault(str(int(rno)), {})[str(int(c))] = [None if not np.isfinite(v) else float(v) for v in row]     # 줄이지 않음 (트리 경계와 같은 값이 있음)
    out = Path(data_dir) / "mkx"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{date}.json").write_text(json.dumps({"date": date, "model": "mkt_v1", "trained_through": mk["trained_through"],
                                                  "n": len(base), "races": races}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def pick_model(date: str) -> str:
    """학습 기간이 그 경주일보다 앞에서 끝나는 모델 중 가장 최근 것 (없으면 기본 모델)"""
    for d in MODEL_DIRS:
        if os.path.exists(os.path.join(d, "win_model_v5.joblib")) and str(_art(d).get("trained_through")) < date:
            return d
    return MODEL_DIRS[0]


def export(date: str, rows: list[dict], data_dir: Path) -> dict:
    hist, rd = _load()
    mdir = pick_model(date)
    art = _art(mdir)
    raw = pd.DataFrame(rows)
    entries = pr.normalize_entries(raw)
    t = time.time()
    feat, info = fv.entrant_features(hist, rd, entries, date)
    X = pr.prepare_inputs(feat, art["cat_features"])
    p = pr.race_normalize(art["model"].predict_proba(X[art["features"]])[:, 1], pd.factorize(X["race_no"])[0])
    res = feat[["race_no", "hrNo", "n_prior_races"]].assign(p_model=p).merge(
        entries.rename(columns={"rcNo": "race_no"})[["race_no", "hrNo", "chulNo"]], on=["race_no", "hrNo"])
    try:      # 배당 반영 모델용 말마다 특징 (실패해도 예측은 그대로)
        chul = X[["race_no", "hrNo"]].merge(entries.rename(columns={"rcNo": "race_no"})[["race_no", "hrNo", "chulNo"]], on=["race_no", "hrNo"], how="left")["chulNo"]
        export_mkx(date, X.reset_index(drop=True), chul.reset_index(drop=True), data_dir)
    except Exception as e:  # noqa: BLE001
        print(f"  배당 반영 모델 특징 저장 실패: {type(e).__name__}: {e}", flush=True)
    print(f"  {date} 우승 확률 {len(res)}두 ({time.time() - t:.0f}초)", flush=True)

    races = {}
    for rno, g in res.groupby("race_no"):
        races[str(int(rno))] = {
            "p": {str(int(c)): round(float(v), 5) for c, v in zip(g["chulNo"], g["p_model"])},
            "n": {str(int(c)): int(v) for c, v in zip(g["chulNo"], g["n_prior_races"])},
        }

    # 당일 마체중 (있으면): 사이트 표시용 [kg, 증감]
    if "wgHr" in raw.columns:
        wg = raw["wgHr"].astype(str).str.extract(r"^\s*(\d+)\s*(?:\(\s*([+-]?\d*)\s*\))?")
        for (rno, ch), kg, cg in zip(zip(pd.to_numeric(raw["rcNo"]), pd.to_numeric(raw["chulNo"])), wg[0], wg[1]):
            if pd.notna(kg) and str(int(rno)) in races:
                races[str(int(rno))].setdefault("wg", {})[str(int(ch))] = [int(kg), int(cg) if cg not in ("", None) and pd.notna(cg) else 0]

    # 지난 경주일이면 실제 1~3착 (사이트에서 예측과 비교)
    day = hist[(hist["date"] == date) & pd.to_numeric(hist["ord"], errors="coerce").between(1, 3)]
    for rno, g in day.groupby("race_no"):
        if str(int(rno)) in races:
            g = g.assign(o=pd.to_numeric(g["ord"])).sort_values("o")
            races[str(int(rno))]["result"] = [int(float(c)) for c in g["chulNo"]]

    # 경주 불성립(98)·경주 취소(99): 모든 말이 그 코드면 표시 (결과·배당 없음, 마권 환불)
    dd = hist[hist["date"] == date]
    for rno, g in dd.groupby("race_no"):
        o = pd.to_numeric(g["ord"], errors="coerce")
        if str(int(rno)) in races and len(o) and o.isin([98, 99]).all():
            races[str(int(rno))]["void"] = "경주 불성립" if (o == 98).all() else "경주 취소"

    # 끝난 경주의 확정 단승 배당(경주성적정보 winOdds, 마감 후 값)과 출전 취소마 → 사이트가 배당 칸을 미리 채움
    d_rd = rd[rd["rcDate"] == date]
    for rno, g in d_rd.groupby(pd.to_numeric(d_rd["rcNo"], errors="coerce")):
        key = str(int(rno))
        if key not in races or "result" not in races[key]:
            continue
        o = pd.to_numeric(g["winOdds"], errors="coerce")
        ordv = pd.to_numeric(g["ord"], errors="coerce")
        ch = pd.to_numeric(g["chulNo"], errors="coerce")
        ran = (o > 0) & ~ordv.between(93, 99)
        races[key]["odds"] = {str(int(c)): float(v) for c, v in zip(ch[ran], o[ran])}
        po = pd.to_numeric(g["plcOdds"], errors="coerce")
        races[key]["plc"] = {str(int(c)): float(v) for c, v in zip(ch[ran & (po > 0)], po[ran & (po > 0)])}
        races[key]["out"] = sorted(int(c) for c in races[key]["p"] if int(c) not in set(ch[ran].astype(int)))

    # ---- 전개 시뮬레이션: simulate_race.py 를 경주마다 실행 (불러온 기록·특징은 재사용) ----
    sim_dir = Path(data_dir) / "sim"
    sim_dir.mkdir(parents=True, exist_ok=True)
    try:
        import simulate_race as sr
        sec = tsm.load_sectionals(DETAILS, DETAILS_DIR, extra=sr.EXTRA)
        orig = (fv.load_history, fv.load_details, tsm.load_sectionals, fv.entrant_features)
        fv.load_history = lambda *a, **k: hist
        fv.load_details = lambda *a, **k: rd
        tsm.load_sectionals = lambda *a, **k: sec

        def cached_features(h, r, e, d):
            keys = set(zip(e["rcNo"].astype(int), e["hrNo"]))
            f = feat[[(int(a), b) in keys for a, b in zip(feat["race_no"], feat["hrNo"])]].copy()
            return f, info
        fv.entrant_features = cached_features
        with tempfile.TemporaryDirectory() as tmp:
            csv = os.path.join(tmp, "entries.csv")
            raw.to_csv(csv, index=False)
            for rno in sorted(races, key=int):
                name = f"sim_{date}_R{rno}.json"
                argv = sys.argv
                if "result" in races[rno]:
                    # 끝난 경주: --backtest 로 실제 통과 순위·시간을 넣어 '실제 경주' 보기를 켬
                    # (특징은 위에서 그날 이전 기록으로 계산한 것을 그대로 쓰고, 우승 확률은 확정 단승 배당과 결합)
                    sys.argv = ["simulate_race.py", "--date", date, "--race", rno, "--backtest", "--models-dir", mdir, "--out", str(sim_dir / name)]
                else:
                    sys.argv = ["simulate_race.py", "--date", date, "--race", rno, "--entries-csv", csv, "--models-dir", mdir, "--out", str(sim_dir / name)]
                buf = io.StringIO()
                try:
                    with contextlib.redirect_stdout(buf):
                        sr.main()
                    races[rno]["sim"] = name
                    if "result" in races[rno]:
                        races[rno]["simActual"] = True
                except SystemExit as e:
                    print(f"  {rno}경주 시뮬레이션 건너뜀: {e}")
                except Exception as e:  # 시뮬레이션이 실패해도 확률은 올림
                    print(f"  {rno}경주 시뮬레이션 실패: {type(e).__name__}: {e}")
                finally:
                    sys.argv = argv
        fv.load_history, fv.load_details, tsm.load_sectionals, fv.entrant_features = orig
    except Exception as e:
        print(f"  시뮬레이션 준비 실패: {type(e).__name__}: {e}")
    print(f"  시뮬레이션 {sum('sim' in r for r in races.values())}/{len(races)}개 경주", flush=True)

    done = any("result" in r for r in races.values())
    return {"races": races, "model": "v5" + ("" if mdir == MODEL_DIRS[0] else " (검증용)"), "modelDir": mdir, "v": 2, "backtestDone": done, "trained_through": str(art.get("trained_through")),
            "history_through": str(hist["date"].max()),
            "notes": {"toolsGuessed": info.get("tools_guessed"), "birthdayGuessed": info.get("birthday_guessed")}}
