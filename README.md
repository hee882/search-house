# Search House (써치하우스)

맞벌이 부부 및 1인 가구를 위한 **출퇴근 기회비용 기반 최적 주거지 추천 서비스**. 연봉을 시급으로 환산하여 출퇴근에 소모되는 '기회비용'과 '주거비'를 합산, 경제적 최적지를 지도 위에 제안합니다.

## 주요 기능

- **경제적 입지 분석** — (시간 가치 x 출퇴근 시간) + 교통비 + 주거비 합산 랭킹
- **맞벌이 모드** — 두 직장 위치 + 각각의 연봉 가중치를 고려한 중간 지점 추천
- **실거래가 연동** — 국토교통부 공공데이터 API 기반 아파트 실거래가 DB 자동 수집
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

**데이터 흐름:** 클라이언트 주소 지오코딩 → `POST /api/optimize` → 서버가 역별 거리·통근시간 계산 + DB 실거래가 조회 → Top 5 추천 결과 반환 → 지도에 마커/오버레이 렌더링

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
```

### 데이터 수집
```bash
python server/collector.py                  # 현재월 수집
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
