import test from 'node:test';
import assert from 'node:assert/strict';
import { getRequestErrorMessage, getSearchErrorMessage } from '../errors.js';

const httpError = (status) => Object.assign(new Error(`분석 요청 실패 (HTTP ${status})`), { status });
const DEFAULT_MESSAGE = '분석 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.';

test('429 는 잠시 후 다시 시도하라고 안내한다', () => {
  assert.equal(getSearchErrorMessage(httpError(429)), '요청이 많습니다. 잠시 후 다시 시도해 주세요.');
});

test('422 는 입력값을 확인하라고 안내한다', () => {
  assert.equal(getSearchErrorMessage(httpError(422)), '입력값을 확인한 뒤 다시 시도해 주세요.');
});

test('그 밖의 상태 코드와 일반 오류는 기존 문구를 쓴다', () => {
  assert.equal(getSearchErrorMessage(httpError(500)), DEFAULT_MESSAGE);
  assert.equal(getSearchErrorMessage(new Error('네트워크 오류')), DEFAULT_MESSAGE);
  assert.equal(getSearchErrorMessage(undefined), DEFAULT_MESSAGE);
});

test('응답 형식 오류와 시간 초과는 각자의 문구를 쓴다', () => {
  assert.equal(
    getSearchErrorMessage(new Error('INVALID_RESPONSE')),
    '서버에서 올바르지 않은 응답을 받았습니다. 잠시 후 다시 시도해 주세요.',
  );
  const abortError = Object.assign(new Error('aborted'), { name: 'AbortError' });
  assert.equal(getSearchErrorMessage(abortError), '요청 시간이 초과되었습니다. 네트워크를 확인한 뒤 다시 시도해 주세요.');
});

test('시간 초과가 아니면 넘겨받은 기본 문구를 돌려준다', () => {
  assert.equal(getRequestErrorMessage(new Error('실패'), '기본 문구'), '기본 문구');
});
