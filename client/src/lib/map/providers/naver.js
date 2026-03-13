// Naver Maps Provider
// SDK: https://oapi.map.naver.com/openapi/v3/maps.js

const NAVER_CLIENT_ID = import.meta.env.VITE_NAVER_MAP_CLIENT_ID;

function loadScript() {
  return new Promise((resolve, reject) => {
    if (window.naver?.maps?.Map) {
      resolve();
      return;
    }

    const script = document.createElement('script');
    script.src = `https://oapi.map.naver.com/openapi/v3/maps.js?ncpClientId=${NAVER_CLIENT_ID}&submodules=geocoder`;
    script.onload = () => {
      if (window.naver?.maps) {
        resolve();
      } else {
        reject(new Error('Naver Maps SDK 로드 실패'));
      }
    };
    script.onerror = () => reject(new Error('Naver Maps SDK 스크립트 로드 실패. NCP 콘솔 설정을 확인하세요.'));
    document.head.appendChild(script);
  });
}

export async function loadSDK() {
  if (!NAVER_CLIENT_ID) {
    throw new Error('VITE_NAVER_MAP_CLIENT_ID가 설정되지 않았습니다. client/.env를 확인하세요.');
  }
  await loadScript();
}

export function createMap(container, { lat, lng }, zoom) {
  const naverMaps = window.naver.maps;
  return new naverMaps.Map(container, {
    center: new naverMaps.LatLng(lat, lng),
    zoom,
  });
}

export function setCenter(map, { lat, lng }) {
  if (!map || !window.naver?.maps) return;
  map.setCenter(new window.naver.maps.LatLng(lat, lng));
}

export function setZoom(map, zoom) {
  if (!map || !window.naver?.maps) return;
  map.setZoom(zoom);
}

export function getZoom(map) {
  if (!map || !window.naver?.maps) return 15;
  return map.getZoom();
}

export function addMarker(map, { lat, lng, title, icon, onClick }) {
  if (!map || !window.naver?.maps) return null;
  const naverMaps = window.naver.maps;

  const opts = {
    position: new naverMaps.LatLng(lat, lng),
    map,
    title,
  };

  if (icon) {
    opts.icon = {
      url: icon.url,
      size: new naverMaps.Size(icon.width || 36, icon.height || 36),
    };
  }

  const marker = new naverMaps.Marker(opts);

  if (onClick) {
    naverMaps.Event.addListener(marker, 'click', onClick);
  }

  return marker;
}

export function addOverlay(map, { lat, lng, content }) {
  if (!map || !window.naver?.maps) return null;
  const naverMaps = window.naver.maps;

  // Naver: Marker의 icon.content로 HTML 오버레이 구현
  return new naverMaps.Marker({
    position: new naverMaps.LatLng(lat, lng),
    map,
    icon: {
      content,
      anchor: new naverMaps.Point(60, 60),
    },
  });
}

export function clearMarkers(list) {
  if (!list) return;
  list.forEach((m) => {
    if (m) m.setMap(null);
  });
}

export async function geocodeAddress(query) {
  if (!query || !window.naver?.maps?.Service) return null;

  return new Promise((resolve) => {
    window.naver.maps.Service.geocode({ query }, (status, response) => {
      if (status === window.naver.maps.Service.Status.OK) {
        const addrs = response.v2.addresses;
        if (addrs.length > 0) {
          resolve({
            lat: parseFloat(addrs[0].y),
            lng: parseFloat(addrs[0].x),
            name: addrs[0].roadAddress || addrs[0].jibunAddress,
          });
          return;
        }
      }
      resolve(null);
    });
  });
}

export function drawPolyline(map, path, { color, style, weight }) {
  if (!map || !window.naver?.maps) return null;
  const naverMaps = window.naver.maps;
  const polyline = new naverMaps.Polyline({
    map,
    path: path.map(p => new naverMaps.LatLng(p.lat, p.lng)),
    strokeColor: color || '#3B82F6',
    strokeWeight: weight || 5,
    strokeOpacity: 0.8,
    strokeStyle: style === 'dashed' ? 'dash' : 'solid',
  });
  return polyline;
}

export function setBounds(map, points, padding = {}) {
  if (!map || !window.naver?.maps || !points || points.length === 0) return;
  const naverMaps = window.naver.maps;
  const bounds = new naverMaps.LatLngBounds();
  points.forEach(p => bounds.extend(new naverMaps.LatLng(p.lat, p.lng)));
  
  // padding: { top, right, bottom, left }
  map.fitBounds(bounds, {
    top: padding.top || 100,
    right: padding.right || 100,
    bottom: padding.bottom || 100,
    left: padding.left || 100
  });
}
