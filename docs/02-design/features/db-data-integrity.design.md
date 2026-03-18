# [Design] 데이터 무결성 및 정합성 고도화 — 가격 왜곡 방지 로직

## Executive Summary

| 항목 | 내용 |
| ---- | ---- |
| Feature | db-data-integrity |
| 시작일 | 2026-03-16 |
| 목표 | 아웃라이어 및 임대단지 데이터를 필터링하여 실거래가 데이터의 무결성 및 정합성 확보 |

### Value Delivered

| 관점 | 내용 |
| ---- | ---- |
| **Problem** | 소규모 단지, 공공임대, 특수 거래 등 아웃라이어 데이터가 평균가를 왜곡하여 사용자 의사결정에 혼선 초래 |
| **Solution** | 임대 단지 키워드 필터링, 최소 거래 건수 강화, 아웃라이어 제거 로직(Trimmed Mean) 도입 |
| **Function UX Effect** | "너무 싼 집" 또는 "말도 안 되게 비싼 집"이 필터링되어 현실적인 주거 예산 가이드 제공 |
| **Core Value** | 데이터의 신뢰성 확보를 통한 서비스 전문성 및 사용자 만족도 증대 |

## 1. 아키텍처 및 상세 설계

### 1.1 데이터 필터링 키워드 (Blacklist)
단지명(`apt_name`)에 다음 패턴이 포함될 경우 검색 결과에서 제외합니다.
- `임대`, `행복주택`, `LH`, `SH`, `국민주택`, `영구임대`, `공공임대`, `도시형`, `기숙사`, `쉐어하우스`

### 1.2 통계적 정제 방식 (Outlier Removal)
- **Trimmed Mean:** 데이터가 10건 이상일 경우 상하위 10%를 제거한 후 평균을 계산합니다.
- **Volume Filter:** 5건 미만의 거래가 있는 단지는 신뢰도가 낮아 후보군에서 하위 랭킹으로 조정하거나 제외합니다.
- **Median Fallback:** 거래가 5건 이하일 경우 평균값(`AVG`) 대신 중앙값(`MEDIAN`)을 사용하여 단일 아웃라이어의 영향을 최소화합니다.

## 2. 인터페이스 및 데이터 스키마

### 2.1 SQL 쿼리 개선 (1차 필터링)
```sql
-- server/main.py 내 쿼리에 추가될 구문 예시
WHERE apt_name NOT LIKE '%임대%'
  AND apt_name NOT LIKE '%행복주택%'
  AND apt_name NOT LIKE '%LH%'
  AND apt_name NOT LIKE '%SH%'
  AND apt_name NOT LIKE '%공공임대%'
```

### 2.2 Python 데이터 처리 함수
```python
def get_clean_average(prices: list):
    """
    아웃라이어를 제거한 정제된 평균값을 반환함.
    상하위 10%를 제외한 Trimmed Mean 산출.
    """
    if not prices: return 0
    if len(prices) < 5: return sum(prices) / len(prices)
    
    prices.sort()
    n = len(prices)
    trim_count = max(1, n // 10) # 10% 트리밍
    trimmed_prices = prices[trim_count:-trim_count]
    return sum(trimmed_prices) / len(trimmed_prices)
```

## 3. 구현 단계별 상세

### Phase 1: SQL 레벨 필터링 강화
- `rent_transactions` 조회 시 블랙리스트 키워드를 명시적으로 제외합니다.
- `HAVING COUNT(*) >= 5`를 기본으로 하되, 결과가 없을 경우 단계적으로 완화하는 로직을 구현합니다.

### Phase 2: 비즈니스 로직 고도화
- 서버 내부 메모리에서 데이터를 그룹화할 때 `get_clean_average` 함수를 호출하여 평균가를 산출합니다.
- 단일 거래가가 비정상적으로 높거나 낮은 경우를 감지하여 로그를 남기도록 합니다.

## 4. 보안 및 성능 고려사항
- **성능:** SQL 레벨에서 `NOT LIKE` 연산은 인덱스를 타지 않을 수 있으므로, 단지명이 10만 건 이상일 경우 성능 저하 우려가 있으나 현재 수도권 3만 개 수준에서는 무방함.
- **확장성:** 블랙리스트 키워드를 별도 설정 파일이나 DB 테이블로 관리하여 코드 수정 없이 업데이트 가능하도록 설계.
