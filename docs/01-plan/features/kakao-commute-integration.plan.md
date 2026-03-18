# [Plan] 카카오 모빌리티 연동 및 출퇴근 시간 정밀화

## Executive Summary

| 항목 | 내용 |
| ---- | ---- |
| Feature | kakao-commute-integration |
| 시작일 | 2026-03-16 |
| 목표 | 카카오 모빌리티 API를 활용하여 실제 출퇴근 시간대(08:00, 18:30)의 정밀 이동 시간을 산출하고 UI에 시각화 |

### Value Delivered

| 관점 | 내용 |
| ---- | ---- |
| **Problem** | 단순 거리 기반 또는 실시간 교통량 미반영 데이터는 실제 출퇴근 체감 시간과 괴리가 큼 |
| **Solution** | 카카오 모빌리티 미래 이동 시간 API를 연동하여 출근(아파트->직장)과 퇴근(직장->아파트) 시간을 개별 산출 및 합산 |
| **Function UX Effect** | 출근/퇴근 각각의 소요 시간 확인 및 시간대별 부하(트래픽) 시각화 (Green/Yellow/Red) |
| **Core Value** | '인생 시급' 계산의 핵심 데이터인 '시간'의 정확도를 극대화하여 서비스 신뢰도 확보 |

## 1. 현황 분석 및 설계

### 1.1 이동 구간 정의
- **출근 (Morning):** 아파트(단지/동) → 직장(사용자 지정 역/위치) (목표: 08:00 도착 또는 출발)
- **퇴근 (Evening):** 직장 → 아파트 (목표: 18:30 출발)

### 1.2 카카오 모빌리티 API 활용
- **Endpoint:** `https://apis-navi.kakaomobility.com/v1/future/directions` (미래 경로 탐색)
- **Parameters:**
    - `origin`: 출발지 좌표
    - `destination`: 목적지 좌표
    - `departure_time`: `YYYYMMDDHHMM` (예: 차주 월요일 08:00)
- **인증:** `Authorization: KakaoAK {REST_API_KEY}`

### 1.3 UI 시각화 가이드
- **30분 미만:** 초록색 (쾌적)
- **60분 미만:** 노란색 (보통)
- **90분 미만:** 주황색 (지침)
- **90분 이상:** 빨간색 (위험)

## 2. 구현 계획

### Phase 1: 백엔드 API 연동 (`server/lib/kakao_api.py`)
- `get_kakao_commute(origin, destination, departure_time)` 함수 구현
- 카카오 API 응답 데이터 파싱 (duration, distance)
- 캐싱 로직 적용 (동일 경로/시간대 호출 최소화)

### Phase 2: 백엔드 로직 수정 (`server/main.py`)
- `optimize_location` 엔드포인트 수정
- 사용자별 출근/퇴근 시간 각각 호출
- 결과 데이터 구조 확장: `commute_morning`, `commute_evening` 필드 추가

### Phase 3: 프론트엔드 UI 개선 (`client/src/App.jsx`)
- 결과 리스트 아이템에 출근/퇴근 시간 상세 표시
- 시간대별 색상 코드 적용 (Lucide-react 아이콘 활용)
- 카카오맵 폴리라인 및 오버레이에 상세 시간 표시

## 3. 검증 방법
- 특정 지역(예: 김포 -> 강남)의 월요일 08:00 기준 시간과 현재 시간 비교 테스트
- 프론트엔드 리스트에서 출/퇴근 합산 및 개별 시간 정상 노출 확인
- 맵 상의 경로 표시 및 툴팁 가독성 확인

## 4. 필요한 리소스
- 카카오 개발자 센터 -> 내 애플리케이션 -> **REST API 키** (server/.env 등록 필요)
