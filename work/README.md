# work/ — 예측 코드·모델 (PC 경마분석기 폴더에서 옮겨 옴)

| 파일 | 하는 일 |
|---|---|
| `site_export.py` | 사이트용 예측: 출전표 → v5 우승 확률 + 경주별 전개 시뮬레이션 (`pipeline/run_all.py` 가 호출) |
| `update_history.py` | 경주 기록 갱신: `merged.zip` + `results/rr_*.csv` → `merged.csv`, 새 경주일의 경주결과(API299)·경주성적정보(API214_1) 받기 |
| `predict_race.py`, `features_v5.py`, `race_feature_lib*.py`, `bet_probs.py` | v5 예측 (PC 와 같은 코드) |
| `simulate_race.py`, `train_sectional_model.py` | 전개 시뮬레이션 |
| `train_win_model_v5.py` | 재학습 |
| `merge_to_excel.py`, `fetch_race_details.py` | PC 용 수집 도구 (자동 업데이트에서는 `update_history.py` 가 대신함) |
| `winner_history/*.joblib` | 모델 (numpy 2.5.3 · scikit-learn 1.9.1 · joblib 1.6.0 · pandas 3.0.5) |
| `merged.zip` | 경주 기록 2000-01-08 ~ 2026-10-31 (그 뒤는 `results/`) |
| `race_details_all.csv.gz` | 경주성적정보 ~2026-10-31 (그 뒤는 `race_details/`) |

`merged.csv` 는 실행할 때 만들어지는 파일이라 저장소에 올리지 않습니다.
PC 의 `kra_race_collector.py` 는 저장소에 두지 않습니다 (자동 업데이트에 필요 없음).
