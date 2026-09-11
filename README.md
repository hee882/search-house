# Search House (써치하우스)

맞벌이 부부 및 1인 가구를 위한 **출퇴근 기회비용 기반 최적 주거지 추천 서비스**. 연봉을 시급으로 환산하여 출퇴근에 소모되는 '기회비용'과 '주거비'를 합산, 경제적 최적지를 지도 위에 제안합니다.

## 주요 기능

- **경제적 입지 분석** — (시간 가치 x 출퇴근 시간) + 교통비 + 주거비 합산 랭킹
- **전세·월세·매매 선택** — 주거 형태별로 실거래가를 따로 집계해 비교 가능한 결과 제공
- **맞벌이 모드** — 두 직장 각각까지의 거리·연봉을 반영해 양쪽 모두 감당 가능한 위치 추천
- **실거래가 연동** — 국토교통부 공공데이터 API 기반 아파트 실거래가 DB 자동 수집
  (신고 지연을 감안해 최근 3개월 재수집, 갱신계약은 시세 집계에서 제외)
- **추천 단지 표시** — 지역별 실거래 기반 Top 단지 + 기회비용 계산 결과 지도 위 표시
- **지도 프로바이더 전환** — 카카오맵 / 네이버맵 Strategy 패턴 추상화 (`VITE_MAP_PROVIDER` 전환)

## 기술 스택

| 영역 | 기술 |
|------|------|
| **Frontend** | React 19, Vite 7, Tailwind CSS v4 (Vite plugin), Pretendard 폰트 |
| **Backend** | Python 3.12, FastAPI, Uvicorn, SQLite |
| **Data** | 국토교통부 실거래가 API (MOLIT), 카카오맵/네이버맵 SDK |
| **Deploy** | GitHub Pages (프론트), Render (백엔드) |
| **CI/CD** | GitHub Actions (프론트 자동 배포 + 실거래가 일일 수집) |

## 아키텍처

```
client/                     server/
├── src/                    ├── main.py          ← FastAPI 서버
│   ├── App.jsx             ├── collector.py     ← 실거래가 수집기
│   └── lib/map/            └── data/
│       ├── index.js             ├── stations.json     ← 후보 역 목록
│       ├── useMap.js            ├── region_codes.json  ← 지역코드
│       └── providers/           └── search_house.db    ← SQLite DB
│           ├── kakao.js
│           └── naver.js
```

**데이터 흐름:** 클라이언트 주소 지오코딩 → `POST /api/optimize` → 서버가 조건에 맞는 단지 시세를
면적대별로 집계 → 직장까지의 거리로 후보 50곳 선별 → 거리 기반 추정으로 상위 12곳만 정밀 분석
(좌표 보정 + 경로 API) → 동별 최대 2곳으로 추려 Top 5 반환 → 지도에 마커/오버레이 렌더링

**시세 집계 규칙:** 같은 단지라도 전용 10㎡ 단위로 묶어 거래가 가장 많은 면적대만 대표 시세로 쓰고,
IQR 상·하한으로 이상치를 제거한다. 전세와 월세는 절대 섞지 않으며, 갱신계약은 신규 대비
중앙값 -9.2% 수준이라 제외한다.

## 시작하기

### Frontend
```bash
cd client
npm install
npm run dev        # http://localhost:5173
```

`client/.env` 설정:
```
VITE_MAP_PROVIDER=kakao
VITE_KAKAO_MAP_KEY=<카카오 JavaScript 키>
VITE_API_URL=https://search-house.onrender.com
```

### Backend
```bash
cd server
pip install -r requirements.txt
python main.py     # http://localhost:8000
```

`server/.env` 설정:
```
DATA_API_KEY=<공공데이터포털 Decoding 키>
KAKAO_REST_API_KEY=<카카오 REST 키>
# 선택: 고비용 최적화 요청 보호 (기본 12회/60초/IP)
OPTIMIZE_RATE_MAX_REQUESTS=12
OPTIMIZE_RATE_WINDOW_SECONDS=60
# 선택: 통근 캐시 만료(초, 기본 900)
COMMUTE_CACHE_TTL_SECONDS=900
```

`/api/optimize`는 IP별 요청 제한을 적용하며 초과 시 `429`를 반환합니다. 대중교통 모드는 자동차 경로 API를 호출하지 않고 검증된 거리 기반 추정치를 사용합니다. 통근·단지 좌표 캐시는 만료 정책과 지역코드별 키를 사용합니다.

### 법정동 좌표 사전
```bash
python server/build_dong_coords.py            # 좌표가 없는 동만 보강
python server/build_dong_coords.py --force    # 기존 좌표까지 갱신
```
`server/data/dong_coordinates.json`은 후보 단지의 대략 위치를 잡는 데 쓰인다. 좌표가 없는 동은
구 중심 좌표로 대체되므로 통근 시간·최근접역 정확도가 떨어진다. `KAKAO_REST_API_KEY`를 설정한 뒤
위 스크립트를 실행하면 실거래 DB에 등장하는 동을 카카오 로컬 API로 채운다.

### 데이터 수집
실거래 신고 기한이 계약 후 30일이라 당월만 수집하면 그 달 후반 신고분이 영구 누락된다.
두 수집기 모두 기본으로 최근 3개월을 다시 훑어(UPSERT) 지연 신고와 정정 내역을 반영한다.

```bash
python server/collector.py                  # 최근 3개월 재수집
python server/collector.py --month 202403   # 특정월 수집
```

## 배포 구성

| 서비스 | 플랫폼 | 트리거 |
|--------|--------|--------|
| 프론트엔드 | GitHub Pages (`gh-pages` 브랜치) | `main` push 시 자동 빌드·배포 |
| 백엔드 API | Render (Web Service) | `main` push 시 자동 배포 |
| 실거래가 수집 | GitHub Actions (Cron) | 매일 KST 04:00 자동 실행 → DB 커밋·푸시 |

### GitHub Secrets 필요 목록

| Secret | 용도 |
|--------|------|
| `VITE_API_URL` | 프론트 빌드 시 백엔드 API 주소 |
| `VITE_KAKAO_MAP_KEY` | 프론트 빌드 시 카카오맵 JavaScript 키 |
| `DATA_API_KEY` | 실거래가 수집기 공공데이터 API 키 |

## 환경변수 참고

- `VITE_MAP_PROVIDER`: `kakao` 또는 `naver` (지도 프로바이더 전환)
- `VITE_NAVER_MAP_CLIENT_ID`: 네이버 클라우드 플랫폼 Client ID (네이버맵 사용 시)
- 프론트엔드 `VITE_*` 변수는 빌드 타임에 번들에 포함됨 (런타임 아님)

## 커밋 규격

[Conventional Commits](https://www.conventionalcommits.org/) — 한글 subject

```
<type>(<scope>): <subject>
```

type: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`
scope: `client`, `server`, `data`, `ci`
