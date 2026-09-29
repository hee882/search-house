import test from 'node:test';
import assert from 'node:assert/strict';
import { getChosung } from '../hangul.js';

test('한글 음절을 초성으로 바꾼다', () => {
  assert.equal(getChosung('강남역'), 'ㄱㄴㅇ');
  assert.equal(getChosung('총신대입구역'), 'ㅊㅅㄷㅇㄱㅇ');
});

test('쌍자음 초성을 구분한다', () => {
  assert.equal(getChosung('까치산'), 'ㄲㅊㅅ');
  assert.equal(getChosung('쌍문'), 'ㅆㅁ');
});

test('한글 음절이 아닌 문자는 그대로 둔다', () => {
  assert.equal(getChosung('GTX-A 역'), 'GTX-A ㅇ');
  assert.equal(getChosung('ㄱㄴ'), 'ㄱㄴ');
  assert.equal(getChosung('인천1호선'), 'ㅇㅊ1ㅎㅅ');
});

test('빈 문자열은 빈 문자열을 돌려준다', () => {
  assert.equal(getChosung(''), '');
});
