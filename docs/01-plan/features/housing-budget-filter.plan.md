# [Plan] 소득 대비 주거비 한도 필터링

## Executive Summary

| 항목 | 내용 |
| ---- | ---- |
| Feature | housing-budget-filter |
| 시작일 | 2026-03-12 |
| 목표 | 연봉 기반 주거비 한도 설정으로 개인화된 추천 결과 제공 |

### Value Delivered

| 관점 | 내용 |
| ---- | ---- |
| **Problem** | 연봉을 바꿔도 결과가 거의 동일 - 항상 "가장 싼 곳"만 추천하여 실제 집 구하기에 무의미 |
| **Solution** | 월 소득 대비 주거비 비율(10%~40%) 게이지로 예산 범위를 설정하고, 예산 내 최적 가성비 단지를 추천 |
| **Function UX Effect** | 연봉 4000만 + 30% = 월 100만 한도 → 100만 이내 최적 단지 추천. 연봉 8000만 + 30% = 월 200만 한도 → 더 좋은 단지 추천 |
| **Core Value** | 연봉이 결과에 실질적으로 반영되어 개인화된 주거 의사결정 지원 |

## 1. 현황 분석

### 1.1 현재 문제

```
현재 비용 구조 (만원):
  고정비 = 월 주거비(보증금이자 + 월세) + 교통비(10만)
  숨은비용 = 시급 × 통근시간 × 피로가중치

  총 기회비용 = 고정비 + 숨은비용
  → 이 값이 낮은 순으로 정렬
```

**문제점**:
- 쿼리가 `ORDER BY cnt DESC LIMIT 3` → 거래 건수 많은 단지 3개만 반환
- 연봉/예산과 무관하게 항상 같은 3개 단지
- 연봉이 높을수록 숨은비용만 올라가고, 결과 순위는 동일
- 사용자 관점: "연봉을 바꿔도 똑같은 결과" → 서비스 가치 없음

### 1.2 사용자 기대 행동

| 연봉 | 주거비 한도 | 기대 결과 |
| ---- | ---- | ---- |
| 3000만 | 30% (75만/월) | 저렴한 전세/월세, 먼 거리도 허용 |
| 5000만 | 30% (125만/월) | 중간 가격대 전세, 적절한 거리 |
| 8000만 | 30% (200만/월) | 고급 전세/월세, 가까운 거리 우선 |
| 8000만 | 10% (67만/월) | 저렴하게, 먼 거리도 감수 |

## 2. 해결 방안

### 2.1 핵심 변경: 예산 기반 필터링

```
월 예산 = (연봉 × 10000 / 12) × housing_ratio

쿼리 변경:
  WHERE monthly_housing_cost <= 월 예산
  ORDER BY monthly_housing_cost DESC  -- 예산 내 최대 품질
  LIMIT 3
```

### 2.2 API 변경

```python
class OptimizeRequest(BaseModel):
    user1: UserProfile
    user2: Optional[UserProfile] = None
    mode: str = 'single'
    resident_type: str = 'buy'
    housing_ratio: float = 0.25  # 신규: 소득 대비 주거비 비율 (기본 25%)
```

### 2.3 쿼리 로직 변경

```python
def get_complexes_with_costs(city_code, salary1, time1, salary2=0, time2=0,
                             resident_type='rent', max_housing_budget=0):
    # max_housing_budget > 0이면 예산 필터링 적용
    # SQL에서 직접 필터링하기 어려우므로 (AVG 후 계산이라) 더 많이 가져와서 Python에서 필터
    cursor.execute('''
        SELECT apt_name, dong_name,
               AVG(deposit) as avg_deposit,
               AVG(monthly_rent) as avg_rent,
               COUNT(*) as cnt
        FROM rent_transactions
        WHERE city_code = ? AND deal_year >= 2024
        GROUP BY apt_name, dong_name
        HAVING cnt >= 2
        ORDER BY cnt DESC
        LIMIT 20
    ''', (city_code,))

    # Python에서 예산 필터링
    for row in rows:
        monthly_cost = round((avg_deposit * 0.04) / 12) + avg_rent
        if max_housing_budget > 0 and monthly_cost > max_housing_budget:
            continue  # 예산 초과
        # 예산 내 단지만 추가
```

### 2.4 UI 변경: 주거비 비율 게이지

```
[  10%  |  20%  |  25%  |  30%  |  40%  ]
         ^^^^^ 선택

"월 소득의 25%까지 (약 104만원)"
```

- 버튼 그룹 형태 (현재 교통수단 UI와 동일 패턴)
- 선택 시 아래에 계산된 월 예산 표시
- 커플 모드: 합산 연봉 기준

## 3. 구현 계획

| 파일 | 변경 | 내용 |
| ---- | ---- | ---- |
| `server/main.py` | **수정** | OptimizeRequest에 housing_ratio 추가, get_complexes_with_costs에 예산 필터 |
| `client/src/App.jsx` | **수정** | 주거비 비율 게이지 UI + API 호출 시 housing_ratio 전달 |

### 3.1 백엔드 변경 상세

1. `OptimizeRequest`에 `housing_ratio: float = 0.25` 추가
2. `get_complexes_with_costs()`에 `max_housing_budget` 파라미터 추가
3. SQL: `LIMIT 3` → `LIMIT 20` (더 많이 가져와서 필터링)
4. Python 필터: `monthly_cost <= max_housing_budget` 통과하는 것만 수집
5. 필터 후 `monthly_cost DESC`로 정렬 (예산 내 최대 품질)
6. 상위 3개 반환

### 3.2 프론트엔드 변경 상세

1. `inputs` state에 `housingRatio: 0.25` 추가
2. 연봉 입력 아래에 비율 버튼 그룹 (10%, 20%, 25%, 30%, 40%)
3. 선택된 비율 × 월 소득 = 월 예산 표시
4. API 호출 시 `housing_ratio` 파라미터 포함
5. 커플 모드: 합산 연봉 기준 표시

## 4. 검증 방법

1. 연봉 3000만 + 30% → 월 75만 이하 단지만 나오는지 확인
2. 연봉 8000만 + 30% → 월 200만 이하의 더 좋은 단지가 나오는지 확인
3. 같은 연봉에서 10% ↔ 40% 변경 시 결과가 확연히 달라지는지 확인
4. 예산 내 단지가 없는 역은 결과에서 제외되는지 확인
5. 커플 모드에서 합산 연봉 기준으로 동작하는지 확인
