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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blend_coef  # noqa: E402  (결합 계수: work/winner_history/blend.json)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data"
WORK = ROOT / "work"
KST = dt.timezone(dt.timedelta(hours=9))
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
            sc = {k: blend_coef.score(v, (1 / od[k]) / s) for k, v in live.items()}
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


def pre_race_changes(d: str) -> tuple[dict[int, set[int]], set[int]]:
    """출전표정보(API78)의 특이사항 + 기수변경·말취소(API320) → (경주별 '말취소' 번호, '경주취소'된 경주).
    site/data/extra/날짜.json, site/data/changes/날짜.json 에서 읽음 (경주일에는 실행마다 새로 받으므로 취소가 뜨면 다음 실행에 반영)."""
    f = DATA / "extra" / f"{d}.json"
    gone: dict[int, set[int]] = {}
    void: set[int] = set()
    try:
        for x in json.loads((DATA / "changes" / f"{d}.json").read_text(encoding="utf-8")).get("rows", []):
            if x.get("kind") == "말취소":
                gone.setdefault(int(x["race"]), set()).add(int(x["no"]))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    if not f.exists():
        return gone, void
    try:
        races = json.loads(f.read_text(encoding="utf-8")).get("races", {})
    except ValueError:
        return gone, void
    for rn, hs in races.items():
        spn = {int(c): (h or {}).get("spn") or "" for c, h in hs.items()}
        g = {c for c, v in spn.items() if "말취소" in v}
        if g:
            gone[int(rn)] = gone.get(int(rn), set()) | g
        if spn and all("경주취소" in v for v in spn.values()):
            void.add(int(rn))
    return gone, void


def apply_changes(res: dict, gone: dict[int, set[int]], void: set[int]) -> None:
    """예측 결과에 경주 전 취소를 표시: 취소마는 p 0 + out(사이트가 빼고 다시 나눔) + scr(경주 전에 알려진 취소), 취소된 경주는 void"""
    for rn, chs in gone.items():
        r = res.get("races", {}).get(str(rn))
        if r is None:
            continue
        for c in chs:
            r.setdefault("p", {}).setdefault(str(c), 0.0)
        r["out"] = sorted(set(map(int, r.get("out", []))) | chs)
        r["scr"] = sorted(chs)
    for rn in void:
        r = res.get("races", {}).get(str(rn))
        if r is not None and not r.get("void"):
            r["void"] = "경주 취소"


