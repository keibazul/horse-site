# 물리엔진 세기 검증

- `pace_data.py` (저장소 맨 위에서 `python pipeline/checks/pace_data.py`): 2015~ 경주성적정보로
  "초반 상위 3두 200m 기록 − 보통(E)" 과 "600m 전 상위 3두의 마지막 600m 상대 기록(F)"의 관계, 선두 다툼 두수 효과.
  2026-11-04: F = 0.290 − 0.473·E, 선두 다툼 1두당 +0.037초, 초반 0.2초 안 말 수 평균 3.16.
- `physics_calib.js` (`node pipeline/checks/physics_calib.js '{"races":700,"draws":4}'`): 지난 경주 시뮬레이션 파일로
  `site/physics.js` 를 돌려 같은 지표 계산. `{"physics":false}` 는 말끼리 영향 없는 이전 방식.
  2026-11-04 기본값(MATCH 0.8, LAMBDA 1.5, BIAS 0.007): F = 0.463 − 0.467·E, 다툼 +0.025, 3.44두, 결승 기록 차 +0.01초.
