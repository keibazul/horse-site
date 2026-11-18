"""베팅 계획 '지난 경주일 연습 보기'용 확률 (2026-11-18)
지금 배당 반영 모델은 2026-11-08 까지 학습했으므로 그 전 경주일을 이 모델로 계산하면 답을 본 셈이 됨 → 연습 보기가 11/14 부터만 됐음.
대신 과거 검증과 같은 연도별 표본외 확률(그 전 해까지 학습한 모델, 확정 단승 배당 사용; work/backtest/mkt_win.json.gz)을 날마다 꺼내 둠.
출력: site/data/plan_past/날짜.json = {source, races: {경주: {번호: 확률}}}  (말 특징 site/data/mkx 가 없는 지난 경주일만)
run_all.write_index 가 파일이 있으면 index.json days[].pp = true.
사용: python work/export_plan_past.py
"""
import gzip
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "site", "data")
D = json.load(gzip.open(os.path.join(HERE, "backtest", "mkt_win.json.gz"), "rt", encoding="utf-8"))
idx = json.load(open(os.path.join(DATA, "index.json"), encoding="utf-8"))
out = os.path.join(DATA, "plan_past")
os.makedirs(out, exist_ok=True)
n = 0
for it in idx["days"]:
    d = it["date"]
    if not it.get("past") or d not in D or os.path.exists(os.path.join(DATA, "mkx", f"{d}.json")):
        continue
    doc = {"source": "연도별 표본외 배당 반영 확률 (그 전 해까지 학습한 모델, 확정 단승 배당)", "races": {k: r["p"] for k, r in sorted(D[d].items(), key=lambda x: int(x[0]))}}
    with open(os.path.join(out, f"{d}.json"), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"))
    n += 1
print(f"{out}: {n}일")
