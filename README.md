# horse-site — 서울 경주 예측

렛츠런파크 서울의 다음 경주에서 말별 우승 확률과 승식별 조합 확률을 보여 주는 사이트입니다.
GitHub Actions 가 출전표 수집부터 예측, 사이트 배포까지 자동으로 돌립니다.

## 자동 실행 시각 (한국 시간)

| 언제 | 무엇 |
|---|---|
| 목·금 18:07 | 출전표 수집 → 예측 → 사이트 갱신 |
| 토·일 07:17, 12:17 | 당일 출전표(취소 반영)로 다시 예측 |
| 월 09:27 | 주말 결과로 경주 기록 갱신 |

Actions 탭의 **update-site → Run workflow** 로 언제든 직접 돌릴 수 있습니다.

## 구성

```
pipeline/   kra_api.py(API 호출), fetch_entries.py(출전표), run_all.py(전체 순서)
site/       index.html(예측 화면), sim.html(전개 시뮬레이터), data/(자동 생성)
work/       PC 경마분석기 폴더의 예측 코드·모델 (work/README.md)
```

## 처음 한 번 설정

1. **Secret**: Settings → Secrets and variables → Actions → `KRA_API_KEY` (data.go.kr 일반 인증키 Encoding). 이미 등록됨.
2. **Pages**: Settings → Pages → Source 를 **GitHub Actions** 로. 무료 계정은 공개 저장소에서만 Pages 를 쓸 수 있습니다.
3. **예측 코드**: `work/README.md` 의 파일을 `work/` 에 올립니다.

## 사이트에서 하는 일

- 경주마다 모델 우승 확률. 경주 직전 KRA 앱의 단승 배당을 모두 넣으면 결합 확률 (α 0.1689, β 0.9219).
- 승식 7가지의 상위 조합 확률과 적정(손익분기) 배당. 하빌 방식, 2착 0.8·3착 0.7 보정.
- 전개 시뮬레이션 (예측 파일이 있을 때).
- 과거 백테스트에서 꾸준히 100%를 넘긴 전략은 없었습니다. 수익을 보장하지 않습니다.
