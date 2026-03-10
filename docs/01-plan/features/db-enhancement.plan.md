# DB Enhancement Plan — 실거래가 DB 다변화 및 통계 고도화

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | db-enhancement (실거래가 DB 다변화) |
| 작성일 | 2026-03-10 |
| 예상 규모 | Medium (DB 스키마 + collector + API 3개 파일 수정) |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | 현재 아파트 매매 데이터만 12개 필드로 저장, 타입 구분/신고가 판별/통계 조회 불가 |
| **Solution** | DB 스키마 확장 + 다중 매물 타입 수집 + 신고가 자동 태깅 + 통계 뷰/API |
| **Function UX Effect** | 구별·날짜별 거래 추이 시각화, 신고가 매물 하이라이트, 매매/전세 비교 가능 |
| **Core Value** | 단순 가격 조회 → 부동산 시장 인사이트 플랫폼으로 진화 |

---

## 1. 현재 상태 분석

### 1.1 현재 DB 스키마 (transactions 테이블)

| 컬럼 | 타입 | 설명 |
|------|------|------|
| city_code | TEXT | 시군구코드 (예: 11680) |
| dong_name | TEXT | 법정동명 |
| apt_name | TEXT | 아파트명 |
| exclusive_area | REAL | 전용면적 (㎡) |
| deal_amount | INTEGER | 거래금액 (만원) |
| deal_year | INTEGER | 거래년 |
| deal_month | INTEGER | 거래월 |
| deal_day | INTEGER | 거래일 |
| floor | INTEGER | 층 |
| build_year | INTEGER | 건축년도 |
| is_direct_deal | TEXT | 거래유형 (중개거래/직거래) |
| cancel_deal_day | TEXT | 해제사유발생일 |

**UNIQUE 제약**: `(dong_name, apt_name, exclusive_area, deal_year, deal_month, deal_day, floor)`

### 1.2 MOLIT API 전체 응답 필드 (32개)

현재 **미수집** 중인 유용 필드:

| API 필드 | 설명 | 활용도 |
|----------|------|--------|
| `aptSeq` | 아파트 고유 일련번호 | **신고가 판별 핵심** — 동일 단지 추적 식별자 |
| `buyerGbn` | 매수자 구분 (개인/법인) | 법인 매수 비율 통계 |
| `slerGbn` | 매도자 구분 (개인/법인) | 매도 패턴 분석 |
| `cdealType` | 해제여부 타입 | 취소 거래 필터링 |
| `umdCd` | 법정동코드 | 동 단위 정밀 집계 |
| `jibun` | 지번 | 주소 정밀도 향상 |
| `roadNm` | 도로명 | 도로명 주소 표시 |
| `rgstDate` | 등기일자 | 등기 지연 분석 |
| `aptDong` | 건물 동 번호 | 동별 시세 분석 |

### 1.3 현재 수집 범위

- **매물 타입**: 아파트 매매만 (1개 API 엔드포인트)
- **지역**: 서울 25개구 + 인천 10개구 + 경기 31개 시군 = 66개 지역
- **기간**: 월 단위 수집 (현재월 or 지정월)

---

## 2. 요구사항

### 2.1 핵심 요구사항

| # | 요구사항 | 우선순위 |
|---|----------|----------|
| R1 | 구별/날짜별 실거래 등록 건수 조회 (타입별 구분) | **P0** |
| R2 | 신고가 여부 자동 태깅 | **P0** |
| R3 | DB 스키마 확장 (미수집 유용 필드 추가) | **P1** |
| R4 | 다중 매물 타입 수집 (오피스텔, 연립다세대) | **P2** |
| R5 | 통계 API 엔드포인트 제공 | **P1** |

### 2.2 타입 구분 범위

MOLIT 공공데이터 API 엔드포인트별 매물 타입:

| 타입 | 거래종류 | API 엔드포인트 | 우선순위 |
|------|----------|---------------|----------|
| 아파트 | 매매 | `getRTMSDataSvcAptTradeDev` | **현재 수집 중** |
| 아파트 | 전세/월세 | `getRTMSDataSvcAptRent` | P2 |
| 오피스텔 | 매매 | `getRTMSDataSvcOffiTrade` | P2 |
| 오피스텔 | 전세/월세 | `getRTMSDataSvcOffiRent` | P2 |
| 연립다세대 | 매매 | `getRTMSDataSvcSHTrade` | P3 |
| 연립다세대 | 전세/월세 | `getRTMSDataSvcSHRent` | P3 |

---

## 3. 구현 계획

### Phase 1: DB 스키마 확장 + 신고가 태깅 (P0)

#### 3.1.1 스키마 마이그레이션

**transactions 테이블 확장 컬럼:**

```sql
-- 추가 컬럼
apt_seq TEXT,           -- 아파트 고유번호 (신고가 판별 키)
property_type TEXT DEFAULT 'apt',  -- 매물 타입: apt, officetel, row_house
deal_type TEXT DEFAULT 'trade',    -- 거래종류: trade(매매), rent(전세), monthly(월세)
buyer_type TEXT,        -- 매수자 구분 (개인/법인)
seller_type TEXT,       -- 매도자 구분
cancel_deal_type TEXT,  -- 해제여부 타입
dong_code TEXT,         -- 법정동코드
jibun TEXT,             -- 지번
road_name TEXT,         -- 도로명
apt_dong TEXT,          -- 건물 동 번호
rgst_date TEXT,         -- 등기일자
is_new_high_price INTEGER DEFAULT 0,  -- 신고가 여부 (0/1)
deposit INTEGER,        -- 보증금 (전세/월세용, 만원)
monthly_rent INTEGER,   -- 월세 (월세용, 만원)
```

