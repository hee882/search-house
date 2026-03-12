# [Design] 실거래가 DB 다변화 및 통계 고도화

## 1. 아키텍처 및 폴더 구조 (변경 대상)

```text
server/
├── collector.py         // 스키마 마이그레이션 + 14개 신규 필드 수집 + 신고가 태깅
├── main.py              // 통계 API 2개 추가 (/api/stats/transactions, /api/stats/new-highs)
└── data/
    └── search_house.db  // transactions 테이블 v2 스키마 + 인덱스 3개
```

## 2. DB 스키마 설계 (transactions v2)

기존 12개 컬럼에서 24개로 확장. 추가 컬럼:

```sql
apt_seq TEXT,                          -- 아파트 고유번호 (신고가 판별 핵심 키)
apt_dong TEXT,                         -- 건물 동 번호
dong_code TEXT,                        -- 법정동코드
jibun TEXT,                            -- 지번
road_name TEXT,                        -- 도로명
buyer_type TEXT,                       -- 매수자 구분 (개인/법인)
seller_type TEXT,                      -- 매도자 구분
cancel_deal_type TEXT,                 -- 해제여부 타입
rgst_date TEXT,                        -- 등기일자
is_new_high_price INTEGER DEFAULT 0,   -- 신고가 여부 (0/1, INSERT 시 자동 계산)
```

**UNIQUE 제약**: `(city_code, apt_seq, exclusive_area, deal_year, deal_month, deal_day, floor)`

## 3. 신고가 자동 태깅 로직

```python
def check_new_high(cursor, apt_seq, apt_name, dong_name, exclusive_area, deal_amount):
    # apt_seq 있으면 apt_seq 기준, 없으면 apt_name+dong_name 폴백
    # 취소 거래(cancel_deal_day) 제외하고 MAX(deal_amount) 비교
    # deal_amount > max_price → is_new_high_price = 1
```

## 4. 마이그레이션 전략

1. 기존 테이블 스키마 자동 감지 (`apt_seq` 컬럼 유무)
2. transactions_v2 생성 → 기존 데이터 복사 → 기존 테이블 백업 → v2를 transactions로 rename
3. 기존 데이터 신고가 일괄 backfill

## 5. 통계 API 설계

### GET /api/stats/transactions?city_code=&year=&month=
- 일별 거래 건수, 신고가 건수, 취소 건수, 매수자 유형별 분포 반환

### GET /api/stats/new-highs?city_code=&limit=20
- 신고가 매물 리스트 (이전 최고가, 상승률 포함)

## 6. 인덱스

```sql
CREATE INDEX idx_stats ON transactions(city_code, deal_year, deal_month);
CREATE INDEX idx_new_high ON transactions(apt_seq, exclusive_area, deal_amount);
CREATE INDEX idx_dong ON transactions(city_code, dong_code, deal_year, deal_month);
```
