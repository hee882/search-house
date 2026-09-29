import { useSyncExternalStore } from 'react';

// Tailwind 의 md: 분기점(768px)과 정확히 맞물리도록 같은 조건을 쓰고 결과를 뒤집는다.
const DESKTOP_QUERY = '(min-width: 768px)';

const subscribe = (onChange) => {
  const mediaQuery = window.matchMedia(DESKTOP_QUERY);
  mediaQuery.addEventListener('change', onChange);
  return () => mediaQuery.removeEventListener('change', onChange);
};

const getSnapshot = () => !window.matchMedia(DESKTOP_QUERY).matches;

// 렌더 중에 window.innerWidth 를 읽으면 창 크기나 화면 방향이 바뀌어도 다시 그려지지 않는다.
export function useIsMobile() {
  return useSyncExternalStore(subscribe, getSnapshot);
}
