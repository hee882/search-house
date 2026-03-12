# [Analysis] 실거래가 DB 다변화 및 통계 고도화 갭 분석 (Check Phase)

## 1. 개요
Plan 문서에서 정의된 P0~P2 요구사항이 실제 코드에 얼마나 반영되었는지 점검합니다.

## 2. 요구사항 대비 구현율 분석

### 2.1 DB 스키마 확장 (P0)
- [x] **14개 신규 컬럼 추가**: apt_seq, apt_dong, dong_code, jibun, road_name, buyer_type, seller_type, cancel_deal_type, rgst_date, is_new_high_price 등 모두 구현. (100%)
- [x] **UNIQUE 제약 변경**: apt_seq 기반으로 정확도 향상. (100%)
- [x] **자동 마이그레이션**: 기존 스키마 감지 → v2 생성 → 데이터 복사 → 백업 → rename 로직 구현. (100%)

### 2.2 신고가 자동 태깅 (P0)
- [x] **check_new_high 함수**: apt_seq 우선, apt_name+dong_name 폴백 전략 구현. (100%)
- [x] **취소 거래 제외**: cancel_deal_day 존재 시 비교 대상에서 제외. (100%)
- [x] **INSERT 시점 자동 계산**: collector.py에서 저장 시 is_new_high_price 태깅. (100%)
- [x] **기존 데이터 backfill**: _backfill_new_high_prices 함수로 과거 데이터 일괄 처리. (100%)

### 2.3 인덱스 (P1)
- [x] **3개 인덱스 생성**: idx_stats, idx_new_high, idx_dong 모두 구현. (100%)

### 2.4 통계 API (P1)
- [x] **GET /api/stats/transactions**: 일별 거래량, 신고가 수, 취소 수, 매수자 유형 분포 반환. (100%)
- [x] **GET /api/stats/new-highs**: 신고가 매물 리스트 + 이전 최고가 + 상승률 반환. (100%)

### 2.5 다중 매물 타입 수집 (P2 — 의도적 후순위)
- [ ] **property_type/deal_type 컬럼**: 미구현 (P2 후순위로 의도적 보류)
- [ ] **오피스텔/연립다세대 수집**: 미구현 (P2 후순위로 의도적 보류)

## 3. 종합 평가 (Match Rate)
**P0/P1 범위 일치율: 100%**
**전체(P0~P2 포함) 일치율: 85%**

P0(스키마 확장, 신고가 태깅)과 P1(인덱스, 통계 API)은 완벽하게 구현. P2(다중 매물 타입)는 계획대로 후순위 보류.

## 4. 권장 후속 액션
- P0/P1 완료 확인. Report Phase로 진행.
- P2 다중 매물 타입은 별도 PDCA 사이클로 진행 권장.
