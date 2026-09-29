export const getRequestErrorMessage = (error, fallback) =>
  error?.name === 'AbortError' ? '요청 시간이 초과되었습니다. 네트워크를 확인한 뒤 다시 시도해 주세요.' : fallback;

// 사용자가 스스로 해결할 수 있는 상태 코드만 따로 안내한다. 나머지는 원인을 알려 줘도 할 수 있는 일이 없다.
const HTTP_STATUS_MESSAGES = {
  429: '요청이 많습니다. 잠시 후 다시 시도해 주세요.',
  422: '입력값을 확인한 뒤 다시 시도해 주세요.',
};

export const getSearchErrorMessage = (error) => {
  if (error?.message === 'INVALID_RESPONSE') return '서버에서 올바르지 않은 응답을 받았습니다. 잠시 후 다시 시도해 주세요.';
  return HTTP_STATUS_MESSAGES[error?.status]
    || getRequestErrorMessage(error, '분석 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.');
};
