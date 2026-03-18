# [Plan] Naver Maps API 인증 실패 해결 (Auth Error 200)

## Executive Summary

| 항목 | 내용 |
| ---- | ---- |
| Feature | fix-naver-map-auth |
| 시작일 | 2026-03-16 |
| 목표 | 네이버 지도 API 인증 실패(Error 200)를 해결하고 지도가 정상적으로 렌더링되도록 함 |

### Value Delivered

| 관점 | 내용 |
| ---- | ---- |
| **Problem** | `Vite`의 `base: '/search-house/'` 설정으로 인해 로컬 개발 서버 주소가 `http://localhost:5173/search-house/`가 되나, 네이버 콘솔에 등록된 URI와 불일치하여 인증 실패 발생 |
| **Solution** | 네이버 클라우드 플랫폼 콘솔 설정 가이드 제공 및 관련 주석/가이드 문서 업데이트 |
| **Function UX Effect** | 지도가 정상적으로 표시되어 서비스의 핵심 기능을 사용할 수 있게 됨 |
| **Core Value** | 사용자에게 중단 없는 지도 기반 탐색 경험 제공 |

## 1. 현황 분석 및 원인 파악

### 1.1 에러 메시지 분석
- **Error Code:** 200 (Authentication Failed)
- **Reported URI:** `http://localhost:5173/search-house/`
- **원인:** 네이버 클라우드 플랫폼(NCP) 콘솔의 'Web 서비스 URL' 설정에 현재 접속 중인 URI가 등록되지 않았거나, 서비스 선택에서 'Web Dynamic Map'이 누락됨.

### 1.2 설정 파일 분석
- `client/.env`: `VITE_NAVER_MAP_CLIENT_ID=fdzttm4ug2` (확인됨)
- `client/vite.config.js`: `base: '/search-house/'` 설정으로 인해 모든 리소스가 해당 경로 하위에 위치함.

## 2. 해결 방안 (Strategy)

### 2.1 NCP 콘솔 설정 변경 (사용자 조치 사항)
1.  [네이버 클라우드 플랫폼 콘솔](https://console.ncloud.com/naver-service/application) 접속.
2.  사용 중인 Application (`fdzttm4ug2` 관련) 선택 후 '변경' 클릭.
3.  **서비스 선택:** `Maps` 카테고리에서 `Web Dynamic Map`이 체크되어 있는지 확인 (Mobile Dynamic Map이 아님).
4.  **Web 서비스 URL:** 아래 주소들을 모두 추가:
    - `http://localhost:5173`
    - `http://localhost:5173/search-house/`
    - `https://hee882.github.io` (배포 환경 대비)

### 2.2 코드 및 문서 개선
- `.env.example` 및 `.env` 파일의 가이드 주석에서 'Mobile Dynamic Map'을 'Web Dynamic Map'으로 정정하고, 상세 URL 등록 예시를 보강함.

## 3. 구현 계획

| 단계 | 작업 내용 | 비고 |
| ---- | ---- | ---- |
| Step 1 | `client/.env.example` 주석 업데이트 (Web Dynamic Map 명시 및 URL 예시 추가) | |
| Step 2 | `client/.env` (사용자 로컬 파일) 주석 업데이트 | |
| Step 3 | 사용자에게 NCP 콘솔 설정 변경 방법 안내 | |

## 4. 검증 방법
- NCP 콘솔 설정 변경 후 브라우저 새로고침 시 네이버 지도가 정상적으로 로드되는지 확인.
- 브라우저 콘솔에서 `Authentication Failed` 에러가 사라졌는지 확인.
