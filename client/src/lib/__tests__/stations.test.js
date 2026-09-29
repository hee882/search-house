import test from 'node:test';
import assert from 'node:assert/strict';
import { searchStations, getLineColor, LINE_COLORS } from '../stations.js';

const STATIONS = [
  { name: '강남구청역', line: '7호선,수인분당선' },
  { name: '신강남역', line: '1호선,2호선,3호선' },
  { name: '강남역', line: '2호선' },
  { name: '총신대입구역', line: '4호선,7호선' },
  { name: '사당역', line: '2호선,4호선' },
  { name: '서울역', line: '1호선,4호선,경의중앙선,공항철도' },
  { name: '건대입구역', line: '2호선,7호선' },
];

const names = (list) => list.map((station) => station.name);

test('정확히 일치하는 역이 환승 노선이 더 많은 역보다 위에 온다', () => {
  assert.equal(searchStations(STATIONS, '강남역', null)[0].name, '강남역');
});

test("'역'을 빼고 검색해도 정확 일치로 본다", () => {
  const result = names(searchStations(STATIONS, '강남', null));
  assert.equal(result[0], '강남역');
  assert.deepEqual([...result].sort(), ['강남구청역', '강남역', '신강남역'].sort());
});

test('이름이 검색어로 시작하는 역이 중간에 포함한 역보다 위에 온다', () => {
  const result = names(searchStations(STATIONS, '강남', null));
  assert.ok(result.indexOf('강남구청역') < result.indexOf('신강남역'));
});

test('별칭으로 검색하면 실제 역 이름을 찾는다', () => {
  assert.deepEqual(names(searchStations(STATIONS, '이수', null)), ['총신대입구역']);
  assert.deepEqual(names(searchStations(STATIONS, '이수역', null)), ['총신대입구역']);
});

test('초성만으로 검색할 수 있다', () => {
  const result = names(searchStations(STATIONS, 'ㄱㄴ', null));
  assert.ok(result.includes('강남역'));
  assert.ok(result.includes('강남구청역'));
  assert.ok(!result.includes('사당역'));
});

test('검색어 앞뒤 공백은 무시한다', () => {
  assert.equal(searchStations(STATIONS, ' 사당 ', null)[0].name, '사당역');
});

test('검색어가 없거나 이미 선택한 역 이름이면 앞의 5개를 추천으로 돌려준다', () => {
  assert.deepEqual(searchStations(STATIONS, '', null), STATIONS.slice(0, 5));
  assert.deepEqual(searchStations(STATIONS, '강남역', '강남역'), STATIONS.slice(0, 5));
});

test('일치하는 역이 없으면 빈 배열을 돌려준다', () => {
  assert.deepEqual(searchStations(STATIONS, '부산', null), []);
});

test('결과는 15개를 넘지 않는다', () => {
  const many = Array.from({ length: 30 }, (_, i) => ({ name: `테스트${i}역`, line: '1호선' }));
  assert.equal(searchStations(many, '테스트', null).length, 15);
});

test('원본 역 목록을 바꾸지 않는다', () => {
  const before = names(STATIONS);
  searchStations(STATIONS, '강남', null);
  assert.deepEqual(names(STATIONS), before);
});

test('호선 색상은 공백을 무시하고 찾으며 모르는 호선은 기본색을 쓴다', () => {
  assert.equal(getLineColor(' 2호선 '), LINE_COLORS['2호선']);
  assert.equal(getLineColor('없는노선'), '#A0AEC0');
});
