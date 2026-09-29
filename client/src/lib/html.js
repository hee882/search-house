const HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

// 지도 오버레이는 문자열 HTML 로 만들어지므로, 단지명 같은 외부 데이터는 넣기 전에 반드시 이스케이프한다.
export const escapeHtml = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (char) => HTML_ESCAPES[char]);
