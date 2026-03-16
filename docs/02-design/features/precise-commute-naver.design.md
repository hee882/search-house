# [Design] 네이버 API 비용 최적화 기반 정밀 통근 분석 아키텍처

## 1. 개요 (Overview)
상용 서비스 운영을 위해 네이버 Cloud Platform API 호출 비용을 최소화하면서, 사용자에게는 실제 길찾기 기반의 정확한 기회비용 데이터를 제공하는 것을 목표로 함.

## 2. 아키텍처 설계 (Architecture)

### 2.1 하이브리드 통근시간 계산 모델
1.  **Walking Section (단지 → 인근역):**
    - 방식: 하버사인 직선거리 기반 산식 적용 (1km 당 12분)
    - 비용: 0원
2.  **Transit Section (인근역 → 직장):**
    - 방식: **Naver Direction API** (자차) 또는 **대중교통 API** 호출
    - 최적화: 캐시 테이블 우선 조회 후 미존재 시에만 API 호출

### 2.2 캐시 데이터베이스 스키마
`commute_cache` 테이블을 생성하여 API 호출 결과를 영구 저장.
- `from_lat`, `from_lng`: 출발지(역) 좌표
- `to_lat`, `to_lng`: 목적지(직장) 좌표
- `transport_mode`: public / car
- `duration_min`: 소요 시간 (분)
- `distance_km`: 실제 주행/이동 거리
- `updated_at`: 데이터 신선도 관리를 위한 타임스탬프

## 3. 비용 관리 (Cost Management)

### 3.1 호출 제한 정책 (Throttling)
- 1회 요청당 최대 API 호출 수를 10건으로 제한.
- 호출 우선순위: 직선거리가 가장 가까운 후보군부터 순차적으로 호출.

### 3.2 무료 티어 활용
- 네이버 맵 API의 무료 쿼터(월 10만건 등) 내에서 운영되도록 캐시 히트율(Cache Hit Rate) 목표를 90% 이상으로 설정.

## 4. 구현 단계 (Implementation)
1.  **Phase 1:** 백엔드 `.env` 연동 및 `commute_cache` 테이블 생성.
2.  **Phase 2:** 네이버 REST API 통신 모듈 개발.
3.  **Phase 3:** 캐시 우선 로직이 포함된 `get_precise_commute` 함수 구현.
4.  **Phase 4:** 프론트엔드 결과 화면에 '실제 소요시간' 태그 추가.
