# [Plan] 통근 시간 정확도 개선 — 역-단지 거리 반영

## Executive Summary

| 항목 | 내용 |
| ---- | ---- |
| Feature | commute-accuracy |
| 시작일 | 2026-03-11 |
| 목표 | 역과 실제 단지 사이의 거리를 반영하여 추천 정확도를 획기적으로 개선 |

### Value Delivered

| 관점 | 내용 |
| ---- | ---- |
| **Problem** | city_code(구 단위) 기반 매칭으로 역에서 2~5km 떨어진 단지도 포함됨. 통근 12분이라고 표시하지만 실제 단지까지 추가 이동시간이 누락 |
| **Solution** | 동(dong) 단위 대표 좌표 매핑 → 역-동 거리 기반 통근시간 보정. 향후 외부 길찾기 API 연동 가능 |
| **Function UX Effect** | "국회의사당역 → 여의도동 단지"처럼 실제 역 인근 단지만 추천, 통근시간에 역-단지 도보시간 포함 |
| **Core Value** | 추천 결과 신뢰도 대폭 향상 → 사용자 체감 정확도 개선 |

## 1. 현황 분석

### 1.1 현재 문제

```
현재 매칭 흐름:
  1. 역 선택 (예: 국회의사당역, city_code=11560)
  2. 통근시간 = 역 ↔ 직장역 직선거리 기반 (12분)
  3. DB 조회: WHERE city_code = '11560' (영등포구 전체)
  4. 결과: 문래동, 당산동, 대림동 등 영등포구 전체 단지 포함
```

**핵심 갭**:
- **구(區) 단위 매칭**: 영등포구 면적 약 24km². 국회의사당역(여의도)에서 당산동까지 직선 2.5km
- **역-단지 거리 무시**: 통근시간에 "역에서 단지까지 도보/이동 시간"이 빠져 있음
- **결과 왜곡**: 역과 거리가 먼 대단지가 거래 건수(cnt)가 높아서 상위 노출

### 1.2 구체적 예시

| 역 | city_code | 1위 단지 | 역-단지 직선거리 | 문제 |
|---|---|---|---|---|
| 국회의사당역 | 11560(영등포구) | 당산래미안4차 | ~2.5km | 역 인근이 아님 |
| 국회의사당역 | 11560 | 문래롯데캐슬 | ~3.2km | 문래동은 더 먼 곳 |

### 1.3 현재 통근시간 계산

```python
# main.py
def estimate_commute_time(distance_km, transport_mode):
    speed = 30 if transport_mode == 'car' else 20
    return int((distance_km / speed) * 60) + (5 if transport_mode == 'car' else 10)

# 문제: 이 distance_km은 역↔직장역 거리이며, 역↔단지 거리는 미포함
```

## 2. 해결 방안

### Phase 1 (P0): 동 단위 좌표 매핑 + 역-동 거리 필터 (즉시 가능)

**핵심**: 각 dong_name에 대표 위경도를 매핑하여, 역에서 반경 2km 이내 동의 단지만 포함

**구현**:
1. `server/data/dong_coordinates.json` 생성: 66개 시군구의 주요 동별 대표 좌표
2. DB 조회 후 Python에서 역-동 거리 필터링
3. 통근시간에 역-동 도보시간(약 5분/km) 추가 반영

```python
# 예시
def get_complexes_with_costs(city_code, station_lat, station_lng, ...):
    # 1. DB에서 city_code 기준 후보 조회 (기존과 동일)
    # 2. 각 dong_name의 대표 좌표와 역 좌표 간 거리 계산
    # 3. 역에서 2km 이내 동의 단지만 필터
    # 4. 통근시간에 역-동 도보시간 추가
    for row in rows:
        dong_coord = DONG_COORDS.get(f"{city_code}_{dong_name}")
        if dong_coord:
            dist_to_dong = calculate_distance(station_lat, station_lng, dong_coord['lat'], dong_coord['lng'])
            if dist_to_dong > 2.0:  # 2km 초과 시 제외
                continue
            walk_minutes = int(dist_to_dong / 0.08)  # 약 80m/분 = 4.8km/h 보행속도
```

**동 좌표 데이터 수집**:
- 방법 1: Kakao Local API (`/v2/local/search/address`) — 동 검색으로 좌표 획득
- 방법 2: 공공 데이터 "행정동 경계" GeoJSON에서 centroid 추출
- 방법 3: 수동 구성 (주요 동 100~200개만)

### Phase 2 (P1): 외부 길찾기 API 연동 (향후)

**카카오 모빌리티 API** 또는 **네이버 지도 길찾기 API**로 실제 대중교통 통근시간 계산.

| API | 장점 | 단점 |
|---|---|---|
| 카카오 모빌리티 | 무료 1만건/일, 대중교통 길찾기 지원 | API 키 필요, 할당량 제한 |
| 네이버 Direction API | 정확한 대중교통/자차 | 유료(1000건/일 무료) |
| TMAP API | 대중교통 길찾기 정확 | API 키, 할당량 |

**이번 범위**: Phase 1만 구현 (동 좌표 매핑), Phase 2는 후속 과제

## 3. 구현 계획

| 파일 | 변경 | 내용 |
| ---- | ---- | ---- |
| `server/build_dong_coords.py` | **신규** | 동 좌표 수집 스크립트 |
| `server/data/dong_coordinates.json` | **신규** | 동별 대표 좌표 데이터 |
| `server/main.py` | **수정** | get_complexes_with_costs에 역-동 거리 필터 + 도보시간 추가 |

### 3.1 동 좌표 데이터 구조

```json
{
  "11560_여의도동": { "lat": 37.5219, "lng": 126.9245 },
  "11560_당산동5가": { "lat": 37.5339, "lng": 126.9028 },
  "11560_문래동6가": { "lat": 37.5183, "lng": 126.8945 }
}
```

### 3.2 서버 로직 변경

1. `get_complexes_with_costs()`에 `station_lat`, `station_lng` 파라미터 추가
2. DB 조회 결과에서 dong_name 기반으로 좌표 조회
3. 역-동 직선거리 > 2km인 단지 제외
4. 통근시간 = 기존 역↔직장역 시간 + 역→단지 도보시간
5. `optimize_location()`에서 station 좌표를 함수에 전달

## 4. 검증 방법

1. 국회의사당역 검색 → 여의도동 단지만 나오고, 당산/문래 단지 미포함 확인
2. 강남역 검색 → 역삼동/논현동 단지 중심, 수서/세곡 제외 확인
3. 통근시간에 역-단지 도보시간이 추가 반영되는지 확인
4. 역세권 반경 2km 내 단지가 없는 경우 → 해당 역 결과 미표시 확인