**UNIQUE 제약 변경:**
```sql
UNIQUE(apt_seq, exclusive_area, deal_year, deal_month, deal_day, floor, property_type, deal_type)
```
- `apt_seq` 기반으로 변경하여 동일 단지 추적 정확도 향상
- `property_type`, `deal_type` 추가로 다중 타입 지원

#### 3.1.2 신고가 판별 로직

```python
# 저장 시점에 자동 계산
def is_new_high(cursor, apt_seq, exclusive_area, deal_amount):
    cursor.execute('''
        SELECT MAX(deal_amount) FROM transactions
        WHERE apt_seq = ? AND exclusive_area = ?
        AND cancel_deal_day IS NULL
    ''', (apt_seq, exclusive_area))
    max_price = cursor.fetchone()[0]
    return 1 if (max_price is None or deal_amount > max_price) else 0
```

**판별 기준:**
- 동일 `apt_seq` + `exclusive_area` 조합에서 역대 최고가 초과 시 `is_new_high_price = 1`
- 취소 거래(`cancel_deal_day` 존재)는 비교 대상에서 제외
- INSERT 시점에 계산하여 저장 (조회 시 매번 계산 불필요)

#### 3.1.3 인덱스 추가

```sql
-- 구별/날짜별 통계 조회용
CREATE INDEX idx_stats ON transactions(city_code, deal_year, deal_month, property_type, deal_type);

-- 신고가 조회용
CREATE INDEX idx_new_high ON transactions(apt_seq, exclusive_area, deal_amount);

-- 동별 집계용
CREATE INDEX idx_dong ON transactions(city_code, dong_code, deal_year, deal_month);
```

### Phase 2: 통계 API (P1)

#### 3.2.1 구별/날짜별 거래 건수 API

```
GET /api/stats/transactions?city_code=11680&year=2026&month=3
```

**응답 예시:**
```json
{
  "city_code": "11680",
  "city_name": "강남구",
  "period": "2026-03",
  "summary": {
    "total": 245,
    "by_type": {
      "apt_trade": 180,
      "apt_rent": 45,
      "officetel_trade": 15,
      "officetel_rent": 5
    },
    "new_high_count": 23,
    "cancel_count": 8
  },
  "daily": [
    {"day": 1, "count": 12, "new_high": 2},
    {"day": 2, "count": 8, "new_high": 1}
  ]
}
```

#### 3.2.2 신고가 매물 조회 API

```
GET /api/stats/new-highs?city_code=11680&limit=20
```

**응답 예시:**
```json
{
  "items": [
    {
      "apt_name": "래미안",
      "dong_name": "역삼동",
      "exclusive_area": 84.5,
      "deal_amount": 280000,
      "prev_high": 265000,
      "increase_rate": 5.66,
      "deal_date": "2026-03-05"
    }
  ]
}
```

### Phase 3: 다중 매물 타입 수집 (P2, 후순위)

- collector.py에 API 엔드포인트 매핑 테이블 추가
- `property_type`, `deal_type` 태깅하여 동일 테이블에 저장
- 전세/월세는 `deposit`, `monthly_rent` 컬럼 활용

---

## 4. 마이그레이션 전략

### 4.1 기존 데이터 보존 방식

```python
# 1. 새 테이블 생성
CREATE TABLE transactions_v2 (...);

# 2. 기존 데이터 복사 (기본값 적용)
INSERT INTO transactions_v2 (기존컬럼들, property_type, deal_type)
SELECT 기존컬럼들, 'apt', 'trade' FROM transactions;

# 3. 기존 테이블 백업 후 교체
ALTER TABLE transactions RENAME TO transactions_backup;
ALTER TABLE transactions_v2 RENAME TO transactions;

# 4. 신고가 일괄 계산 (기존 데이터)
UPDATE transactions SET is_new_high_price = 1
WHERE deal_amount = (
    SELECT MAX(t2.deal_amount) FROM transactions t2
    WHERE t2.apt_seq = transactions.apt_seq
    AND t2.exclusive_area = transactions.exclusive_area
    AND t2.cancel_deal_day IS NULL
);
```

### 4.2 호환성

- `main.py`의 기존 쿼리는 새 컬럼 무시하므로 즉시 호환
- `property_type = 'apt'`, `deal_type = 'trade'` 기본값으로 기존 로직 유지
- 프론트엔드는 새 API를 점진적으로 연동

---

## 5. 파일 변경 범위

| 파일 | 변경 내용 | 난이도 |
|------|----------|--------|
| `server/collector.py` | 스키마 마이그레이션, 필드 추가 수집, 신고가 계산, 다중 타입 | Medium |
| `server/main.py` | 통계 API 2개 추가 (`/api/stats/transactions`, `/api/stats/new-highs`) | Easy |
| `server/data/search_house.db` | 스키마 마이그레이션 후 재수집 필요 | Auto |

---

## 6. 리스크 및 고려사항

| 리스크 | 대응 |
|--------|------|
| 기존 DB 데이터 손실 | transactions_backup 테이블로 백업 후 마이그레이션 |
| API 호출량 증가 (다중 타입) | Phase 3는 후순위, 필요시 rate limit 조절 |
| 신고가 판별 정확도 | apt_seq 없는 기존 데이터는 apt_name+dong_name 기반 폴백 |
| GitHub Actions 실행 시간 증가 | 현재 ~1분 → 다중 타입 시 ~3분 예상 (허용 범위) |

---

## 7. 구현 순서 (권장)

```
Step 1: DB 스키마 마이그레이션 (collector.py init_db 수정)
Step 2: collector.py 필드 추가 수집 + 신고가 로직
Step 3: 기존 데이터 재수집 (202401~ 현재)
Step 4: main.py 통계 API 추가
Step 5: (선택) 다중 매물 타입 확장
Step 6: (선택) 프론트엔드 통계 대시보드 연동
```
