# work/ — PC의 경마분석기 폴더를 옮겨 오는 곳

이 폴더에 예측 코드와 모델이 들어오면 자동 업데이트가 출전표마다 우승 확률과 전개 시뮬레이션을 만들어 사이트에 올립니다.
비어 있으면 사이트는 출전표와 (배당을 넣었을 때) 시장 확률만 보여 줍니다.

## 올릴 파일 (`C:\Users\zulst\Desktop\경마분석기` 기준, 폴더 구조 그대로)

| 파일 | 용도 |
|---|---|
| `predict_race.py`, `features_v5.py`, `race_feature_lib.py`, `race_feature_lib_v4.py`, `race_feature_lib_v5.py`, `bet_probs.py` | 우승 확률 |
| `simulate_race.py`, `train_sectional_model.py`, `train_win_model_v5.py` | 전개 시뮬레이션, 재학습 |
| `merge_to_excel.py`(폴더 최상위 것), `fetch_race_details.py` | 기록 갱신 |
| `winner_history/win_model_v5.joblib`, `winner_history/sect_model_v1.joblib` | 모델 |
| `race_details_all.csv.gz` | 경주성적정보 |
| `merged.csv` → **zip 으로 압축해서** `merged.zip` | 경주 기록 (GitHub 웹 업로드는 파일당 25MB 까지) |

**올리지 말 것:** `kra_race_collector.py`, `kra_race_collector_backup_20261101.py` — API 키가 코드에 들어 있습니다.
경주 결과 수집은 저장소 Secret(`KRA_API_KEY`)을 쓰는 새 수집기로 대신합니다.

## site_export.py

파일이 올라오면 `site_export.py` 를 만들어 `predict_race.py` / `simulate_race.py` 를 사이트 형식으로 연결합니다.
형식은 `pipeline/run_all.py` 맨 위 설명을 보세요.
