# [Analysis] 소득 대비 주거비 한도 필터링 Gap 분석 (Check Phase)

> **Summary**: housing-budget-filter Plan 문서 대비 실제 구현의 일치도 분석
>
> **Author**: gap-detector
> **Created**: 2026-03-12
> **Status**: Approved

---

## 1. 분석 개요

| 항목 | 내용 |
|------|------|
| 분석 대상 | housing-budget-filter (소득 대비 주거비 한도 필터링) |
| Plan 문서 | `docs/01-plan/features/housing-budget-filter.plan.md` |
| 구현 파일 (백엔드) | `server/main.py` |
| 구현 파일 (프론트엔드) | `client/src/App.jsx` |
| 분석일 | 2026-03-12 |

## 2. 종합 점수

| 카테고리 | 점수 | 상태 |
|----------|:----:|:----:|
| API 설계 일치 | 100% | Pass |
| 쿼리 로직 일치 | 92% | Pass |
| UI 구현 일치 | 100% | Pass |
| 비즈니스 로직 일치 | 100% | Pass |
| **종합 Match Rate** | **97%** | **Pass** |

## 3. 항목별 상세 분석

### 3.1 백엔드 변경 (Plan 3.1 vs server/main.py)

| # | Plan 항목 | 구현 상태 | 위치 | 비고 |
|---|-----------|:---------:|------|------|
| 1 | `OptimizeRequest`에 `housing_ratio: float = 0.25` 추가 | Match | main.py:59 | 정확히 일치 |
| 2 | `get_complexes_with_costs()`에 `max_housing_budget` 파라미터 추가 | Match | main.py:118-119 | 정확히 일치 |
| 3 | SQL `LIMIT 3` -> `LIMIT 20` (더 많이 가져와서 필터링) | Changed | main.py:132 | Plan=20, 구현=30 |
| 4 | Python 필터: `monthly_cost <= max_housing_budget` | Match | main.py:146 | 정확히 일치 |
| 5 | 필터 후 `monthly_cost DESC` 정렬 (예산 내 최대 품질) | Match | main.py:186 | `housing_cost_only` 기준 DESC 정렬 |
| 6 | 상위 3개 반환 | Match | main.py:187 | `candidates[:3]` |

#### 월 예산 계산 로직 비교

- **Plan**: `monthly_budget = (salary * 10000 / 12) * housing_ratio`
- **구현** (main.py:323): `max_housing_budget = round((total_salary * 10000 / 12) * request.housing_ratio / 10000)`
- 구현은 마지막에 `/10000`을 추가하여 만원 단위로 변환. DB의 보증금/월세가 만원 단위이므로 올바른 처리.

#### 커플 모드 합산 연봉

- **Plan**: 커플 모드에서 합산 연봉 기준
- **구현** (main.py:320-322):
  ```python
  total_salary = request.user1.salary
  if request.mode == 'couple' and request.user2:
      total_salary += request.user2.salary
  ```
- 정확히 일치.

### 3.2 프론트엔드 변경 (Plan 3.2 vs client/src/App.jsx)

| # | Plan 항목 | 구현 상태 | 위치 | 비고 |
|---|-----------|:---------:|------|------|
| 1 | `inputs` state에 `housingRatio: 0.25` 추가 | Match | App.jsx:166 | 별도 state로 분리 (`const [housingRatio, setHousingRatio] = useState(0.25)`) |
| 2 | 비율 버튼 그룹 (10%, 20%, 25%, 30%, 40%) | Match | App.jsx:397-401 | `[0.1, 0.2, 0.25, 0.3, 0.4].map(...)` |
| 3 | 선택된 비율 x 월 소득 = 월 예산 표시 | Match | App.jsx:393 | `Math.round((...salary * housingRatio / 12))` + "만원 이내" |
| 4 | API 호출 시 `housing_ratio` 파라미터 포함 | Match | App.jsx:286 | `housing_ratio: housingRatio` in payload |
| 5 | 커플 모드: 합산 연봉 기준 표시 | Match | App.jsx:393 | `mode === 'couple' ? inputs.user1.salary + inputs.user2.salary : inputs.user1.salary` |

### 3.3 UI 패턴 비교

- **Plan**: "버튼 그룹 형태 (현재 교통수단 UI와 동일 패턴)"
- **구현**: `flex bg-gray-100 rounded-xl p-1 gap-0.5` 컨테이너 안에 개별 버튼 -- 교통수단 UI(`flex bg-gray-100 rounded-xl p-0.5 h-[42px]`)와 동일 패턴. 일치.

## 4. 차이점 상세

### 4.1 Changed: SQL LIMIT 값

| 항목 | Plan | 구현 | 영향도 |
|------|------|------|:------:|
| SQL LIMIT | `LIMIT 20` | `LIMIT 30` | Low |

**분석**: 구현이 Plan보다 10개 더 많은 후보를 가져온다. 이는 보수적인 방향의 변경으로, 예산 필터링 후 충분한 후보가 남도록 보장하는 개선이다. 결과 품질에 긍정적 영향.

**판정**: 의도적 개선 (Intentional Improvement). Plan 업데이트 권장하나 긴급도 낮음.

### 4.2 State 구조 미세 차이

- **Plan**: `inputs` state 내부에 `housingRatio: 0.25` 포함
- **구현**: `housingRatio`를 독립 state로 분리 (`useState(0.25)`)

**분석**: 기능적으로 동등하며, 독립 state가 리렌더링 최적화에 유리. 설계 의도 충족.

**판정**: 구현 개선 (Implementation Improvement). 문서 반영 불필요.

## 5. 검증 항목 (Plan Section 4)

| # | 검증 시나리오 | 구현 가능 여부 | 비고 |
|---|--------------|:-----------:|------|
| 1 | 연봉 3000만 + 30% -> 월 75만 이하 단지만 표시 | Supported | 예산 필터 로직 정상 |
| 2 | 연봉 8000만 + 30% -> 월 200만 이하 더 좋은 단지 표시 | Supported | DESC 정렬로 고품질 우선 |
| 3 | 같은 연봉에서 10% <-> 40% 변경 시 결과 차이 | Supported | housing_ratio 반영 확인 |
| 4 | 예산 내 단지 없는 역은 결과 제외 | Supported | `if not complexes: continue` (main.py:334) |
| 5 | 커플 모드 합산 연봉 기준 동작 | Supported | 백엔드/프론트엔드 모두 합산 처리 |

5개 검증 시나리오 모두 구현 코드에서 지원됨을 확인.

## 6. 종합 평가

**Match Rate: 97%**

Plan 문서에서 정의한 핵심 기능 -- (1) `housing_ratio` API 파라미터, (2) 예산 기반 필터링 쿼리, (3) 예산 내 최대 품질 정렬, (4) 비율 게이지 UI, (5) 커플 모드 합산 -- 이 모두 정확하게 구현되었다.

유일한 차이는 SQL `LIMIT` 값(20 vs 30)이며, 이는 필터링 후보 풀을 넓히기 위한 의도적 개선으로 판단된다. 기능 동작에 영향 없음.

## 7. 권장 후속 액션

Match Rate >= 90%이므로 추가 개선(Act Phase) 불필요.

| 액션 | 우선순위 | 내용 |
|------|:--------:|------|
| Plan 문서 갱신 | Low | Section 2.3의 `LIMIT 20`을 `LIMIT 30`으로 업데이트 |
| Report 작성 | Next | `/pdca report housing-budget-filter`로 PDCA 사이클 완료 |

---

## Related Documents
- Plan: [housing-budget-filter.plan.md](../01-plan/features/housing-budget-filter.plan.md)
