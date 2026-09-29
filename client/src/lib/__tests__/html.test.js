import test from 'node:test';
import assert from 'node:assert/strict';
import { escapeHtml } from '../html.js';

test('HTML 특수문자 다섯 가지를 모두 바꾼다', () => {
  assert.equal(escapeHtml(`&<>"'`), '&amp;&lt;&gt;&quot;&#39;');
});

test('태그가 들어간 단지명은 태그로 해석되지 않는 문자열이 된다', () => {
  assert.equal(
    escapeHtml('<img src=x onerror="alert(1)">'),
    '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;',
  );
});

test('속성 값을 끊고 나가는 따옴표를 막는다', () => {
  const escaped = escapeHtml(`" onclick='alert(1)'`);
  assert.ok(!escaped.includes('"'));
  assert.ok(!escaped.includes("'"));
});

test('일반 단지명은 그대로 둔다', () => {
  assert.equal(escapeHtml('래미안 퍼스티지 1단지'), '래미안 퍼스티지 1단지');
});

test('이미 이스케이프된 문자열도 한 번 더 바꾼다', () => {
  assert.equal(escapeHtml('&amp;'), '&amp;amp;');
});

test('문자열이 아닌 값은 문자열로 바꾸고 없는 값은 빈 문자열로 만든다', () => {
  assert.equal(escapeHtml(42), '42');
  assert.equal(escapeHtml(null), '');
  assert.equal(escapeHtml(undefined), '');
});
