"""자동 업데이트 전체 순서 (GitHub Actions 에서 실행).

1. 출전표 수집 → site/data/entries/날짜.json
2. (work/ 에 예측 코드가 있으면) 경주 기록 갱신 → 예측 → site/data/pred/날짜.json, site/data/sim/*.json
3. site/data/index.json 작성 (사이트가 처음 읽는 목차)

예측 코드 연결 방법: work/site_export.py 에 다음 함수를 둔다.
    def export(date: str, entries: list[dict], out_dir: pathlib.Path) -> dict
        반환: {"races": {"1": {"p": {"1": 0.12, ...}, "sim": "sim_20261108_R1.json"}, ...},
               "model": "v5", "note": "..."}
        sim 파일은 out_dir / "sim" 에 저장.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data"
WORK = ROOT / "work"
KST = dt.timezone(dt.timedelta(hours=9))
ALPHA, BETA = 0.1689, 0.9219  # train_win_model_v5.py 결합 비중 (2008~2026)
KEEP_PAST_DAYS = 2  # 지난 경주일도 몇 개 남겨 둠 (결과 확인용)


def log(*a):
    print(*a, flush=True)


def step(name: str, cmd: list[str], cwd: Path) -> bool:
    log(f"\n▶ {name}: {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=cwd)
    if r.returncode != 0:
        log(f"  ✗ {name} 실패 (종료 코드 {r.returncode})")
        return False
    return True


def refresh_history(fetch: bool = True) -> None:
    """work/update_history.py 로 경주 기록(merged.csv, race_details/rd_*.csv)을 최신으로."""
    cmd = [sys.executable, "update_history.py"] + ([] if fetch else ["--no-fetch"])
    if not step("경주 기록 갱신", cmd, WORK):
        log("  기록 갱신이 중간에 멈췄습니다. 예측은 있는 기록으로 계속합니다.")


def load_exporter():
    f = WORK / "site_export.py"
    if not f.exists():
        return None
    sys.path.insert(0, str(WORK))
    spec = importlib.util.spec_from_file_location("site_export", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def day_stats(pred: dict) -> dict | None:
    """끝난 경주일: 모델 1순위 / 결합(확정 배당) 1순위 / 배당 1순위(인기마)가 실제로 이긴 경주 수"""
    import math
    n = hm = hc = hk = 0
    for r in pred.get("races", {}).values():
        res, p = r.get("result"), r.get("p") or {}
        if not res or not p:
            continue
        out = set(map(str, r.get("out", [])))
        live = {k: v for k, v in p.items() if k not in out}
        if not live:
            continue
        n += 1
        hm += max(live, key=live.get) == str(res[0])
        od = r.get("odds") or {}
        if all(k in od and od[k] > 1 for k in live):
            s = sum(1 / od[k] for k in live)
            sc = {k: ALPHA * math.log(max(v, 1e-9)) + BETA * math.log((1 / od[k]) / s) for k, v in live.items()}
            hc += max(sc, key=sc.get) == str(res[0])
            hk += min(live, key=lambda k: od[k]) == str(res[0])
    return {"races": n, "model": hm, "comb": hc, "mkt": hk} if n else None


def add_weights(d: str, rows: list[dict]) -> list[dict]:
    """site/data/weights/날짜.json 의 당일 마체중을 출전표 행에 wgHr('510(+7)', 변화 없으면 '465()')로 붙임"""
    f = DATA / "weights" / f"{d}.json"
    if not f.exists():
        return rows
    w = json.loads(f.read_text(encoding="utf-8")).get("races", {})
    out = []
    for r in rows:
        x = w.get(str(int(r.get("rcNo", 0))), {}).get(str(int(r.get("chulNo", 0))))
        r = dict(r)
        if x and x.get("kg"):
            r["wgHr"] = f"{x['kg']}({x['chg']:+d})" if x.get("chg") else f"{x['kg']}()"
        out.append(r)
    return out


def signature(rows: list[dict]) -> str:
    """예측을 다시 만들어야 하는지 판단: 출전표+마체중, 경주 기록 크기, 모델 파일"""
    import hashlib
    h = hashlib.sha1(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode())
    for f in [WORK / "merged.csv", *sorted((WORK / "winner_history").glob("*.joblib"))]:
        if f.exists():
            h.update(f"{f.name}:{f.stat().st_size}".encode())
    for f in sorted((WORK / "winner_history").glob("*.joblib")):
        h.update(hashlib.sha1(f.read_bytes()).digest())
    return h.hexdigest()[:16]


def day_finished(d: str, today: dt.date) -> bool:
    """지난 날이거나, 오늘인데 경주결과·경주성적정보가 모두 들어온 날"""
    t = today.strftime("%Y%m%d")
    if d < t:
        return True
    return d == t and (WORK / "results" / f"rr_{d}.csv").exists() and (WORK / "race_details" / f"rd_{d}.csv").exists()


def write_index(today: dt.date, connected: bool, model_name: str | None = None) -> None:
    """사이트 목차: 예측이 있는 지난 경주일 전부 + 앞으로 열릴 경주일"""
    t = today.strftime("%Y%m%d")
    ent = sorted(f.stem for f in (DATA / "entries").glob("*.json"))
    days = []
    for d in ent:
        pf = DATA / "pred" / f"{d}.json"
        past = d < t or (d == t and pf.exists() and bool(json.loads(pf.read_text(encoding="utf-8")).get("backtestDone")))
        if past and not pf.exists():
            continue
        item = {"date": d, "entries": f"entries/{d}.json", "past": past}
        if pf.exists():
            item["pred"] = f"pred/{d}.json"
            if past:
                st = day_stats(json.loads(pf.read_text(encoding="utf-8")))
                if st:
                    item["hits"] = st
        days.append(item)
    idx = {
        "updated": dt.datetime.now(KST).strftime("%Y-%m-%dT%H:%M"),
        "alpha": ALPHA, "beta": BETA,
        "model": {"connected": connected, "name": model_name or ("v5" if connected else None)},
        "days": days,
    }
    fi = DATA / "index.json"
    try:   # 시각 말고 바뀐 것이 없으면 그대로 둠 → 바뀐 데이터가 없으면 커밋·배포도 안 함
        old = json.loads(fi.read_text(encoding="utf-8"))
        if {**old, "updated": None} == {**idx, "updated": None}:
            idx["updated"] = old["updated"]
    except (OSError, ValueError, KeyError):
        pass
    fi.write_text(json.dumps(idx, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    try:
        sys.path.insert(0, str(ROOT / "pipeline"))
        import strategy
        strategy.write()
    except Exception as e:  # 수익 계산이 실패해도 사이트 갱신은 계속
        log(f"전략 계산 실패: {e}")
    past = [x for x in days if x["past"]]
    log(f"\n목차: 지난 경주일 {len(past)}일, 앞으로 {len(days) - len(past)}일")


def main() -> int:
    if "--index-only" in sys.argv:
        write_index(dt.datetime.now(KST).date(), (WORK / "site_export.py").exists())
        return 0
    today = dt.datetime.now(KST).date()
    step("출전표 수집", [sys.executable, str(ROOT / "pipeline" / "fetch_entries.py"), "--days", "8"], ROOT)
    # 지난 주말 출전표가 없으면 받아 둠 (다음 출전표가 나오기 전까지 사이트에 보여 줄 것)
    for back in range(1, 8):
        d = today - dt.timedelta(days=back)
        if d.weekday() in (5, 6) and not (DATA / "entries" / f"{d:%Y%m%d}.json").exists():
            step("지난 경주일 출전표", [sys.executable, str(ROOT / "pipeline" / "fetch_entries.py"), "--date", f"{d:%Y%m%d}"], ROOT)

    ent_files = sorted((DATA / "entries").glob("*.json"))
    upcoming = [f.stem for f in ent_files if f.stem >= today.strftime("%Y%m%d")]
    # 사이트에 남겨 두는 지난 경주일도 예측이 없으면 만든다 (그날 이전 기록만 쓰므로 사전 예측과 같음)
    past_keep = [f.stem for f in ent_files if f.stem < today.strftime("%Y%m%d")][-KEEP_PAST_DAYS:]
    def needs_result(d):
        f = DATA / "pred" / f"{d}.json"
        if not f.exists():
            return True
        # 결과가 들어오면 실제 구간 기록을 넣은 시뮬레이션(backtest)으로 한 번 다시 만든다
        j = json.loads(f.read_text(encoding="utf-8"))
        return not (j.get("backtestDone") and j.get("v", 1) >= 2)   # v2: 확정 배당·출전 취소 포함
    upcoming += [d for d in past_keep if needs_result(d)]

    # 경주 당일(또는 지난 이틀 안) 마체중: KRA 홈페이지에 입력된 경주만 받아 둠
    for d in sorted(set(upcoming)):
        if d <= today.strftime("%Y%m%d") and d >= (today - dt.timedelta(days=1)).strftime("%Y%m%d"):
            step("당일 마체중", [sys.executable, str(ROOT / "pipeline" / "fetch_weights.py"), "--date", d], ROOT)

    exporter = load_exporter()
    model_name = None
    if exporter:
        refresh_history(fetch=os.environ.get("SKIP_HISTORY") != "1")
    if exporter and upcoming:
        os.chdir(WORK)
        (DATA / "pred").mkdir(parents=True, exist_ok=True)
        (DATA / "sim").mkdir(parents=True, exist_ok=True)
        for d in upcoming:
            rows = add_weights(d, json.loads((DATA / "entries" / f"{d}.json").read_text(encoding="utf-8"))["rows"])
            sig = signature(rows)
            pf = DATA / "pred" / f"{d}.json"
            if day_finished(d, today):
                # 결과가 들어온 날(경주일 저녁의 오늘 포함): 결과·실제 경주 시뮬레이션으로 한 번만 다시 만든다
                if pf.exists() and not needs_result(d):
                    log(f"결과 반영 끝: {d}")
                    continue
                if pf.exists() and not (WORK / "results" / f"rr_{d}.csv").exists():
                    log(f"결과 기다림: {d} (경주 기록 갱신 때 들어옴)")
                    continue
            elif pf.exists():
                old = json.loads(pf.read_text(encoding="utf-8"))
                if old.get("sig") == sig:
                    log(f"예측 그대로: {d} (출전표·마체중·기록·모델 변화 없음)")
                    model_name = old.get("model", model_name)
                    continue
            try:
                res = exporter.export(d, rows, DATA)
                res["sig"] = sig
                res["date"] = d
                res["made"] = dt.datetime.now(KST).isoformat(timespec="minutes")
                (DATA / "pred" / f"{d}.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
                model_name = res.get("model", model_name)
                log(f"예측 저장: {d} ({len(res.get('races', {}))}개 경주)")
            except Exception:
                log(f"예측 실패: {d}")
                traceback.print_exc()
        os.chdir(ROOT)
    elif not exporter:
        log("work/site_export.py 가 없어 예측은 건너뜁니다 (출전표만 사이트에 표시).")

    # 참고 정보(진료·조교 등, 예측에는 안 씀): 앞으로 열릴 날은 매번, 지난 날은 파일이 없을 때만 (한 번에 4일까지)
    t8 = today.strftime("%Y%m%d")
    have_x = {f.stem for f in (DATA / "extra").glob("*.json")} if (DATA / "extra").exists() else set()
    xd = [f.stem for f in ent_files if f.stem >= t8] + [f.stem for f in ent_files if f.stem < t8 and f.stem not in have_x][-4:]
    if xd:
        step("참고 정보", [sys.executable, str(ROOT / "pipeline" / "extra_site.py"), "--dates", ",".join(xd)], ROOT)
    if exporter and (WORK / "merged.csv").exists():
        # 출전마 지난 성적 (앞으로 열릴 날은 매번 새로, 지난 날은 없을 때만)
        step("지난 성적", [sys.executable, str(ROOT / "pipeline" / "form.py"), "--missing"] +
             sum([["--date", d] for d in upcoming if d >= today.strftime("%Y%m%d")], []), ROOT)
    # 끝난 경주일 확정 배당 (마권 기록장 정산용): 최근 날부터 한 번에 4일
    step("확정 배당", [sys.executable, str(ROOT / "pipeline" / "dividends.py"), "--missing", "--max", "4"], ROOT)
    # 경주일: 공공데이터 단승 배당을 시각과 함께 모아 둠 (경주 전에 바뀌는 값인지 확인용, 사이트에는 안 씀)
    step("배당 흐름", [sys.executable, str(ROOT / "pipeline" / "odds_snap.py")], ROOT)
    # 오늘 끝난 경주 결과를 예측 파일에 바로 (저녁 기록 갱신 전까지)
    step("당일 결과", [sys.executable, str(ROOT / "pipeline" / "live_results.py")], ROOT)
    # 당일 주로 경향 (앞서 끝난 경주의 안쪽·바깥쪽 유리 정도 → 뒤 경주 확률 보정), 지난 날은 없을 때만
    step("당일 주로 경향", [sys.executable, str(ROOT / "pipeline" / "live_bias.py"), "--past"], ROOT)
    # 베팅 계획 실전 기록: 결과가 난 날은 모든 조합 확정 배당을 받아 두고(정산용), 출발 전 계획 고정·정산
    step("모든 조합 확정 배당", [sys.executable, str(ROOT / "pipeline" / "fetch_odds_full.py"), "--since", "20261108", "--max", "2"], ROOT)
    step("베팅 계획 기록", ["node", str(ROOT / "pipeline" / "plan_track.js")], ROOT)
    step("모델 상태", [sys.executable, str(ROOT / "pipeline" / "calib.py")], ROOT)
    # 끝난 경주일 복기 (예측 파일이 바뀐 날만 다시)
    step("복기", [sys.executable, str(ROOT / "pipeline" / "review.py"), "--missing"], ROOT)
    write_index(today, exporter is not None, model_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
