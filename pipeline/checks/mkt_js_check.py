"""배당 반영 모델: 학습한 sklearn 모델과 브라우저 계산(site/assets/mktmodel.js)이 같은 확률을 내는지 확인

자료: site/data/mkx/날짜.json(말마다 v5 특징 93개, 범주는 OrdinalEncoder 코드) + site/data/pred/날짜.json 의 확정 단승 배당.
배당이 같은 말이 있을 때 인기 순위(동률은 출전 번호 순)가 두 쪽에서 같은지 보려고, 경주마다 배당 일부를 같은 값으로 바꾼 시험도 함.
사용: python pipeline/checks/mkt_js_check.py [--model work/winner_history/win_mkt_v1.joblib] [--json site/data/model/mkt_v1.json]
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile

import joblib
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "work"))
import train_mkt_model as tm  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--model", default=os.path.join(ROOT, "work", "winner_history", "win_mkt_v1.joblib"))
ap.add_argument("--json", default=os.path.join(ROOT, "site", "data", "model", "mkt_v1.json"))
a = ap.parse_args()
art = joblib.load(a.model)
clf = art["model"].named_steps["clf"]

cases = []      # (이름, 번호들, 특징들, 배당)
for f in sorted(glob.glob(os.path.join(ROOT, "site", "data", "mkx", "*.json"))):
    d = os.path.basename(f)[:8]
    pf = os.path.join(ROOT, "site", "data", "pred", d + ".json")
    if not os.path.exists(pf):
        continue
    X = json.load(open(f)); P = json.load(open(pf))
    for n, xs in X["races"].items():
        od = (P["races"].get(n) or {}).get("odds") or {}
        ids = sorted([i for i in xs if i in od and od[i] and od[i] > 1], key=int)
        if len(ids) < 5:
            continue
        o = [float(od[i]) for i in ids]
        cases.append((f"{d}-{n}", ids, [xs[i] for i in ids], o))
        t = list(o)                                   # 동률 시험: 2·3·4번째 말(번호 순)의 배당을 1번째와 같게, 마지막 두 말끼리 같게
        for k in (1, 2, 3):
            t[k] = t[0]
        t[-1] = t[-2]
        cases.append((f"{d}-{n}-동률", ids, [xs[i] for i in ids], t))

# 파이썬: train_mkt_model.market_features (rank_desc) + sklearn
py = []
for name, ids, xs, o in cases:
    df = pd.DataFrame({"chulNo": [int(i) for i in ids]})
    rid = pd.Series(["r"] * len(ids)); odds = pd.Series(o)
    mk = tm.market_features(df, rid, odds)[tm.MK].to_numpy()
    x = np.hstack([np.array([[np.nan if v is None else v for v in r] for r in xs], dtype=float), mk])
    p = clf.predict_proba(x)[:, 1]
    py.append(p / p.sum())

# 브라우저: node 로 mktmodel.js
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
    # 동률 시험은 번호를 거꾸로 넘김 (브라우저가 넘긴 순서가 아니라 출전 번호로 동률을 가르는지)
    json.dump([{"ids": ids[::-1] if "동률" in nm else ids, "xs": dict(zip(ids, xs)), "odds": dict(zip(ids, o)), "want": ids} for nm, ids, xs, o in cases], fh)
    tmp = fh.name
js = f"""
const MK = require({json.dumps(os.path.join(ROOT, "site", "assets", "mktmodel.js"))});
const M = JSON.parse(require("fs").readFileSync({json.dumps(a.json)}, "utf8"));
const C = JSON.parse(require("fs").readFileSync({json.dumps(tmp)}, "utf8"));
console.log(JSON.stringify(C.map(c => {{ const r = MK.predict(M, c.xs, c.odds, c.ids); return c.want.map(i => r[i]); }})));
"""
out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
os.unlink(tmp)
M = json.load(open(a.json))
diff = np.array([np.max(np.abs(np.array(j) - p)) for j, p in zip(out, py)])
tie = np.array(["동률" in c[0] for c in cases])
print(f"모델 {a.model} (~{art['trained_through']}, 트리 {art['n_trees']}) / 브라우저 {a.json} (~{M['trained_through']}, 트리 {len(M['trees'])})")
print(f"경주 {int((~tie).sum())} (말 {sum(len(c[1]) for c, t in zip(cases, tie) if not t)}): 최대 차이 {diff[~tie].max():.2e}")
print(f"동률 시험 {int(tie.sum())}경주: 최대 차이 {diff[tie].max():.2e}")
sys.exit(0 if diff.max() < 1e-12 else 1)