def apply_training(d: str) -> bool:
    """조교 횟수 보정: 모델 확률 × exp(T·rel), rel = 조교 횟수 − 그 경주 출전표 평균 (참고 정보 파일의 trngRel, ±clip).
    계수 T 는 work/winner_history/trng.json (work/fit_trng.py 가 매달 다시 맞춤). 원래 모델 확률은 p0 에 남기고,
    여러 번 실행해도 결과가 같다(p0 에서 다시 계산). 시뮬레이션 파일의 모델 확률(pModel)도 같은 값으로 맞춤."""
    import math
    cf, pf, xf = WORK / "winner_history" / "trng.json", DATA / "pred" / f"{d}.json", DATA / "extra" / f"{d}.json"
    if not (cf.exists() and pf.exists() and xf.exists()):
        return False
    try:
        c = json.loads(cf.read_text(encoding="utf-8")); T, clip = float(c["T"]), float(c.get("clip", 6))
        pred = json.loads(pf.read_text(encoding="utf-8")); extra = json.loads(xf.read_text(encoding="utf-8")).get("races", {})
    except (ValueError, KeyError):
        return False
    changed = []
    for rn, r in pred.get("races", {}).items():
        base = r.get("p0") or r.get("p") or {}
        xs = extra.get(rn) or {}
        rel = {k: float(xs[k]["trngRel"]) for k in base if k in xs and (xs[k] or {}).get("trngRel") is not None}
        out = {str(x) for x in r.get("out", [])}
        live = [k for k in base if k not in out]
        if not rel or not live:
            continue
        v = {k: base[k] * math.exp(T * max(-clip, min(clip, rel.get(k, 0.0)))) for k in live}
        s0, s1 = sum(base[k] for k in live), sum(v.values())
        if s1 <= 0:
            continue
        newp = {k: (round(v[k] * s0 / s1, 5) if k in v else base[k]) for k in base}
        if newp != r.get("p") or "p0" not in r:
            r["p0"], r["p"] = dict(base), newp
            changed.append(rn)
    if not changed and (pred.get("adj") or {}).get("trng") == T:
        return False
    pred["adj"] = {**(pred.get("adj") or {}), "trng": T}
    pf.write_text(json.dumps(pred, ensure_ascii=False), encoding="utf-8")
    for rn in changed:                                    # 다가오는 경주의 시뮬레이션: 우승 비율 목표를 보정한 확률로
        r = pred["races"][rn]
        sf = DATA / "sim" / str(r.get("sim") or "")
        if r.get("result") or not r.get("sim") or not sf.exists():
            continue
        try:
            sim = json.loads(sf.read_text(encoding="utf-8"))
            if sim.get("target") != "model":
                continue
            for h in sim.get("horses", []):
                if str(h.get("no")) in r["p"]:
                    h["pModel"] = round(r["p"][str(h["no"])], 4)
            sf.write_text(json.dumps(sim, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        except (ValueError, OSError):
            pass
    log(f"조교 횟수 보정 {d}: {len(changed)}개 경주 (계수 {T})")
    return True


def signature(rows: list[dict], void: set[int] = frozenset()) -> str:
    """예측을 다시 만들어야 하는지 판단: 출전표(취소마 뺀 것)+마체중, 취소된 경주, 경주 기록 크기, 모델 파일"""
    import hashlib
    h = hashlib.sha1(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode())
    if void:
        h.update(("void:" + ",".join(map(str, sorted(void)))).encode())
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
        "alpha": blend_coef.ALPHA, "beta": blend_coef.BETA, "gamma": blend_coef.GAMMA,
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

    # 참고 정보(진료·조교 등)와 특이사항(말취소·경주취소·기수변경): 앞으로 열릴 날은 매번, 지난 날은 파일이 없을 때만 (한 번에 4일까지)
    # 예측보다 먼저 받음 → 경주 전 출전 취소마를 빼고 예측
    t8 = today.strftime("%Y%m%d")
    have_x = {f.stem for f in (DATA / "extra").glob("*.json")} if (DATA / "extra").exists() else set()
    xd = [f.stem for f in ent_files if f.stem >= t8] + [f.stem for f in ent_files if f.stem < t8 and f.stem not in have_x][-4:]
    if xd:
        step("참고 정보", [sys.executable, str(ROOT / "pipeline" / "extra_site.py"), "--dates", ",".join(xd)], ROOT)
    cd_ = [f.stem for f in ent_files if f.stem >= t8]
    if cd_:     # 기수변경·말취소 (이유 포함) — 앞으로 열릴 날만
        step("기수변경·말취소", [sys.executable, str(ROOT / "pipeline" / "changes.py"), "--dates", ",".join(cd_)], ROOT)

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
            gone, void = pre_race_changes(d)
            if gone:      # 경주 전 출전 취소마는 빼고 예측 (같은 경주 다른 말과 비교하는 값·시뮬레이션이 맞게)
                rows = [r for r in rows if int(r.get("chulNo") or 0) not in gone.get(int(r.get("rcNo") or 0), ())]
                log(f"출전 취소 {d}: " + ", ".join(f"{rn}경주 {sorted(c)}번" for rn, c in sorted(gone.items())))
            sig = signature(rows, void)
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
                apply_changes(res, gone, void)
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
        for d in sorted(set(upcoming)):       # 조교 횟수 보정 (모델 확률에 곱함, 원래 값은 p0)
            try:
                apply_training(d)
            except Exception:
                log(f"조교 횟수 보정 실패: {d}")
                traceback.print_exc()
    elif not exporter:
        log("work/site_export.py 가 없어 예측은 건너뜁니다 (출전표만 사이트에 표시).")

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
