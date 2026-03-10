# [Design] 백엔드 전월세 실거래가 연동 및 전월세 분리 최적화

## 1. 아키텍처 및 폴더 구조 (변경 대상)

```text
server/
├── data/
│   └── search_house.db       // rent_transactions 테이블 추가
├── collector_rent.py         // [신규 파일] 전월세 실거래가 전용 수집기
├── db_init.py                // 테이블 생성 스키마 수정
└── main.py                   // /api/optimize 계산 로직 수정 (보증금+월세 기반)

client/
└── src/
    └── App.jsx               // 전월세 분리 UI 렌더링 및 매매 버튼 숨김
```

## 2. 데이터베이스 스키마 설계 (`db_init.py`)

기존 `transactions` 테이블과 별도로, API 응답에 맞춰 `rent_transactions` 테이블을 생성합니다.

```sql
CREATE TABLE IF NOT EXISTS rent_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_code TEXT,
    apt_name TEXT,
    dong_name TEXT,
    exclusive_area REAL,
    deal_year INTEGER,
    deal_month INTEGER,
    deal_day INTEGER,
    deposit INTEGER,           -- 보증금액 (문자열 내 콤마 제거 후 정수 변환) 단위: 만원
    monthly_rent INTEGER,      -- 월차임 (문자열 내 콤마 제거 후 정수 변환) 단위: 만원
    floor INTEGER,
    build_year INTEGER,
    UNIQUE(city_code, apt_name, dong_name, deal_year, deal_month, deal_day, deposit, monthly_rent)
);
```

## 3. 데이터 수집기 설계 (`collector_rent.py`)

*   **API URL**: `http://apis.data.go.kr/1613000/RTMSDataSvcAptRent`
*   **API Key**: `7c7b7f2b751248958a8bf6bba48481d621f202f946cf8028056a89b3c9feb532`
*   **파싱 로직**: XML 파싱 시 `<보증금액>`과 `<월세금액>` 노드를 찾아 공백 및 콤마(`,`)를 제거한 뒤 `int()`로 캐스팅하여 DB에 삽입. 
*   **로깅**: 실행 시 기존 `collector.py`와 충돌하지 않도록 별도의 로깅 혹은 파일명 구분 철저.

## 4. 분석 모델 로직 설계 (`main.py`)

`get_complexes_with_costs` 함수를 재설계합니다.

**[전세/월세/반전세 랭킹 산출 쿼리]**
1. `rent_transactions` 테이블에서 최근 거래(예: 2024년 이후)를 가져옵니다.
2. 그룹핑(`apt_name`, `dong_name`) 시 가장 빈번하게 거래된 조건을 가져오기 위해 전세(월세=0)와 월세(월세>0)를 분리하여 대표값을 추출하거나, 단지별로 가장 최근/평균 보증금 및 월세를 구합니다.
3. **월 주거비용 환산 (fixed_monthly_exp)**:
   - `월 거주비 = (deposit * 0.04) / 12 + monthly_rent + 기본관리비(예: 10만원)`
   - 전세: `(deposit * 0.04) / 12 + 10`
   - 반/월세: `(deposit * 0.04) / 12 + monthly_rent + 10`
4. 프론트엔드 응답(JSON) 페이로드에 다음 필드 추가:
   - `rent_type`: `"전세"` 또는 `"월세"` (반전세 포함)
   - `deposit`: 보증금 (만원)
   - `monthly_rent`: 월세 (만원)
   - `display_price_label`: "전세" 또는 "월세"
   - `display_price_value`: 프론트에서 포맷팅하기 쉽도록 가공된 문자열 (예: "전세 2억 5천", "월세 5000 / 60")

## 5. 프론트엔드 반영 계획 (`App.jsx`)

1. **매매/임대 토글 강제 비활성화**: 
   - UI에서 `매매`, `임대` 버튼이 있는 `div` 영역을 `hidden` 처리하거나 삭제. 
   - `residentType` state의 기본값을 `'rent'`로 고정.
2. **결과 카드 금액 표기 변경**:
   - 기존 `apt.display_price_value` (숫자) 기반 렌더링에서 벗어나, 백엔드에서 전달받은 `rent_type`, `deposit`, `monthly_rent`를 조합하여 렌더링.
   - 예: `apt.rent_type === '전세' ? \`전세 ${apt.deposit}만\` : \`월세 ${apt.deposit}/${apt.monthly_rent}\`` (실제로는 '억' 단위 환산 로직 적용)
   - "추정 전세가", "평균 매매가" 등의 라벨을 `apt.display_price_label`에 맞게 동적으로 렌더링.

## 6. 작업 순서 (Do Phase)
1. `server/db_init.py` 에 `rent_transactions` 테이블 생성 로직 추가 후 스크립트 실행.
2. `server/collector_rent.py` 작성 및 과거 1~2달치 데이터 테스트 수집.
3. `server/main.py` 의 API 로직 및 계산 알고리즘 수정 (반전세 비용 통합 랭킹).
4. `client/src/App.jsx` UI 수정 (매매 숨김, 전월세 전용 렌더링).
5. 통합 테스트 (Lighthouse 또는 프론트엔드 직접 구동).