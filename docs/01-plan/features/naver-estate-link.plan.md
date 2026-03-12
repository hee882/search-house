# [Plan] 네이버 부동산 단지 링크 정확도 개선

## Executive Summary

| 항목 | 내용 |
|------|------|
| Feature | naver-estate-link |
| 시작일 | 2026-03-12 |
| 목표 | 추천 단지 클릭 시 네이버 부동산에서 해당 단지를 정확히 찾을 수 있도록 개선 |

### Value Delivered

| 관점 | 내용 |
|------|------|
| **Problem** | "동명 + 아파트명" 검색 쿼리가 네이버 부동산에서 부정확한 결과를 반환하여 사용자가 재검색해야 함 |
| **Solution** | 검색 URL 최적화 + 단지 카드에서 직접 이동 UX 추가 (비공식 API 스크래핑 없이 안전하게) |
| **Function UX Effect** | 단지 카드 클릭 또는 버튼 클릭 → 네이버 부동산 검색에서 해당 단지가 최상위에 표시 |
| **Core Value** | 매물 탐색 여정 단축 + 법적/기술적 안정성 확보 |

## 1. 현황 분석

### 1.1 현재 구현

```javascript
// App.jsx:412
window.open(`https://m.land.naver.com/search/result?query=${complex.dong} ${complex.name}`, '_blank');
```

- `complex.dong` = DB의 `dong_name` (예: "명륜3가", "평창동")
- `complex.name` = DB의 `apt_name` (예: "경희궁롯데캐슬")

### 1.2 문제점

1. **동명이 검색을 방해**: "명륜3가 경희궁롯데캐슬" 같은 쿼리에서 동명이 노이즈로 작용
2. **동명 불일치**: MOLIT API의 `dong_name`과 네이버 부동산의 지역명이 다를 수 있음
3. **URL 인코딩 누락**: 공백/특수문자가 인코딩되지 않아 일부 아파트명에서 오작동
4. **단지 카드에서 바로 이동 불가**: 하단 버튼에서만 네이버 링크 접근 가능

### 1.3 법적 고려사항

| 방식 | 법적 안전성 | 비고 |
|------|------------|------|
| 네이버 부동산 검색 URL로 연결 (외부 링크) | **안전** | 일반 하이퍼링크, 이용약관 위반 없음 |
| 네이버 내부 API 직접 호출 (스크래핑) | **위험** | 이용약관 위반, 429 차단, 부정경쟁방지법 적용 가능 |
| 네이버 공식 검색 API (Naver Developers) | **안전** | 공식 API지만 부동산 전용 아님 |

**결론**: 검색 URL 링크 방식이 법적으로 안전하고 유지보수 부담 없음. API 스크래핑 하지 않음.

## 2. 해결 방안

### P0: 검색 쿼리 최적화 (프론트엔드만)

**현재**: `query=${dong} ${name}` → 동명이 노이즈로 작용
**개선**: `query=${name}` → 아파트명만 사용 (네이버 부동산에서 아파트명으로 정확히 검색됨)

```javascript
// Before
window.open(`https://m.land.naver.com/search/result?query=${complex.dong} ${complex.name}`, '_blank');

// After
const query = encodeURIComponent(complex.name);
window.open(`https://m.land.naver.com/search/result?query=${query}`, '_blank');
```

추가 개선:
- `encodeURIComponent()` 적용으로 특수문자 안전 처리
- 아파트명 앞뒤 공백 제거 (`trim()`)

### P1: 단지 카드 클릭 시 네이버 부동산 이동

현재는 하단 버튼("네이버 부동산 매물 보기")에서만 접근 가능.
개선: 단지 카드(아파트명 + ExternalLink 아이콘) 클릭 시에도 네이버 부동산으로 이동.

### P2: PC/모바일 URL 분기 (선택)

- 모바일: `https://m.land.naver.com/search/result?query=...`
- PC: `https://new.land.naver.com/complexes?query=...`
- `window.innerWidth` 기반 분기 또는 `navigator.userAgent` 체크

## 3. 구현 계획

### 3.1 파일 변경 범위

| 파일 | 변경 | 비고 |
|------|------|------|
| `client/src/App.jsx` | **수정** | 검색 URL 최적화 + 단지 카드 클릭 이동 |

**백엔드 변경 없음** — 프론트엔드만 수정하는 안전한 변경.

### 3.2 변경 상세

#### App.jsx 변경 1: 하단 버튼 URL 개선

```javascript
// line 412 변경
const query = encodeURIComponent((complex.name || '').trim());
window.open(`https://m.land.naver.com/search/result?query=${query}`, '_blank');
```

#### App.jsx 변경 2: 단지 카드 클릭 시 이동

```javascript
// 단지 카드(line 388)에 네이버 링크 onClick 추가
onClick={() => {
  setExpandedComplexIdx(idx);
  // ExternalLink 아이콘 클릭 감지 시 네이버로 이동
}}
```

ExternalLink 아이콘에 별도 onClick 핸들러:
```javascript
<ExternalLink
  size={12}
  className="text-gray-300 shrink-0 cursor-pointer hover:text-blue-500"
  onClick={(e) => {
    e.stopPropagation();
    const q = encodeURIComponent(apt.name.trim());
    window.open(`https://m.land.naver.com/search/result?query=${q}`, '_blank');
  }}
/>
```

## 4. 검증 방법

1. "경희궁롯데캐슬" → 네이버 부동산에서 해당 단지 검색 결과 최상위 표시 확인
2. "(1-102)" 같은 특수문자 포함 아파트명도 정상 인코딩 확인
3. ExternalLink 아이콘 클릭 → 네이버 이동 + 단지 카드 확장은 유지 확인
4. 하단 버튼 클릭 → 네이버 이동 정상 확인

## 5. 우선순위 요약

| 단계 | 내용 | 난이도 | 법적 안전성 |
|------|------|--------|------------|
| **P0** | 검색 쿼리 최적화 (dong 제거 + encodeURI) | 하 | 안전 |
| **P1** | 단지 카드 ExternalLink 클릭 시 이동 | 하 | 안전 |
| **P2** | PC/모바일 URL 분기 (선택) | 하 | 안전 |
