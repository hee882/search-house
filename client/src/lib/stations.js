// Node 테스트 러너는 확장자 없는 상대 경로를 해석하지 못하므로 lib 모듈끼리는 확장자를 붙여 가져온다.
import { getChosung } from './hangul.js';

// 지하철 호선별 공식 색상
export const LINE_COLORS = {
  '1호선': '#0052A4', '2호선': '#00A84D', '3호선': '#EF7C1C', '4호선': '#00A5DE',
  '5호선': '#996CAC', '6호선': '#CD7C2F', '7호선': '#747F00', '8호선': '#E6186C',
  '9호선': '#BDB092',
  '수인분당선': '#F5A200', '신분당선': '#D4003B', '경의중앙선': '#77C4A3',
  '경의선': '#77C4A3', '경춘선': '#0C8E72', '경강선': '#003DA5',
  '공항철도': '#0090D2', '서해선': '#81A914',
  '우이신설선': '#B7C452', '신림선': '#6789CA', '에버라인': '#55B332',
  '김포골드라인': '#A17E00', '의정부경전철': '#FDA600',
  '신안산선': '#A71E31', '위례신사선': '#F5A200', '동북선': '#2E8B57',
  '인천1호선': '#7CA8D5', '인천2호선': '#ED8000',
  'GTX-A': '#9A6292',
};

export const getLineColor = (line) => LINE_COLORS[line.trim()] || '#A0AEC0';
export const getShortLineName = (line) => line.trim();

export const STATION_ALIASES = {
  '총신대입구역': ['이수역', '이수'],
  '총신대입구(이수)역': ['이수역', '이수'],
  '이수역': ['총신대입구역', '총신대입구'],
  '서울역': ['서울'],
  '잠실역': ['신천역', '잠실새내역'],
};

export const searchStations = (stations, keyword, selectedName) => {
  if (!keyword || keyword === selectedName) return stations.slice(0, 5);
  const kw = keyword.trim();
  const searchChosung = getChosung(kw);
  const isChosungOnly = /^[ㄱ-ㅎ]+$/.test(kw);
  return stations
    .filter(s => {
      const nameMatch = s.name.includes(kw) || getChosung(s.name).includes(searchChosung);
      if (nameMatch) return true;
      const aliases = STATION_ALIASES[s.name] || [];
      return aliases.some(alias => alias.includes(kw) || getChosung(alias).includes(searchChosung));
    })
    .sort((a, b) => {
      const score = (s) => {
        const n = s.name;
        const aliases = STATION_ALIASES[n] || [];
        const isAliasMatch = aliases.some(a => a === kw || a === kw + '역');
        let sc = (s.line?.split(',').length || 1) * 2;
        if (n === kw || n === kw + '역' || isAliasMatch) sc += 100;
        else if (n.startsWith(kw)) sc += 50;
        else if (!isChosungOnly && n.includes(kw)) sc += 20;
        else if (getChosung(n).startsWith(searchChosung)) sc += 15;
        return sc;
      };
      return score(b) - score(a);
    })
    .slice(0, 15);
};
