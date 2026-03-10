# [Design] 백엔드 데이터 파이프라인 확장: 전월세 실거래가 연동

## 1. 아키텍처 및 폴더 구조 (변경 대상)

```text
server/
├── data/
│   └── search_house.db       // rent_transactions 테이블 추가
├── collector_rent.py         // [신규 파일] 전월세 실거래가 전용 수집기
├── db_init.py                // 테이블 생성 스키마 수정
└── main.py                   // /api/optimize 계산 로직 수정 (전월세 기반)

client/
└── src/
    └── App.jsx               // 전월세 UI/UX 반영 및 매매 탭 임시 숨김
```

## 2. 데이터베이스 스키마 설계 (`db_init.py`)

기존 `transactions` 테이블과 유사한 `rent_transactions` 테이블을 생성합니다.

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
    deposit INTEGER,           -- 보증금액 (전세는 보증금 전체, 월세는 보증금) 단위: 만원
    monthly_rent INTEGER,      -- 월차임 (전세는 0, 월세는 해당 금액) 단위: 만원
    floor INTEGER,
    build_year INTEGER,
    UNIQUE(city_code, apt_name, dong_name, deal_year, deal_month, deal_day, deposit, monthly_rent)
);
```

## 3. 데이터 수집기 설계 (`collector_rent.py`)

*   **API URL**: `http://apis.data.go.kr/1613000/RTMSDataSvcAptRent`
*   **API Key**: (제공된 새로운 키 사용)
*   **파싱 로직**: XML 응답에서 `보증금액`과 `월세금액`을 파싱. (공공데이터는 보통 보증금액 10,000 과 같이 콤마가 포함된 문자열이므로 integer로 캐스팅 필요)
*   GitHub Actions에서 매월 실행되도록 `data_update.yml`에 스크립트 실행 추가.

## 4. 분석 모델 로직 설계 (`main.py`)

`get_complexes_with_costs` 함수를 재설계합니다.
현재는 `transactions` (매매) 테이블을 보지만, 파라미터에 따라 `rent_transactions` 테이블을 보도록 쿼리를 수정합니다.

**[전월세 거주비 계산 알고리즘]**
*   **보증금 기회비용**: `(deposit * 0.04) / 12` (전세 자금 대출 이자 혹은 기회비용을 연 4%로 가정)
*   **월세**: `monthly_rent`
*   **월 거주비 (fixed_monthly_exp)** = 보증금 기회비용 + 월세 + (기본 관리비/교통비 고정값)

## 5. 프론트엔드 반영 계획 (`App.jsx`)

1.  **매매 버튼 숨김 처리**: `<button onClick={() => setResidentType('buy')}>매매</button>` 등의 옵션을 삭제하거나 `hidden` 클래스를 주어 강제로 **전월세 전용 모드**로 작동하게 합니다. (백엔드 기본값도 'rent'로 고정)
2.  **출력 텍스트 수정**: "추정 전세가"를 **"월 거주비 (보증금+월세 환산)"** 등의 더 명확한 문구로 통일합니다.

## 6. 작업 순서 (Do Phase)
1. `server/db_init.py` 에 `rent_transactions` 테이블 추가.
2. `server/collector_rent.py` 생성 및 전월세 수집 로직 구현, 테스트 실행하여 로컬 DB에 데이터 적재.
3. `server/main.py` 의 `get_complexes_with_costs` 쿼리 및 계산식 전월세 기준으로 수정.
4. `client/src/App.jsx` UI 수정 (매매 숨김, 텍스트 변경).