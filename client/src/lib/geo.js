export const getDistanceKm = (lat1, lng1, lat2, lng2) => {
  const toRad = (deg) => (deg * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
};

// 서버는 법정동 좌표로 최근접역을 계산하므로, 클라이언트에서 단지 좌표를 보정한 뒤에는
// 보정된 좌표 기준으로 다시 계산해야 표시되는 역이 실제 위치와 어긋나지 않는다.
export const findNearestStations = (lat, lng, stations, count = 3, maxDistanceKm = 2) =>
  stations
    .map((station) => ({ name: station.name, distance: getDistanceKm(lat, lng, station.lat, station.lng) }))
    .filter((item) => Number.isFinite(item.distance) && item.distance <= maxDistanceKm)
    .sort((a, b) => a.distance - b.distance)
    .slice(0, count)
    .map((item) => item.name);

export const MAX_COORD_CORRECTION_KM = 1.5;

// 키워드 검색 첫 결과가 이름만 같은 다른 장소일 수 있다. 서버 좌표에서 크게 벗어난 보정값을 받아들이면
// 마커와 최근접역이 서버가 계산한 통근 시간과 어긋나므로, 허용 거리 안의 보정만 인정한다.
export const isWithinCorrectionRange = (serverCoords, correctedCoords, maxDistanceKm = MAX_COORD_CORRECTION_KM) => {
  if (!serverCoords || !correctedCoords) return false;
  const distance = getDistanceKm(
    Number(serverCoords.lat), Number(serverCoords.lng),
    Number(correctedCoords.lat), Number(correctedCoords.lng),
  );
  return Number.isFinite(distance) && distance <= maxDistanceKm;
};
