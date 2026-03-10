// Kakao Maps Provider
// SDK: https://dapi.kakao.com/v2/maps/sdk.js

const KAKAO_KEY = import.meta.env.VITE_KAKAO_MAP_KEY;

// 표준 줌(1-20, 높을수록 가까움) ↔ 카카오 레벨(1-14, 높을수록 멀어짐) 변환
function toKakaoLevel(zoom) {
  return Math.max(1, Math.min(14, 20 - zoom));
}

function fromKakaoLevel(level) {
  return 20 - level;
}

function loadScript() {
  return new Promise((resolve, reject) => {
    if (window.kakao?.maps?.Map) {
      resolve();
      return;
    }

    if (window.kakao?.maps?.load) {
      window.kakao.maps.load(() => resolve());
      return;
    }

    // 동적 스크립트 로드
    const script = document.createElement('script');
    script.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${KAKAO_KEY}&autoload=false&libraries=services`;
    script.onload = () => {
      if (window.kakao?.maps?.load) {
        window.kakao.maps.load(() => resolve());
      } else {
        reject(new Error('Kakao Maps SDK 로드 실패'));
      }
    };
    script.onerror = () => reject(new Error('Kakao Maps SDK 스크립트 로드 실패. 카카오 개발자 콘솔 설정을 확인하세요.'));
    document.head.appendChild(script);
  });
}

export async function loadSDK() {
  if (!KAKAO_KEY) {
    throw new Error('VITE_KAKAO_MAP_KEY가 설정되지 않았습니다. client/.env를 확인하세요.');
  }
  await loadScript();
}

export function createMap(container, { lat, lng }, zoom) {
  const kakaoMaps = window.kakao.maps;
  return new kakaoMaps.Map(container, {
    center: new kakaoMaps.LatLng(lat, lng),
    level: toKakaoLevel(zoom),
  });
}

export function setCenter(map, { lat, lng }) {
  if (!map || !window.kakao?.maps) return;
  map.setCenter(new window.kakao.maps.LatLng(lat, lng));
}

export function setZoom(map, zoom) {
  if (!map || !window.kakao?.maps) return;
  map.setLevel(toKakaoLevel(zoom));
}

export function setBounds(map, points) {
  if (!map || !window.kakao?.maps || !points.length) return;
  const kakaoMaps = window.kakao.maps;
  const bounds = new kakaoMaps.LatLngBounds();
  points.forEach(p => bounds.extend(new kakaoMaps.LatLng(p.lat, p.lng)));
  map.setBounds(bounds);
}

export function getZoom(map) {
  if (!map || !window.kakao?.maps) return 15;
  return fromKakaoLevel(map.getLevel());
}

export function addMarker(map, { lat, lng, title, icon, onClick }) {
  if (!map || !window.kakao?.maps) return null;
  const kakaoMaps = window.kakao.maps;

  const opts = {
    position: new kakaoMaps.LatLng(lat, lng),
    map,
    title,
  };

  if (icon) {
    opts.image = new kakaoMaps.MarkerImage(
      icon.url,
      new kakaoMaps.Size(icon.width || 36, icon.height || 36),
    );
  }

  const marker = new kakaoMaps.Marker(opts);

  if (onClick) {
    kakaoMaps.event.addListener(marker, 'click', onClick);
  }

  return marker;
}

export function addOverlay(map, { lat, lng, content }) {
  if (!map || !window.kakao?.maps) return null;
  const kakaoMaps = window.kakao.maps;

  return new kakaoMaps.CustomOverlay({
    position: new kakaoMaps.LatLng(lat, lng),
    content,
    yAnchor: 1.2,
    map,
  });
}

export function clearMarkers(list) {
  if (!list) return;
  list.forEach((m) => {
    if (m) {
      if (typeof m.setMap === 'function') m.setMap(null);
    }
  });
}

export function drawPolyline(map, path, options = {}) {
  if (!map || !window.kakao?.maps) return null;
  const kakaoMaps = window.kakao.maps;

  const linePath = path.map(p => new kakaoMaps.LatLng(p.lat, p.lng));

  const polyline = new kakaoMaps.Polyline({
    path: linePath,
    strokeWeight: options.weight || 4,
    strokeColor: options.color || '#3B82F6',
    strokeOpacity: 0.8,
    strokeStyle: options.style || 'solid',
  });

  polyline.setMap(map);

  // 중앙에 라벨(시간 등) 표시
  let overlay = null;
  if (options.label && path.length >= 2) {
    const midLat = (path[0].lat + path[1].lat) / 2;
    const midLng = (path[0].lng + path[1].lng) / 2;
    
    overlay = new kakaoMaps.CustomOverlay({
      position: new kakaoMaps.LatLng(midLat, midLng),
      content: `<div style="background:${options.color}; color:white; padding:4px 8px; border-radius:12px; font-size:11px; font-weight:900; box-shadow:0 2px 6px rgba(0,0,0,0.2); white-space:nowrap; border:1.5px solid white;">${options.label}</div>`,
      map
    });
  }

  return { polyline, overlay, setMap: (m) => { polyline.setMap(m); if(overlay) overlay.setMap(m); } };
}

export async function geocodeAddress(query) {
  if (!query || !window.kakao?.maps?.services) return null;

  return new Promise((resolve) => {
    const geocoder = new window.kakao.maps.services.Geocoder();

    geocoder.addressSearch(query, (result, status) => {
      if (status === window.kakao.maps.services.Status.OK && result.length > 0) {
        resolve({
          lat: parseFloat(result[0].y),
          lng: parseFloat(result[0].x),
          name: result[0].address_name,
        });
      } else {
        // 주소 실패 → 키워드 검색 폴백
        const places = new window.kakao.maps.services.Places();
        places.keywordSearch(query, (placeResult, placeStatus) => {
          if (placeStatus === window.kakao.maps.services.Status.OK && placeResult.length > 0) {
            resolve({
              lat: parseFloat(placeResult[0].y),
              lng: parseFloat(placeResult[0].x),
              name: placeResult[0].place_name,
            });
          } else {
            resolve(null);
          }
        });
      }
    });
  });
}
