# Search House (써치하우스) 🏠

맞벌이 부부 및 1인 가구를 위한 **출퇴근 시간 가치 기반 최적 주거지 추천 서비스**입니다. 단순히 거리를 재는 것이 아니라, 사용자의 연봉을 시급으로 환산하여 출퇴근에 소모되는 '기회비용'과 '주거비'를 합산한 경제적 최적지를 제안합니다.

## ✨ 주요 기능
- **경제적 입지 분석:** (연봉 기반 시간 가치 × 출퇴근 시간) + 교통비 + 주거비를 합산 분석
- **맞벌이 모드:** 두 사람의 직장 위치와 각각의 연봉 가중치를 고려한 중간 지점 추천
- **네이버 지도 연동:** 고해상도 한국 지도 및 실시간 매물 서비스(아웃링크) 연결
- **매물 매칭:** 추천 지역의 실제 네이버 부동산 매물 페이지로 즉시 연결

## 🛠 기술 스택
- **Frontend:** React 19, Vite, Tailwind CSS v4, Lucide Icons, React-Naver-Maps
- **Backend:** Python 3.12, FastAPI, Uvicorn, Pydantic
- **Data:** Open Data API (국토교통부 실거래가), Naver Maps API

## 🚀 시작하기

### Frontend
```bash
cd client
npm install
npm run dev
```
*`.env` 파일에 `VITE_NAVER_MAP_CLIENT_ID` 설정 필요*

### Backend
```bash
cd server
pip install -r requirements.txt
python main.py
```
*`.env` 파일에 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` 설정 필요*

## 📝 커밋 규격
[Conventional Commits](https://www.conventionalcommits.org/) 규격을 따릅니다.
- `feat:`, `fix:`, `docs:`, `style:`, `refactor:`, `test:`, `chore:`
