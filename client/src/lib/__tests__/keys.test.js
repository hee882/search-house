import test from 'node:test';
import assert from 'node:assert/strict';
import { buildUniqueKeys } from '../keys.js';

const spotKey = (spot) => `${spot.name}|${spot.dong}`;

test('겹치지 않는 항목은 기본 key 를 그대로 쓴다', () => {
  const spots = [{ name: '래미안', dong: '반포동' }, { name: '자이', dong: '반포동' }];
  assert.deepEqual(buildUniqueKeys(spots, spotKey), ['래미안|반포동', '자이|반포동']);
});

test('기본 key 가 겹치면 뒤에 오는 항목에 순번을 붙여 구분한다', () => {
  const spots = [{ name: '현대', dong: '중앙동' }, { name: '현대', dong: '중앙동' }, { name: '현대', dong: '중앙동' }];
  const keys = buildUniqueKeys(spots, spotKey);
  assert.equal(new Set(keys).size, 3);
  assert.equal(keys[0], '현대|중앙동');
});

test('순서가 바뀌어도 겹치지 않는 항목의 key 는 변하지 않는다', () => {
  const a = { name: '래미안', dong: '반포동' };
  const b = { name: '자이', dong: '잠원동' };
  assert.deepEqual(buildUniqueKeys([b, a], spotKey), buildUniqueKeys([a, b], spotKey).reverse());
});

test('빈 목록은 빈 배열을 돌려준다', () => {
  assert.deepEqual(buildUniqueKeys([], spotKey), []);
});
