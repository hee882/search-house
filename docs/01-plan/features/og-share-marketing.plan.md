# [Plan] OG(Open Graph) 이미지 + 카카오 공유 마케팅

## Executive Summary

| 항목 | 내용 |
| ---- | ---- |
| Feature | og-share-marketing |
| 시작일 | 2026-03-11 |
| 목표 | 카카오톡/SNS 공유 시 매력적인 OG 이미지와 마케팅 문구로 클릭 유도 |

### Value Delivered

| 관점 | 내용 |
| ---- | ---- |
| **Problem** | 카카오톡으로 URL 공유 시 기본 제목만 표시되어 클릭 유도력 없음 |
| **Solution** | 모던한 OG 이미지 + 마케팅 문구 + 메타태그 최적화로 공유 시 시각적 임팩트 |
| **Function UX Effect** | 카카오톡에 링크 붙여넣기 → 모던 카드(이미지+제목+설명)로 표시 → 클릭율 증대 |
| **Core Value** | 바이럴 공유 통한 자연 유입 증대 + 서비스 브랜딩 강화 |

## 1. 현황 분석

### 1.1 현재 문제

- `index.html`에 OG 메타태그 미설정 (또는 기본값)
- 카카오톡 공유 시 제목/설명/이미지 없이 URL만 표시
- SNS(트위터, 페이스북 등) 공유 시에도 동일 문제

### 1.2 OG 메타태그 요구사항

```html
<!-- 필수 OG 태그 -->
<meta property="og:title" content="Search House — 당신의 시간은 얼마인가요?" />
<meta property="og:description" content="통근 기회비용까지 포함한 진짜 주거 비용으로 최적 입지를 찾아보세요. 매일 왕복 2시간 = 연 20일, 그 시간의 가치는?" />
<meta property="og:image" content="https://hee882.github.io/search-house/og-image.png" />
<meta property="og:url" content="https://hee882.github.io/search-house/" />
<meta property="og:type" content="website" />
<meta property="og:site_name" content="Search House" />

<!-- 카카오톡 전용 -->
<meta property="og:image:width" content="1200" />
<meta property="og:image:height" content="630" />

<!-- 트위터 카드 -->
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="Search House — 당신의 시간은 얼마인가요?" />
<meta name="twitter:description" content="통근 기회비용까지 포함한 진짜 주거 비용 계산기" />
<meta name="twitter:image" content="https://hee882.github.io/search-house/og-image.png" />
```

## 2. 해결 방안

### P0: OG 이미지 디자인 및 생성

**사이즈**: 1200×630px (카카오톡/페이스북 최적)

**디자인 컨셉**: 모던 다크 그라디언트 + 통계 강조

```
┌─────────────────────────────────────────────┐
│  ╔═══════════════════════════════════════╗   │
│  ║  [로고]  Search House                ║   │
│  ║                                       ║   │
│  ║  매일 왕복 2시간 통근 =               ║   │
│  ║  연간 480시간 = 20일                  ║   │
│  ║  🔥 당신의 시간은 얼마인가요?          ║   │
│  ║                                       ║   │
│  ║  ▸ 인생 시급 기반 최적 주거지 추천     ║   │
│  ║  ▸ 수도권 620+ 역세권 실시간 분석      ║   │
│  ╚═══════════════════════════════════════╝   │
└─────────────────────────────────────────────┘
```

**구현 방식**:
- HTML/CSS로 OG 이미지 레이아웃 작성
- Playwright/Puppeteer로 스크린샷 → PNG 저장
- 또는 SVG → PNG 변환

### P1: 메타태그 추가

`client/index.html`에 OG/Twitter 메타태그 추가.

### P2: 카카오톡 공유 버튼 (선택)

결과 화면에 "카카오톡으로 공유" 버튼 추가.
Kakao JavaScript SDK의 `Kakao.Share.sendDefault()` 사용.

## 3. 구현 계획

| 파일 | 변경 | 내용 |
| ---- | ---- | ---- |
| `client/public/og-image.png` | **신규** | 1200×630 OG 이미지 |
| `client/index.html` | **수정** | OG/Twitter 메타태그 추가 |
| `scripts/generate-og-image.html` | **신규** (선택) | OG 이미지 생성용 HTML |

### 3.1 OG 이미지 생성

**방법 A**: SVG 기반 (의존성 없음)
```bash
# SVG → PNG 변환 (brew install librsvg)
rsvg-convert -w 1200 -h 630 og-template.svg -o og-image.png
```

**방법 B**: HTML/CSS 기반 (Puppeteer)
```bash
node scripts/generate-og-image.js
```

### 3.2 마케팅 문구 옵션

| 버전 | 제목 | 설명 |
|---|---|---|
| A | "당신의 시간은 얼마인가요?" | 통근 기회비용까지 포함한 진짜 주거 비용 계산기 |
| B | "보이지 않는 비용이 진짜 비용입니다" | 매일 왕복 2시간 = 연 20일, 당신의 시급으로 환산하면? |
| C | "집값만 비교하면 잃는 것들" | 인생 시급 × 통근시간 = 숨은 기회비용. 지금 확인하세요. |

## 4. 검증 방법

1. `https://developers.kakao.com/tool/debugger` 에서 OG 태그 파싱 확인
2. 카카오톡 채팅에 URL 공유 → 이미지+제목+설명 카드 표시 확인
3. Facebook Debugger (`https://developers.facebook.com/tools/debug/`) 확인
4. 트위터 카드 validator로 확인
5. OG 이미지가 1200×630px, 5MB 미만인지 확인
