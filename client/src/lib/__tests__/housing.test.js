import test from 'node:test';
import assert from 'node:assert/strict';
import { getIncomeRatio, getBudgetStatus, getTimeStatus, getResidentTypeLabel, getNaverLandUrl } from '../housing.js';

test('소득 대비 비율을 계산한다', () => {
  assert.equal(getIncomeRatio(100, 400), 0.25);
});

test('소득이 0 이하이면 비율을 계산하지 않는다', () => {
  assert.equal(getIncomeRatio(100, 0), null);
  assert.equal(getIncomeRatio(0, 0), null);
  assert.equal(getIncomeRatio(100, -10), null);
});

test('지출이나 소득 값이 없으면 비율을 계산하지 않는다', () => {
  assert.equal(getIncomeRatio(undefined, 400), null);
  assert.equal(getIncomeRatio(100, undefined), null);
  assert.equal(getIncomeRatio(100, NaN), null);
});

test('주거비 비율 구간의 경계값은 낮은 단계에 속한다', () => {
  assert.equal(getBudgetStatus(0.2).label, '양호');
  assert.equal(getBudgetStatus(0.21).label, '주의');
  assert.equal(getBudgetStatus(0.3).label, '주의');
  assert.equal(getBudgetStatus(0.31).label, '위험');
});

test('통근 시간 구간의 경계값은 낮은 단계에 속한다', () => {
  assert.equal(getTimeStatus(30).color, 'text-green-600');
  assert.equal(getTimeStatus(31).color, 'text-yellow-600');
  assert.equal(getTimeStatus(60).color, 'text-yellow-600');
  assert.equal(getTimeStatus(90).color, 'text-orange-600');
  assert.equal(getTimeStatus(91).color, 'text-red-600');
});

test('주거 형태 이름을 찾고 모르는 값은 전월세로 표시한다', () => {
  assert.equal(getResidentTypeLabel('jeonse'), '전세');
  assert.equal(getResidentTypeLabel('buy'), '매매');
  assert.equal(getResidentTypeLabel('unknown'), '전월세');
});

test('네이버 부동산 주소는 동 이름을 앞에 붙이고 인코딩한다', () => {
  assert.equal(
    getNaverLandUrl('래미안 & 자이', '반포동'),
    `https://fin.land.naver.com/search?query=${encodeURIComponent('반포동 래미안 & 자이')}`,
  );
});

test('동 이름이나 단지명이 없어도 주소를 만든다', () => {
  assert.equal(getNaverLandUrl('래미안', ''), `https://fin.land.naver.com/search?query=${encodeURIComponent('래미안')}`);
  assert.equal(getNaverLandUrl(undefined, undefined), 'https://fin.land.naver.com/search?query=');
});
