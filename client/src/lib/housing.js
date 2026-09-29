export const RESIDENT_TYPES = [
  { id: 'jeonse', label: '전세' },
  { id: 'wolse', label: '월세' },
  { id: 'buy', label: '매매' },
];

export const getResidentTypeLabel = (id) => RESIDENT_TYPES.find((type) => type.id === id)?.label || '전월세';

export const getTimeStatus = (minutes) => {
  if (minutes <= 30) return { color: 'text-green-600', bg: 'bg-green-50', border: 'border-green-100', dot: 'bg-green-500' };
  if (minutes <= 60) return { color: 'text-yellow-600', bg: 'bg-yellow-50', border: 'border-yellow-100', dot: 'bg-yellow-500' };
  if (minutes <= 90) return { color: 'text-orange-600', bg: 'bg-orange-50', border: 'border-orange-100', dot: 'bg-orange-500' };
  return { color: 'text-red-600', bg: 'bg-red-50', border: 'border-red-100', dot: 'bg-red-500' };
};

export const getBudgetStatus = (ratio) => {
  if (ratio <= 0.2) return { label: '양호', color: 'text-green-600', bg: 'bg-green-50', border: 'border-green-100', icon: '✅' };
  if (ratio <= 0.3) return { label: '주의', color: 'text-orange-600', bg: 'bg-orange-50', border: 'border-orange-100', icon: '⚠️' };
  return { label: '위험', color: 'text-red-600', bg: 'bg-red-50', border: 'border-red-100', icon: '🚨' };
};

// 소득이 0 이면 나눗셈 결과가 Infinity 나 NaN 이 되어 화면에 그대로 찍히므로, 계산할 수 없을 때는 null 로 알린다.
export const getIncomeRatio = (monthlyExpense, monthlyIncome) => {
  if (!(monthlyIncome > 0)) return null;
  const ratio = monthlyExpense / monthlyIncome;
  return Number.isFinite(ratio) ? ratio : null;
};

export const getNaverLandUrl = (name, dong) => {
  // 동이름 포함 시 검색 정확도 향상 (MOLIT 단지명과 네이버 명칭 차이 보완)
  const query = dong ? `${dong} ${name}` : name;
  const q = encodeURIComponent((query || '').trim());
  return `https://fin.land.naver.com/search?query=${q}`;
};
