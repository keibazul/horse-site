"""사이트용 예측 내보내기 (pipeline/run_all.py 가 work/ 폴더 안에서 호출).

export(date, entries_rows, data_dir)
  - entries_rows: 출전표 API(API26_2) 응답 행 그대로 (site/data/entries/날짜.json 의 rows)
  - predict_race.py 와 같은 방법(v5)으로 그날 모든 경주의 모델 우승 확률을 계산
  - 경주마다 simulate_race.py 로 전개 시뮬레이션 파일(data_dir/sim/sim_날짜_R경주.json)을 만듦
  - 반환: {"races": {"1": {"p": {"3": 0.21, ...}, "n": {"3": 5, ...}, "sim": "sim_..json"}}, "model": "v5", ...}
배당은 사이트에서 사용자가 넣으면 브라우저에서 결합하므로 여기서는 모델 확률만 만든다.
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

HISTORY, DETAILS, DETAILS_DIR, MODELS = "merged.csv", "race_details_all.csv.gz", "race_details", "winner_history"
_cache: dict = {}


def _load():
    if "hist" not in _cache:
        t = time.time()
        _cache["hist"] = fv.load_history(HISTORY)
        _cache["rd"] = fv.load_details(DETAILS, DETAILS_DIR)
        _cache["art"] = joblib.load(os.path.join(MODELS, "win_model_v5.joblib"))
        print(f"  기록 불러오기 {time.time() - t:.0f}초 (경주 기록 ~{_cache['hist']['date'].max()}, 경주성적 ~{_cache['rd']['rcDate'].max()})", flush=True)
    return _cache["hist"], _cache["rd"], _cache["art"]


def export(date: str, rows: list[dict], data_dir: Path) -> dict:
    hist, rd, art = _load()
    raw = pd.DataFrame(rows)
    entries = pr.normalize_entries(raw)
    t = time.time()
    feat, info = fv.entrant_features(hist, rd, entries, date)
    X = pr.prepare_inputs(feat, art["cat_features"])
    p = pr.race_normalize(art["model"].predict_proba(X[art["features"]])[:, 1], pd.factorize(X["race_no"])[0])
    res = feat[["race_no", "hrNo", "n_prior_races"]].assign(p_model=p).merge(
        entries.rename(columns={"rcNo": "race_no"})[["race_no", "hrNo", "chulNo"]], on=["race_no", "hrNo"])
    print(f"  {date} 우승 확률 {len(res)}두 ({time.time() - t:.0f}초)", flush=True)

    races = {}
    for rno, g in res.groupby("race_no"):
        races[str(int(rno))] = {
            "p": {str(int(c)): round(float(v), 5) for c, v in zip(g["chulNo"], g["p_model"])},
            "n": {str(int(c)): int(v) for c, v in zip(g["chulNo"], g["n_prior_races"])},
        }

    # 지난 경주일이면 실제 1~3착 (사이트에서 예측과 비교)
    day = hist[(hist["date"] == date) & pd.to_numeric(hist["ord"], errors="coerce").between(1, 3)]
    for rno, g in day.groupby("race_no"):
        if str(int(rno)) in races:
            g = g.assign(o=pd.to_numeric(g["ord"])).sort_values("o")
            races[str(int(rno))]["result"] = [int(float(c)) for c in g["chulNo"]]

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
                    # (그날 이전 기록만 쓰고, 우승 확률은 확정 단승 배당과 결합)
                    fv.entrant_features = orig[3]
                    sys.argv = ["simulate_race.py", "--date", date, "--race", rno, "--backtest", "--out", str(sim_dir / name)]
                else:
                    fv.entrant_features = cached_features
                    sys.argv = ["simulate_race.py", "--date", date, "--race", rno, "--entries-csv", csv, "--out", str(sim_dir / name)]
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
    return {"races": races, "model": "v5", "v": 2, "backtestDone": done, "trained_through": str(art.get("trained_through")),
            "history_through": str(hist["date"].max()),
            "notes": {"toolsGuessed": info.get("tools_guessed"), "birthdayGuessed": info.get("birthday_guessed")}}
