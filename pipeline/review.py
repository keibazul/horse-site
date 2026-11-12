"""끝난 경주일 복기 → site/data/review/날짜.json  (review.html 이 주말 단위로 묶어 보여 줌)

경주마다: 우승마와 모델 1순위·인기마의 확률·배당·착순, 초반 위치(예상 vs 실제), 마체중 변화,
참고 정보(기수 변경·최근 진료), 그리고 이 정보로 만든 짧은 '왜 빗나갔나' 메모.
메모는 데이터에서 기계적으로 뽑은 후보일 뿐이고 원인을 확정하지 않는다.

사용: python pipeline/review.py --missing   (예측 파일이 바뀐 지난 날만 다시)   또는 --date 20261107
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import blend_coef  # noqa: E402  (결합 계수: work/winner_history/blend.json)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data"


def load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ranks(d: dict[str, float], reverse=True) -> dict[str, int]:
    order = sorted(d, key=d.get, reverse=reverse)
    return {k: i + 1 for i, k in enumerate(order)}


def race_review(rno: str, r: dict, ent: dict, extra: dict, sim: dict | None) -> dict | None:
    res = r.get("result")
    if r.get("void"):
        return {"race": int(rno), "void": r["void"]}
    if not res:
        return None
    out = {str(x) for x in r.get("out", [])}
    p = {k: v for k, v in (r.get("p") or {}).items() if k not in out}
    od = {k: v for k, v in (r.get("odds") or {}).items() if k in p and v and v > 1}
    if not p:
        return None
    s = sum(p.values())
    p = {k: v / s for k, v in p.items()}
    have_odds = len(od) == len(p)
    q = comb = None
    if have_odds:
        si = sum(1 / v for v in od.values())
        q = {k: (1 / od[k]) / si for k in p}
        comb = blend_coef.combine(p, q)
    rk_m = ranks(p)
    rk_c = ranks(comb) if comb else {}
    rk_k = ranks(q) if q else {}
    fav = min(od, key=od.get) if have_odds else None
    fin = {str(n): i + 1 for i, n in enumerate(res)}
    hs = {str(h["no"]): h for h in (sim or {}).get("horses", [])}
    for k, h in hs.items():                      # 실제 착순 (4착 이하는 시뮬레이션 파일에서)
        o = (h.get("actual") or {}).get("ord")
        if o and k not in fin:
            fin[k] = int(o)
    # 초반(200m) 위치: 예상은 구간 모델 잔차 순서, 실제는 경주성적정보 통과 순위
    pe = {k: h["pred"]["s1f"] for k, h in hs.items() if k in p and h.get("pred", {}).get("s1f") is not None}
    early_pred = ranks(pe, reverse=False) if pe else {}
    early_act = {k: h["actual"]["cp"]["s1f"][0] for k, h in hs.items()
                 if (h.get("actual") or {}).get("cp", {}).get("s1f")}
    late_act = {k: h["actual"]["cp"]["g1f"][0] for k, h in hs.items()
                if (h.get("actual") or {}).get("cp", {}).get("g1f")}
    names = {str(int(e["chulNo"])): e for e in ent.get("rows", []) if int(e["rcNo"]) == int(rno)}
    n = len(p)

    def horse(k: str) -> dict:
        e = names.get(k, {})
        wg = (r.get("wg") or {}).get(k)
        x = (extra or {}).get(k, {})
        d = {"no": int(k), "name": e.get("hrName", ""), "jk": e.get("jkName", ""), "age": e.get("age"),
             "pm": round(p[k], 4), "rm": rk_m[k], "fin": fin.get(k)}
        if comb:
            d.update(pc=round(comb[k], 4), rc=rk_c[k], q=round(q[k], 4), rk=rk_k[k], odds=od[k])
        if wg:
            d["wg"] = wg
        if k in early_pred:
            d["ep"] = early_pred[k]
        if k in early_act:
            d["ea"] = early_act[k]
        if k in late_act:
            d["la"] = late_act[k]
        nprior = (r.get("n") or {}).get(k)
        if nprior is not None:
            d["np"] = nprior
        if x.get("spn"):
            d["spn"] = x["spn"]
        if x.get("trea"):
            d["trea"] = x["trea"][0]
        return d

    win = str(res[0])
    top = max(p, key=p.get)
    o = {"race": int(rno), "n": n, "dist": (sim or {}).get("dist") or (names.get(win, {}) or {}).get("rcDist"),
         "cls": (sim or {}).get("rank") or (names.get(win, {}) or {}).get("rank", ""),
         "track": (sim or {}).get("track", ""), "result": res[:3],
         "win": horse(win), "top": horse(top)}
    if fav:
        o["fav"] = horse(fav)
    if comb:
        o["ctop"] = int(max(comb, key=comb.get))
    o["loss"] = {"m": round(-math.log(max(p.get(win, 1e-9), 1e-9)), 4)}
    if comb:
        o["loss"].update(c=round(-math.log(max(comb[win], 1e-9)), 4), k=round(-math.log(max(q[win], 1e-9)), 4))
    o["notes"] = notes(o, n)
    return o


def pct(x):
    return f"{x * 100:.1f}%" if x < 0.1 else f"{x * 100:.0f}%"


def notes(o: dict, n: int) -> list[str]:
    """데이터에서 보이는 사실만 짧게 (원인 단정 안 함)"""
    w, t = o["win"], o["top"]
    out: list[str] = []
    hit = w["no"] == t["no"]
    if not hit:
        f = t.get("fin")
        out.append(f"모델 1순위 {t['no']}번 {t['name']}({pct(t['pm'])}) {f}착" if f else f"모델 1순위 {t['no']}번 {t['name']}({pct(t['pm'])})")
        if t.get("ep") and t.get("ea") and t["ea"] - t["ep"] >= 3:
            out.append(f"{t['no']}번은 초반 {t['ep']}위 예상이었지만 실제 {t['ea']}위로 뒤에서 출발")
        if t.get("wg") and t["wg"][0] and abs(t["wg"][1]) / max(t["wg"][0] - t["wg"][1], 1) >= 0.02:
            out.append(f"{t['no']}번 마체중 {t['wg'][1]:+d}kg ({t['wg'][1] / (t['wg'][0] - t['wg'][1]) * 100:+.1f}%)")
        if t.get("spn"):
            out.append(f"{t['no']}번 특이사항: {t['spn']}")
    # 우승마 쪽
    if not hit or (w.get("odds") or 0) >= 10:
        mk = f" · 인기 {w['rk']}위 {w['odds']}배" if w.get("odds") else ""
        out.append(f"우승 {w['no']}번 {w['name']}: 모델 {w['rm']}순위 {pct(w['pm'])}{mk}")
    if w.get("ea") and w.get("la"):
        if w["ea"] == 1 and w["la"] == 1:
            out.append(f"{w['no']}번이 처음부터 끝까지 선두")
        elif w["ea"] >= max(4, (n + 1) // 2):
            out.append(f"{w['no']}번이 초반 {w['ea']}위에서 따라잡음")
    if w.get("ep") and w.get("ea") and w["ep"] - w["ea"] >= 3:
        out.append(f"{w['no']}번은 초반 {w['ep']}위 예상보다 앞({w['ea']}위)에서 경주")
    if not hit and w.get("np") is not None and w["np"] <= 1:
        out.append(f"{w['no']}번은 이번이 {w['np'] + 1}번째 출전 (기록이 적어 모델 확신이 낮음)")
    if w.get("spn") and not hit:
        out.append(f"{w['no']}번 특이사항: {w['spn']}")
    return out


def build(date: str) -> dict | None:
    pred = load(DATA / "pred" / f"{date}.json")
    if not pred or not pred.get("backtestDone"):
        return None
    ent = load(DATA / "entries" / f"{date}.json") or {}
    extra = (load(DATA / "extra" / f"{date}.json") or {}).get("races", {})
    races = []
    for rno, r in sorted(pred["races"].items(), key=lambda x: int(x[0])):
        sim = load(DATA / "sim" / r["sim"]) if r.get("sim") else None
        x = race_review(rno, r, ent, extra.get(rno, {}), sim)
        if x:
            races.append(x)
    if not races:
        return None
    return {"date": date, "made": pred.get("made"), "model": pred.get("model"), "races": races}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", action="append", default=[])
    ap.add_argument("--missing", action="store_true")
    a = ap.parse_args()
    (DATA / "review").mkdir(parents=True, exist_ok=True)
    dates = list(a.date)
    if a.missing:
        for f in sorted((DATA / "pred").glob("*.json")):
            pr = load(f) or {}
            if not pr.get("backtestDone"):
                continue
            old = load(DATA / "review" / f"{f.stem}.json")
            if not old or old.get("made") != pr.get("made"):
                dates.append(f.stem)
    n = 0
    for d in dict.fromkeys(dates):
        o = build(d)
        if o:
            (DATA / "review" / f"{d}.json").write_text(json.dumps(o, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            n += 1
    print(f"복기: {n}일 작성")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
