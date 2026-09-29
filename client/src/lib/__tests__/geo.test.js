import test from 'node:test';
import assert from 'node:assert/strict';
import { getDistanceKm, findNearestStations, isWithinCorrectionRange, MAX_COORD_CORRECTION_KM } from '../geo.js';

const KM_PER_LAT_DEGREE = (6371 * Math.PI) / 180;
const ORIGIN = { lat: 37.5, lng: 127.0 };

// 같은 경도에서 위도만 옮기면 거리가 위도 차이에 비례하므로 원하는 거리의 점을 정확히 만들 수 있다.
const northOf = (origin, km) => ({ lat: origin.lat + km / KM_PER_LAT_DEGREE, lng: origin.lng });

test('같은 지점의 거리는 0 이다', () => {
  assert.equal(getDistanceKm(ORIGIN.lat, ORIGIN.lng, ORIGIN.lat, ORIGIN.lng), 0);
});

test('강남역과 서울역 사이 거리를 실제와 비슷하게 계산한다', () => {
  const distance = getDistanceKm(37.498085, 127.028, 37.554648, 126.972559);
  assert.ok(distance > 7.5 && distance < 8.5, `계산된 거리: ${distance}`);
});

test('최근접역은 가까운 순서로 정렬되고 최대 거리 밖의 역은 빠진다', () => {
  const stations = [
    { name: '먼역', ...northOf(ORIGIN, 1.8) },
    { name: '범위밖역', ...northOf(ORIGIN, 2.1) },
    { name: '가까운역', ...northOf(ORIGIN, 0.3) },
    { name: '중간역', ...northOf(ORIGIN, 1.0) },
  ];
  assert.deepEqual(findNearestStations(ORIGIN.lat, ORIGIN.lng, stations), ['가까운역', '중간역', '먼역']);
});

test('최근접역 개수와 최대 거리를 바꿀 수 있다', () => {
  const stations = [
    { name: 'A역', ...northOf(ORIGIN, 0.2) },
    { name: 'B역', ...northOf(ORIGIN, 0.6) },
    { name: 'C역', ...northOf(ORIGIN, 0.9) },
  ];
  assert.deepEqual(findNearestStations(ORIGIN.lat, ORIGIN.lng, stations, 1), ['A역']);
  assert.deepEqual(findNearestStations(ORIGIN.lat, ORIGIN.lng, stations, 3, 0.7), ['A역', 'B역']);
});

test('좌표가 없는 역은 최근접역 후보에서 빠진다', () => {
  const stations = [
    { name: '좌표없는역' },
    { name: '정상역', ...northOf(ORIGIN, 0.5) },
  ];
  assert.deepEqual(findNearestStations(ORIGIN.lat, ORIGIN.lng, stations), ['정상역']);
});

test('범위 안에 역이 없으면 빈 배열을 돌려준다', () => {
  assert.deepEqual(findNearestStations(ORIGIN.lat, ORIGIN.lng, [{ name: '먼역', ...northOf(ORIGIN, 5) }]), []);
  assert.deepEqual(findNearestStations(ORIGIN.lat, ORIGIN.lng, []), []);
});

test('좌표 보정 허용 거리는 1.5km 이다', () => {
  assert.equal(MAX_COORD_CORRECTION_KM, 1.5);
});

test('서버 좌표에서 1.5km 안쪽의 보정은 받아들인다', () => {
  assert.equal(isWithinCorrectionRange(ORIGIN, northOf(ORIGIN, 0.2)), true);
  assert.equal(isWithinCorrectionRange(ORIGIN, northOf(ORIGIN, 1.499)), true);
});

test('서버 좌표에서 1.5km 를 넘는 보정은 버린다', () => {
  assert.equal(isWithinCorrectionRange(ORIGIN, northOf(ORIGIN, 1.501)), false);
  assert.equal(isWithinCorrectionRange(ORIGIN, northOf(ORIGIN, 12)), false);
});

test('허용 거리와 정확히 같은 거리는 받아들인다', () => {
  const corrected = northOf(ORIGIN, 1.5);
  const distance = getDistanceKm(ORIGIN.lat, ORIGIN.lng, corrected.lat, corrected.lng);
  assert.equal(isWithinCorrectionRange(ORIGIN, corrected, distance), true);
  assert.equal(isWithinCorrectionRange(ORIGIN, corrected, distance - 1e-9), false);
});

test('같은 좌표로의 보정은 받아들인다', () => {
  assert.equal(isWithinCorrectionRange(ORIGIN, { ...ORIGIN }), true);
});

test('서버가 좌표를 문자열로 보내도 거리를 판정한다', () => {
  const corrected = northOf(ORIGIN, 1.0);
  assert.equal(isWithinCorrectionRange({ lat: String(ORIGIN.lat), lng: String(ORIGIN.lng) }, corrected), true);
});

test('좌표가 없거나 숫자가 아니면 보정을 버린다', () => {
  assert.equal(isWithinCorrectionRange(ORIGIN, null), false);
  assert.equal(isWithinCorrectionRange(null, ORIGIN), false);
  assert.equal(isWithinCorrectionRange(ORIGIN, { lat: NaN, lng: 127 }), false);
  assert.equal(isWithinCorrectionRange(ORIGIN, { lat: undefined, lng: undefined }), false);
});
