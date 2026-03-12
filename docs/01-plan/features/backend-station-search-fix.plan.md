# [Plan] 백엔드 역 검색 간헐적 오류 해결

## Executive Summary

| 항목 | 내용 |
| ---- | ---- |
| Feature | backend-station-search-fix |
| 시작일 | 2026-03-12 |
| 목표 | 역 검색 API 응답 안정성 100% 달성 |

### Value Delivered

| 관점 | 내용 |
| ---- | ---- |
| **Problem** | `/api/stations` 호출 시 Render cold start(15분 비활성 후 슬립) + 재시도 없는 fetch로 인해 빈 결과가 간헐적으로 반환됨 |
| **Solution** | 백엔드: startup 이벤트로 데이터 보장 + 헬스체크. 프론트: 재시도 로직 + 로딩/에러 UI |
| **Function UX Effect** | 역 검색 드롭다운이 항상 620개역을 정상 표시하고, 로딩/에러 상태를 명확히 안내 |
| **Core Value** | 서비스 첫인상 개선 + 사용자 이탈 방지 |

## 1. 현황 분석

### 1.1 문제 재현 시나리오

1. Render 무료 티어에서 15분 비활성 → 서버 슬립
2. 사용자 접속 → 프론트 `fetch(/api/stations)` 호출
3. Render cold start (5~30초 소요) → 요청 타임아웃 또는 지연
4. `catch(console.error)` — 실패 시 `stationList = []` 유지
5. 역 검색 드롭다운에 아무것도 표시되지 않음

### 1.2 코드 분석

**백엔드 (`server/main.py`)**:
- `load_stations()`가 모듈 레벨에서 동기 호출 (line 84) — 이것은 정상
- `/api/stations` 엔드포인트에서 empty일 경우 1회 retry (line 286) — 부분적 방어
- 문제: startup 이벤트 미사용, 헬스체크 없음

**프론트엔드 (`client/src/App.jsx:170`)**:
```javascript
fetch(`${API_BASE_URL}/api/stations`).then(res => res.json()).then(setStationList).catch(console.error);
```
- 재시도 로직 없음
- HTTP 에러 상태 체크 없음 (`res.ok` 미확인)
- 로딩/에러 UI 없음

## 2. 해결 방안

### P0: 프론트엔드 재시도 로직 (핵심)

```javascript
// 지수 백오프 재시도 (최대 3회)
const fetchWithRetry = async (url, retries = 3) => {
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      if (i === retries - 1) throw e;
      await new Promise(r => setTimeout(r, 1000 * (i + 1)));
    }
  }
};
```

### P1: 백엔드 startup 이벤트 + 헬스체크

```python
@app.on_event("startup")
async def startup_event():
    load_stations()
    logger.info(f"Server ready: {len(STATIONS_DATA)} stations loaded")

@app.get("/api/health")
async def health():
    return {"status": "ok", "stations": len(STATIONS_DATA)}
```

### P2: 프론트엔드 로딩/에러 상태 표시

- 역 로딩 중: 스피너 또는 "역 데이터 로딩 중..." 텍스트
- 역 로딩 실패: "역 데이터를 불러올 수 없습니다. 재시도" 버튼

## 3. 구현 계획

| 파일 | 변경 | 비고 |
| ---- | ---- | ---- |
| `server/main.py` | **수정** | startup 이벤트, 헬스체크 엔드포인트 |
| `client/src/App.jsx` | **수정** | fetchWithRetry, 로딩/에러 상태 |

## 4. 검증 방법

1. `curl /api/health` → `{"status": "ok", "stations": 620}` 확인
2. `curl /api/stations` → 620개역 정상 반환 확인
3. 프론트: 네트워크 탭에서 fetch 실패 시 재시도 동작 확인
4. 프론트: API_BASE_URL을 잘못된 URL로 변경 후 에러 UI 표시 확인
