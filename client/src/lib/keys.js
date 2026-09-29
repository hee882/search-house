// 이름과 동이 같은 단지가 다른 구에 있을 수 있다. key 가 겹치면 React 가 항목을 잘못 재사용하므로
// 겹칠 때만 등장 순서를 덧붙여 구분한다.
export const buildUniqueKeys = (items, getBaseKey) => {
  const seen = new Map();
  return items.map((item) => {
    const base = String(getBaseKey(item));
    const count = seen.get(base) || 0;
    seen.set(base, count + 1);
    return count === 0 ? base : `${base}#${count}`;
  });
};
