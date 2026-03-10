# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Search House (써치하우스) — a commute-time opportunity-cost-based optimal housing location recommender for Korea. Users input workplace location(s) and salary; the system calculates (hourly wage x commute time) + housing cost to recommend the most economical residential areas, displayed on a map (Kakao/Naver switchable) with links to Naver Real Estate listings.

## Development Commands

### Frontend (client/)
```bash
cd client
npm install
npm run dev        # Vite dev server on http://localhost:5173
npm run build      # Production build
npm run lint       # ESLint
```

### Backend (server/)
```bash
cd server
pip install -r requirements.txt
python main.py     # FastAPI on http://localhost:8000 with auto-reload
```

### Data Collection
```bash
python server/collector.py                  # Collect current month
python server/collector.py --month 202404   # Collect specific month
```

## Architecture

**Monorepo with two independent apps:**

- `client/` — React 19 + Vite 7 SPA. Single-page app in `App.jsx` with a map-centric UI (left sidebar + full-screen map). Map provider abstraction layer (`src/lib/map/`) supports Kakao Maps and Naver Maps — switchable via `VITE_MAP_PROVIDER` env var. Each provider handles SDK loading, markers, overlays, and geocoding. Styled with Tailwind CSS v4 (Vite plugin, not PostCSS). Font: Pretendard via CDN.
- `server/` — FastAPI backend. `main.py` exposes `POST /api/optimize` which loads station candidates from `data/stations.json`, calculates distances (Haversine), estimates commute times, queries real estate prices from SQLite, and returns top 5 ranked locations. `collector.py` fetches apartment transaction data from the MOLIT public API (XML→dict) and stores it in `data/search_house.db` with UPSERT logic.

**Data flow:** Client geocodes address → POST to `/api/optimize` → Server scores stations by (commute opportunity cost + housing interest cost) → Client renders markers + ranked results.

**Data files (server/data/):**
- `stations.json` — candidate residential locations (lat/lng/name/city_code/rent_level)
- `region_codes.json` — region code mappings for MOLIT API
- `search_house.db` — SQLite DB with `transactions` table (apartment deals)

**GitHub Actions:** `data_update.yml` runs `collector.py` daily (UTC 19:00 / KST 04:00), commits DB changes automatically.

## Environment Variables

- `client/.env`: `VITE_MAP_PROVIDER` (`kakao` or `naver`), `VITE_KAKAO_MAP_KEY`, `VITE_NAVER_MAP_CLIENT_ID`
- `server/.env`: `DATA_API_KEY` (공공데이터포털 API key)
- See `client/.env.example` for reference

## Conventions

- 한국어로 소통한다
- ESLint rule: unused vars are errors except those matching `^[A-Z_]`
- CORS is configured for `localhost:5173` only
- Currency unit throughout the codebase is 만원 (10,000 KRW)

## Commit Convention

[Conventional Commits](https://www.conventionalcommits.org/) 형식을 따르며, 아래 포맷을 일관되게 사용한다. Co-Authored-By 푸터는 넣지 않는다.

```text
<type>(<scope>): <subject>

<body>
```

- **type**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`
- **scope**: 변경 범위 (예: `client`, `server`, `data`, `ci`)
- **subject**: 한글로 간결하게 작성
- **body**: 필요시 상세 설명 (선택)
