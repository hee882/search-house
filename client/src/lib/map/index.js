import * as kakao from './providers/kakao';
import * as naver from './providers/naver';

const MAP_PROVIDER = import.meta.env.VITE_MAP_PROVIDER || 'kakao';

export function getProvider() {
  return MAP_PROVIDER === 'naver' ? naver : kakao;
}

export function getProviderName() {
  return MAP_PROVIDER;
}

// 통합 훅
export { useMap } from './useMap';

// 프로바이더 위임 함수들
const p = getProvider();
export const addMarker = (...args) => p.addMarker(...args);
export const addOverlay = (...args) => p.addOverlay(...args);
export const clearMarkers = (...args) => p.clearMarkers(...args);
export const geocodeAddress = (...args) => p.geocodeAddress(...args);
export const drawPolyline = (...args) => p.drawPolyline(...args);
export const setBounds = (...args) => p.setBounds(...args);
export const getZoom = (...args) => p.getZoom(...args);
export const setZoom = (...args) => p.setZoom(...args);
