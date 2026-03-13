import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { Search, MapPin, Coins, Car, Bus, Loader2, ChevronDown, ExternalLink, Trophy, Zap, Coffee, ShieldCheck, Map as MapIcon, List, Settings2, Pencil, Train, X } from 'lucide-react';
import { useMap, addMarker, addOverlay, clearMarkers, drawPolyline, setBounds, getZoom, setZoom } from './lib/map';

// 지하철 호선별 공식 색상
const LINE_COLORS = {
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

const getLineColor = (line) => LINE_COLORS[line.trim()] || '#A0AEC0';
const getShortLineName = (line) => line.trim();

const getNaverLandUrl = (name) => {
  const q = encodeURIComponent((name || '').trim());
  const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
  return isMobile
    ? `https://m.land.naver.com/search?query=${q}`
    : `https://fin.land.naver.com/search?query=${q}`;
};

function LineBadge({ line }) {
  if (!line) return null;
  const lines = line.split(/[,,/]/);
  return (
    <div className="flex gap-1 items-center flex-nowrap">
      {lines.map((l, i) => (
        <div key={i} className="px-1.5 py-0.5 rounded-md text-[8px] font-black text-white shadow-sm flex items-center justify-center whitespace-nowrap leading-tight" style={{ backgroundColor: getLineColor(l) }}>
          {getShortLineName(l)}
        </div>
      ))}
    </div>
  );
}

const getChosung = (str) => {
  const cho = ["ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"];
  let result = "";
  for (let i = 0; i < str.length; i++) {
    const code = str.charCodeAt(i) - 44032;
    if (code > -1 && code < 11172) result += cho[Math.floor(code / 588)];
    else result += str.charAt(i);
  }
  return result;
};

const STATION_ALIASES = {
  '총신대입구역': ['이수역', '이수'],
  '총신대입구(이수)역': ['이수역', '이수'],
  '이수역': ['총신대입구역', '총신대입구'],
  '서울역': ['서울'],
  '잠실역': ['신천역', '잠실새내역'],
};

function StationSearch({ value, onChange, placeholder, stations, icon: IconComponent, colorClass, stationLoading, stationError, onRetry }) {
  const [keyword, setKeyword] = useState(value?.name || "");
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const dropdownRef = useRef(null);

  const filteredStations = useMemo(() => {
    if (!keyword || keyword === value?.name) return stations.slice(0, 5);
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
      .slice(0, 10);
  }, [keyword, stations, value]);

  useEffect(() => {
    const handleClickOutside = (e) => { if (dropdownRef.current && !dropdownRef.current.contains(e.target)) setIsOpen(false); };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSelect = (station) => {
    onChange(station);
    setKeyword(station.name);
    setIsOpen(false);
    setSelectedIndex(-1);
  };

  return (
    <div className="relative group w-full" ref={dropdownRef}>
      {IconComponent && <IconComponent className={`absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-300 group-focus-within:${colorClass} transition-colors`} />}
      <input
        type="text" value={keyword}
        onChange={(e) => { setKeyword(e.target.value); setIsOpen(true); }}
        onFocus={() => setIsOpen(true)}
        className="w-full pl-10 pr-4 py-2.5 bg-gray-50 border border-transparent rounded-xl text-[13px] font-black focus:bg-white focus:border-blue-500 outline-none transition-all placeholder:text-gray-300"
        placeholder={placeholder}
      />
      {isOpen && (stationLoading || stationError || filteredStations.length > 0) && (
        <div className="absolute bottom-full md:bottom-auto md:top-full left-0 w-full mb-2 md:mt-1.5 bg-white rounded-2xl shadow-[0_20px_50px_rgba(0,0,0,0.15)] border border-gray-100 z-[2000] overflow-hidden">
          {stationLoading ? (
            <div className="px-4 py-6 text-center"><Loader2 className="animate-spin mx-auto mb-2 text-blue-400" size={20} /><div className="text-[11px] font-bold text-gray-400">역 데이터 로딩 중...</div></div>
          ) : stationError ? (
            <div className="px-4 py-4 text-center"><div className="text-[11px] font-bold text-red-400 mb-2">데이터를 불러올 수 없습니다</div><button onClick={onRetry} className="text-[11px] font-black text-blue-500 hover:underline">재시도</button></div>
          ) : (
          <>
          <div className="px-4 py-1.5 bg-gray-50/50 text-[9px] font-black text-gray-400 uppercase tracking-widest border-b border-gray-100 text-center">
            {!keyword ? '주요 거점 추천' : '검색 결과'}
          </div>
          {filteredStations.map((s, i) => (
            <button key={i} onClick={() => handleSelect(s)} onMouseEnter={() => setSelectedIndex(i)} className={`w-full text-left px-4 py-3 flex items-center gap-4 transition-all duration-200 ${selectedIndex === i ? 'bg-blue-50/80 border-l-[4px] border-blue-500 pl-3' : 'text-gray-600 border-b border-gray-50 last:border-0'}`}>
              <div className={`shrink-0 p-2 rounded-xl transition-colors ${selectedIndex === i ? 'bg-white shadow-sm' : 'bg-gray-100'}`}>
                <Train className={`h-4 w-4 ${selectedIndex === i ? 'text-blue-500' : 'text-gray-400'}`} />
              </div>
              <div className="flex-1 min-w-0">
                <div className={`text-[15px] font-black tracking-tight truncate ${selectedIndex === i ? 'text-blue-700' : 'text-gray-800'}`}>
                  {s.name}
                  {STATION_ALIASES[s.name] && (
                    <span className="ml-1.5 text-[12px] font-bold text-gray-400 group-hover:text-blue-400">
                      ({STATION_ALIASES[s.name][0].replace('역', '')})
                    </span>
                  )}
                </div>
                <div className="mt-1 flex items-center gap-2 overflow-x-auto no-scrollbar">
                  <LineBadge line={s.line} />
                </div>
              </div>
            </button>
          ))}
          </>
          )}
        </div>
      )}
    </div>
  );
}

function App() {
  const [mapCenter] = useState({ lat: 37.5665, lng: 126.9780 });
  const [zoomLevel] = useState(15);
  const [mode, setMode] = useState('single');
  const [residentType, setResidentType] = useState('buy');
  const [housingRatio, setHousingRatio] = useState(0.25);
  const [roomType, setRoomType] = useState('all');
  const [buildingAge, setBuildingAge] = useState(0);
  const [inputsCollapsed, setInputsCollapsed] = useState(false);
  const [inputs, setInputs] = useState({
    user1: { workplace: null, salary: 4000, transport: 'public' },
    user2: { workplace: null, salary: 4000, transport: 'public' }
  });
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(window.innerWidth >= 768);
  const [expandedSpotIndex, setExpandedSpotIndex] = useState(null);
  const [expandedComplexIdx, setExpandedComplexIdx] = useState(0);
  const [workplaceLocs, setWorkplaceLocs] = useState({ user1: null, user2: null });
  const [stationList, setStationList] = useState([]);
  const [stationLoading, setStationLoading] = useState(true);
  const [stationError, setStationError] = useState(null);

  const mapContainerRef = useRef(null);
  const markersRef = useRef([]);
  const pathsRef = useRef([]);
  const { map, isReady, error: mapError } = useMap(mapContainerRef, { center: mapCenter, zoom: zoomLevel });

  const API_BASE_URL = import.meta.env.VITE_API_URL || 'https://search-house.onrender.com';

  const fetchStations = useCallback(async () => {
    setStationLoading(true);
    setStationError(null);
    for (let i = 0; i < 3; i++) {
      try {
        const res = await fetch(`${API_BASE_URL}/api/stations`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data.length > 0) { setStationList(data); setStationLoading(false); return; }
        throw new Error('빈 데이터');
      } catch (e) {
        if (i === 2) { setStationError(e.message); setStationLoading(false); return; }
        await new Promise(r => setTimeout(r, 1500 * (i + 1)));
      }
    }
  }, [API_BASE_URL]);

  useEffect(() => { fetchStations(); }, [fetchStations]);

  const drawCommutePaths = useCallback((spot, workplaceLocs, mode) => {
    if (!map) return;
    pathsRef.current.forEach(p => p.setMap(null));
    pathsRef.current = [];
    const pts = [{ lat: spot.lat, lng: spot.lng }];
    if (workplaceLocs.user1) {
      pts.push(workplaceLocs.user1);
      const p1 = drawPolyline(map, [{ lat: spot.lat, lng: spot.lng }, { lat: workplaceLocs.user1.lat, lng: workplaceLocs.user1.lng }], { color: '#3B82F6', style: 'dashed', weight: 5, label: `나: ${spot.commute_time_1}분` });
      if (p1) pathsRef.current.push(p1);
    }
    if (mode === 'couple' && workplaceLocs.user2) {
      pts.push(workplaceLocs.user2);
      const p2 = drawPolyline(map, [{ lat: spot.lat, lng: spot.lng }, { lat: workplaceLocs.user2.lat, lng: workplaceLocs.user2.lng }], { color: '#EC4899', style: 'dashed', weight: 5, label: `배우자: ${spot.commute_time_2}분` });
      if (p2) pathsRef.current.push(p2);
    }
    setBounds(map, pts);
  }, [map]);

  const handleSpotClick = useCallback((spot, index) => {
    const isAlreadyExpanded = expandedSpotIndex === index;
    setExpandedSpotIndex(isAlreadyExpanded ? null : index);
    setExpandedComplexIdx(0);
    if (!isAlreadyExpanded) {
      drawCommutePaths(spot, workplaceLocs, mode);
      if (window.innerWidth < 768) setIsSidebarOpen(false);
    } else {
      pathsRef.current.forEach(p => p.setMap(null));
      pathsRef.current = [];
      const allPts = [...results, workplaceLocs.user1];
      if (workplaceLocs.user2) allPts.push(workplaceLocs.user2);
      setBounds(map, allPts);
      setTimeout(() => { const currentZoom = getZoom(map); setZoom(map, currentZoom - 2); }, 300);
    }
  }, [expandedSpotIndex, workplaceLocs, mode, drawCommutePaths, results, map]);

  useEffect(() => {
    if (!map || !isReady) return;
    clearMarkers(markersRef.current);
    markersRef.current = [];
    if (results) {
      results.forEach((spot, index) => {
        const isSelected = expandedSpotIndex === index;
        const zIndex = isSelected ? 1000 : (100 - index);
        const content = `
          <div style="cursor:pointer; position: absolute; left: 0; bottom: 40px; transform: translateX(-50%); z-index: ${zIndex};" onclick="window.dispatchSpotClick(${index})">
            <div style="background:${isSelected ? '#3B82F6' : 'rgba(31,41,55,0.9)'}; backdrop-filter: blur(8px); color:white; padding: 10px 18px; border-radius: 40px; font-weight: 900; font-size: 14px; white-space: nowrap; border: 2.5px solid ${isSelected ? '#FACC15' : 'white'}; box-shadow: 0 12px 30px rgba(0,0,0,0.25); transition: all 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275); ${isSelected ? 'transform: scale(1.1);' : ''}">
              <div style="display:flex; align-items:center; gap:8px;">
                <span style="font-size: 16px;">${index === 0 ? '🏆' : (index+1)}</span>
                <span style="letter-spacing: -0.02em;">${spot.name}</span>
              </div>
            </div>
            <div style="width: 3px; height: 12px; background: ${isSelected ? '#FACC15' : 'white'}; margin: 0 auto; box-shadow: 0 2px 5px rgba(0,0,0,0.2);"></div>
          </div>
        `;
        const overlay = addOverlay(map, { lat: spot.lat, lng: spot.lng, content });
        if (overlay) markersRef.current.push(overlay);
      });
    }
    if (workplaceLocs.user1) {
      const m1 = addMarker(map, { lat: workplaceLocs.user1.lat, lng: workplaceLocs.user1.lng, title: "나의 직장" });
      if (m1) markersRef.current.push(m1);
    }
    if (mode === 'couple' && workplaceLocs.user2) {
      const m2 = addMarker(map, { lat: workplaceLocs.user2.lat, lng: workplaceLocs.user2.lng, title: "배우자 직장" });
      if (m2) markersRef.current.push(m2);
    }
  }, [map, isReady, results, workplaceLocs, mode, expandedSpotIndex]);

  useEffect(() => {
    window.dispatchSpotClick = (index) => { if (results && results[index]) handleSpotClick(results[index], index); };
  }, [results, handleSpotClick]);

  const handleSearch = async () => {
    if (!inputs.user1.workplace) { alert("나의 직장 위치를 선택해 주세요."); return; }
    setLoading(true);
    try {
      const loc1 = inputs.user1.workplace;
      const loc2 = mode === 'couple' ? inputs.user2.workplace : null;
      setWorkplaceLocs({ user1: loc1, user2: loc2 });
      const areaMap = { all: [40, 200], '2': [40, 60], '3': [60, 85], '4': [85, 200] };
      const [minArea, maxArea] = areaMap[roomType] || areaMap.all;
      const payload = { mode, resident_type: residentType, housing_ratio: housingRatio, min_area: minArea, max_area: maxArea, max_building_age: buildingAge, user1: { workplace: loc1, salary: inputs.user1.salary, transport: inputs.user1.transport }, user2: loc2 ? { workplace: loc2, salary: inputs.user2.salary, transport: inputs.user2.transport } : null };
      const response = await fetch(`${API_BASE_URL}/api/optimize`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const data = await response.json();
      setResults(data.results);
      if (data.results?.length > 0) setInputsCollapsed(true);
      if (window.innerWidth < 768) setIsSidebarOpen(false);
      if (data.results?.length > 0) {
        const allPts = [...data.results, loc1];
        if (loc2) allPts.push(loc2);
        setBounds(map, allPts);
        setTimeout(() => { const currentZoom = getZoom(map); setZoom(map, currentZoom - 2); }, 300);
        setExpandedSpotIndex(0);
        setExpandedComplexIdx(0);
        setTimeout(() => { drawCommutePaths(data.results[0], { user1: loc1, user2: loc2 }, mode); }, 600);
      }
    } catch (err) { console.error(err); alert("분석 중 오류가 발생했습니다."); } finally { setLoading(false); }
  };

  return (
    <div className="relative w-full h-[100dvh] overflow-hidden antialiased bg-gray-50 text-gray-900 font-sans">
      {/* 1. Map Layer */}
      <div ref={mapContainerRef} className="absolute inset-0 w-full h-full z-0 bg-gray-100 flex items-center justify-center">
        {!isReady && !mapError && (
          <div className="flex flex-col items-center space-y-4">
            <Loader2 className="animate-spin text-blue-500" size={40} />
            <p className="text-sm font-bold text-gray-400 text-center px-6">지능형 지도를 로드하고 있습니다...</p>
          </div>
        )}
      </div>

      {/* 2. Unified Sidebar/Bottom Sheet */}
      <div className={`absolute z-[1000] transition-all duration-500 ease-in-out flex flex-col 
        md:inset-y-0 md:left-0 md:w-[420px] md:bg-white md:border-r md:border-gray-100 md:shadow-2xl
        ${window.innerWidth < 768 
          ? (isSidebarOpen ? 'inset-x-0 bottom-0 h-[85vh] bg-white rounded-t-[2.5rem] shadow-[0_-20px_60px_rgba(0,0,0,0.15)] overflow-hidden' : 'inset-x-0 bottom-[-100%]')
          : (isSidebarOpen ? 'translate-x-0' : '-translate-x-full')
        }
      `}>
        <div className="flex flex-col h-full">
          {/* Header Area - Fixed height to ensure visibility */}
          <div className="p-6 md:p-8 shrink-0 relative bg-white z-[100] border-b border-gray-50">
            <div className="flex items-center justify-between mb-4 md:mb-6">
              <div className="flex items-center space-x-3 cursor-pointer" onClick={() => window.location.reload()}>
                <img src="logo.svg" alt="Logo" className="w-8 h-8 md:w-12 md:h-12" />
                <span className="text-lg md:text-2xl font-black uppercase tracking-tight">Search House</span>
              </div>
              <button onClick={() => setIsSidebarOpen(false)} className="p-2 bg-gray-100 rounded-full md:hidden transition-colors active:bg-gray-200"><X size={20} /></button>
            </div>

            {inputsCollapsed ? (
              <div className="space-y-3">
                <div className="flex flex-wrap gap-1.5">
                  <span className="text-[10px] font-black bg-blue-50 text-blue-600 px-2 py-1 rounded-full">{inputs.user1.workplace?.name || '미선택'}</span>
                  <span className="text-[10px] font-black bg-gray-100 text-gray-500 px-2 py-1 rounded-full">{inputs.user1.salary}만</span>
                  {mode === 'couple' && <span className="text-[10px] font-black bg-pink-50 text-pink-500 px-2 py-1 rounded-full">{inputs.user2.workplace?.name || ''} {inputs.user2.salary}만</span>}
                  <span className="text-[10px] font-black bg-gray-100 text-gray-500 px-2 py-1 rounded-full">주거비 {Math.round(housingRatio * 100)}%</span>
                  <span className="text-[10px] font-black bg-gray-100 text-gray-500 px-2 py-1 rounded-full">{roomType === 'all' ? '전체' : roomType + '룸'}{buildingAge > 0 ? ` · ${buildingAge}년` : ''}</span>
                </div>
                <button onClick={() => setInputsCollapsed(false)} className="w-full py-2 bg-gray-100 hover:bg-gray-200 rounded-xl text-[11px] font-black text-gray-500 flex items-center justify-center gap-1.5 transition-colors">
                  <Settings2 size={13} /> 조건 수정
                </button>
              </div>
            ) : (
            <div className="space-y-3 md:space-y-4">
              <div className="bg-blue-50/80 p-3 rounded-xl border border-blue-100 shadow-sm hidden md:block">
                <div className="flex items-center space-x-2 text-blue-600 mb-1">
                  <ShieldCheck size={16} /><span className="text-[10px] font-black uppercase tracking-widest">Fatigue Model v1.0</span>
                </div>
                <p className="text-[11px] font-bold text-gray-600 leading-tight">인생 시급과 워라밸 가치를 반영한 최적의 입지 분석</p>
              </div>

              <div className="flex p-1 bg-gray-100 rounded-xl">
                <button onClick={() => setMode('single')} className={`flex-1 py-1.5 rounded-lg text-[11px] font-black transition-all ${mode === 'single' ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400'}`}>1인 가구</button>
                <button onClick={() => setMode('couple')} className={`flex-1 py-1.5 rounded-lg text-[11px] font-black transition-all ${mode === 'couple' ? 'bg-white shadow-sm text-pink-500' : 'text-gray-400'}`}>부부/커플</button>
              </div>

              <div className="space-y-3">
                <div className="space-y-1">
                  <div className="text-[10px] font-black text-gray-400 uppercase tracking-widest pl-1">직장 위치</div>
                  <StationSearch stations={stationList} value={inputs.user1.workplace} onChange={(val) => setInputs({...inputs, user1: {...inputs.user1, workplace: val}})} placeholder="나의 직장 위치 검색" icon={MapPin} colorClass="text-blue-500" stationLoading={stationLoading} stationError={stationError} onRetry={fetchStations} />
                </div>
                <div className="flex gap-2">
                  <div className="flex-1 space-y-1">
                    <div className="text-[10px] font-black text-gray-400 uppercase tracking-widest pl-1">연봉 (만원)</div>
                    <div className="relative group"><Coins className="absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-300" /><input type="number" value={inputs.user1.salary} onChange={(e) => setInputs({...inputs, user1: {...inputs.user1, salary: parseInt(e.target.value)||0}})} className="w-full pl-10 pr-4 py-2.5 bg-gray-50 border-none rounded-xl text-[13px] font-black outline-none focus:ring-2 focus:ring-blue-500/20" /></div>
                  </div>
                  <div className="shrink-0 space-y-1">
                    <div className="text-[10px] font-black text-gray-400 uppercase tracking-widest pl-1">이동 수단</div>
                    <div className="flex bg-gray-100 rounded-xl p-0.5 h-[42px]">
                      <button onClick={() => setInputs({...inputs, user1: {...inputs.user1, transport: 'public'}})} className={`px-3 rounded-lg ${inputs.user1.transport === 'public' ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400'}`}><Bus size={16} /></button>
                      <button onClick={() => setInputs({...inputs, user1: {...inputs.user1, transport: 'car'}})} className={`px-3 rounded-lg ${inputs.user1.transport === 'car' ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400'}`}><Car size={16} /></button>
                    </div>
                  </div>
                </div>
              </div>

              {mode === 'couple' && (
                <div className="space-y-3 pt-3 border-t border-gray-50 animate-in fade-in">
                  <div className="space-y-1">
                    <div className="text-[10px] font-black text-pink-400 uppercase tracking-widest pl-1">배우자 직장</div>
                    <StationSearch stations={stationList} value={inputs.user2.workplace} onChange={(val) => setInputs({...inputs, user2: {...inputs.user2, workplace: val}})} placeholder="배우자 직장 위치" icon={MapPin} colorClass="text-pink-500" stationLoading={stationLoading} stationError={stationError} onRetry={fetchStations} />
                  </div>
                  <div className="flex gap-2">
                    <div className="flex-1 space-y-1">
                      <div className="text-[10px] font-black text-pink-400 uppercase tracking-widest pl-1">연봉 (만원)</div>
                      <div className="relative group"><Coins className="absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-300" /><input type="number" value={inputs.user2.salary} onChange={(e) => setInputs({...inputs, user2: {...inputs.user2, salary: parseInt(e.target.value)||0}})} className="w-full pl-10 pr-4 py-2.5 bg-gray-50 border-none rounded-xl text-[13px] font-black outline-none focus:ring-2 focus:ring-pink-500/20" /></div>
                    </div>
                    <div className="shrink-0 space-y-1">
                      <div className="text-[10px] font-black text-pink-400 uppercase tracking-widest pl-1">이동 수단</div>
                      <div className="flex bg-gray-100 rounded-xl p-0.5 h-[42px]">
                        <button onClick={() => setInputs({...inputs, user2: {...inputs.user2, transport: 'public'}})} className={`px-3 rounded-lg ${inputs.user2.transport === 'public' ? 'bg-white shadow-sm text-pink-500' : 'text-gray-400'}`}><Bus size={16} /></button>
                        <button onClick={() => setInputs({...inputs, user2: {...inputs.user2, transport: 'car'}})} className={`px-3 rounded-lg ${inputs.user2.transport === 'car' ? 'bg-white shadow-sm text-pink-500' : 'text-gray-400'}`}><Car size={16} /></button>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              <div className="space-y-1.5">
                <div className="flex items-center justify-between px-1">
                  <div className="text-[10px] font-black text-gray-400 uppercase tracking-widest">소득 대비 주거비 한도</div>
                  <div className="text-[11px] font-black text-blue-600">
                    월 {Math.round(((mode === 'couple' ? inputs.user1.salary + inputs.user2.salary : inputs.user1.salary) * housingRatio / 12))}만원 이내
                  </div>
                </div>
                <div className="flex bg-gray-100 rounded-xl p-1 gap-0.5">
                  {[0.1, 0.2, 0.25, 0.3, 0.4].map((ratio) => (
                    <button key={ratio} onClick={() => setHousingRatio(ratio)} className={`flex-1 py-1.5 rounded-lg text-[11px] font-black transition-all ${housingRatio === ratio ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400 hover:text-gray-600'}`}>
                      {Math.round(ratio * 100)}%
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex gap-2">
                <div className="flex-1 space-y-1">
                  <div className="text-[10px] font-black text-gray-400 uppercase tracking-widest pl-1">방 타입</div>
                  <div className="flex bg-gray-100 rounded-xl p-0.5 gap-0.5">
                    {[['all', '전체'], ['2', '2룸'], ['3', '3룸'], ['4', '4룸+']].map(([val, label]) => (
                      <button key={val} onClick={() => setRoomType(val)} className={`flex-1 py-1.5 rounded-lg text-[11px] font-black transition-all ${roomType === val ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400'}`}>
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="flex-1 space-y-1">
                  <div className="text-[10px] font-black text-gray-400 uppercase tracking-widest pl-1">준공</div>
                  <div className="flex bg-gray-100 rounded-xl p-0.5 gap-0.5">
                    {[[0, '전체'], [5, '5년'], [10, '10년'], [20, '20년']].map(([val, label]) => (
                      <button key={val} onClick={() => setBuildingAge(val)} className={`flex-1 py-1.5 rounded-lg text-[11px] font-black transition-all ${buildingAge === val ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400'}`}>
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <button onClick={handleSearch} disabled={loading || !isReady} className="w-full bg-gray-900 hover:bg-black text-white font-black py-3.5 rounded-xl shadow-xl active:scale-[0.98] flex items-center justify-center space-x-2 transition-all">
                {loading ? <Loader2 className="animate-spin" size={20} /> : <Search size={20} strokeWidth={3} />}
                <span className="text-[14px]">스마트 주거 탐색 시작</span>
              </button>
            </div>
            )}
          </div>

          {/* Results Area - Scrollable within sidebar */}
          <div className="flex-1 overflow-y-auto px-6 py-4 custom-scrollbar space-y-3 border-t border-gray-50 bg-gray-50/30 pb-32">
            {results ? (
              <>
                <div className="flex items-center justify-between px-1 mb-1">
                  <h5 className="text-[10px] font-black text-gray-400 uppercase tracking-widest">최적 생존 입지 <span className="ml-1 text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded-full text-[9px]">{results.length}</span></h5>
                  <div className="flex items-center space-x-1 text-[9px] font-bold text-blue-500"><Zap size={11} className="fill-blue-500" /> <span>Al-Driven</span></div>
                </div>
                {results.map((spot, i) => {
                  const topApt = spot.complexes[0];
                  return (
                  <div key={i} className={`transition-all rounded-[1.5rem] border overflow-hidden ${expandedSpotIndex === i ? 'bg-white border-blue-200 shadow-xl ring-1 ring-blue-100' : 'bg-white border-gray-100 hover:border-gray-200'}`}>
                    {/* Card Header - Always visible */}
                    <button onClick={() => handleSpotClick(spot, i)} className="w-full p-4 pb-3 text-left">
                      <div className="flex justify-between items-start mb-3">
                        <div className="flex items-center space-x-3">
                          <div className={`w-8 h-8 rounded-xl flex items-center justify-center text-xs font-black shrink-0 ${i === 0 ? 'bg-blue-600 text-white shadow-md' : 'bg-gray-100 text-gray-400'}`}>{i === 0 ? <Trophy size={16} /> : i + 1}</div>
                          <div>
                            <div className="text-[9px] font-black text-blue-500 uppercase tracking-tighter mb-0.5">{spot.name} 인근</div>
                            <h6 className="text-[14px] font-black tracking-tighter text-gray-900 leading-none truncate max-w-[180px]">{topApt?.name}</h6>
                          </div>
                        </div>
                        <div className="text-right shrink-0 ml-2">
                          <div className="text-[8px] font-black text-gray-300 uppercase mb-0.5">{topApt?.display_price_label}</div>
                          <div className="text-[12px] font-black text-gray-700 tracking-tight">{topApt?.display_price_value}</div>
                        </div>
                      </div>
                      {/* Cost comparison - the marketing hook */}
                      <div className="flex gap-2">
                        <div className="flex-1 bg-gray-50 rounded-xl p-2.5 text-center border border-gray-100">
                          <div className="text-[8px] font-black text-gray-400 uppercase mb-1">실제 지출</div>
                          <div className="text-[18px] font-black text-gray-900 tracking-tighter leading-none">{topApt?.fixed_monthly_exp}<span className="text-[11px] text-gray-400 ml-0.5">만</span></div>
                          <div className="text-[8px] font-bold text-gray-300 mt-0.5">주거비 + 교통비</div>
                        </div>
                        <div className="flex-1 bg-orange-50 rounded-xl p-2.5 text-center border border-orange-100">
                          <div className="text-[8px] font-black text-orange-500 uppercase mb-1">보이지 않는 비용</div>
                          <div className="text-[18px] font-black text-orange-600 tracking-tighter leading-none">{topApt?.hidden_life_cost}<span className="text-[11px] text-orange-400 ml-0.5">만</span></div>
                          <div className="text-[8px] font-bold text-orange-300 mt-0.5">당신의 시간 가치</div>
                        </div>
                      </div>
                      {/* Commute badges */}
                      <div className="flex items-center gap-2 mt-2.5">
                        <div className="flex items-center gap-1 bg-blue-50 px-2 py-1 rounded-lg">
                          {inputs.user1.transport === 'car' ? <Car size={10} className="text-blue-500" /> : <Bus size={10} className="text-blue-500" />}
                          <span className="text-[10px] font-black text-blue-600">{spot.commute_time_1}분</span>
                        </div>
                        {mode === 'couple' && spot.commute_time_2 > 0 && (
                          <div className="flex items-center gap-1 bg-pink-50 px-2 py-1 rounded-lg">
                            {inputs.user2.transport === 'car' ? <Car size={10} className="text-pink-500" /> : <Bus size={10} className="text-pink-500" />}
                            <span className="text-[10px] font-black text-pink-600">{spot.commute_time_2}분</span>
                          </div>
                        )}
                        <div className="ml-auto text-[9px] font-black text-gray-300">월 총 {spot.total_cost}만 손실</div>
                        <ChevronDown size={14} className={`text-gray-300 transition-transform ${expandedSpotIndex === i ? 'rotate-180' : ''}`} />
                      </div>
                    </button>

                    {/* Expanded Detail */}
                    {expandedSpotIndex === i && (
                      <div className="px-4 pb-4 animate-in slide-in-from-top-4 duration-500">
                        <div className="h-px bg-gray-100 mb-3" />
                        {/* Other complexes */}
                        {spot.complexes.length > 1 && (
                          <div className="space-y-1.5 mb-3">
                            <div className="text-[9px] font-black text-gray-400 uppercase tracking-widest px-1">같은 역세권 다른 단지</div>
                            {spot.complexes.map((apt, idx) => (
                              <div key={idx} onClick={() => setExpandedComplexIdx(idx)} className={`p-2.5 rounded-xl border transition-all cursor-pointer ${expandedComplexIdx === idx ? 'bg-blue-50 border-blue-200' : 'bg-gray-50/50 border-transparent'}`}>
                                <div className="flex justify-between items-center gap-2">
                                  <div className="flex items-center space-x-1.5 overflow-hidden">
                                    <span className={`text-[12px] font-black tracking-tight truncate ${expandedComplexIdx === idx ? 'text-blue-700' : 'text-gray-700'}`}>{apt.name}</span>
                                    <ExternalLink size={9} className="text-gray-300 shrink-0 hover:text-blue-500 transition-colors" onClick={(e) => { e.stopPropagation(); window.open(getNaverLandUrl(apt.name), '_blank'); }} />
                                  </div>
                                  <div className="text-right shrink-0">
                                    <span className="text-[10px] font-black text-blue-600">{apt.display_price_value}</span>
                                  </div>
                                </div>
                                {expandedComplexIdx === idx && (
                                  <div className="mt-2 flex gap-1.5 animate-in fade-in duration-300">
                                    <div className="flex-1 bg-white py-1.5 rounded-lg text-center border border-gray-100"><div className="text-[8px] font-black text-gray-400">실제 지출</div><div className="text-[11px] font-black text-gray-800">{apt.fixed_monthly_exp}만</div></div>
                                    <div className="flex-1 bg-white py-1.5 rounded-lg text-center border border-orange-100"><div className="text-[8px] font-black text-orange-400">숨은 비용</div><div className="text-[11px] font-black text-orange-600">{apt.hidden_life_cost}만</div></div>
                                    <div className="flex-1 bg-white py-1.5 rounded-lg text-center border border-red-100"><div className="text-[8px] font-black text-red-400">총 손실</div><div className="text-[11px] font-black text-red-600">{apt.total_opp_cost}만</div></div>
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                        <button onClick={() => {const c = spot.complexes?.[expandedComplexIdx] || spot.complexes?.[0]; if(c) window.open(getNaverLandUrl(c.name), '_blank');}} className="w-full bg-gray-900 hover:bg-black text-white font-black py-3 rounded-xl text-xs transition-all flex items-center justify-center space-x-2 active:scale-95 shadow-lg">
                          <ExternalLink size={14} strokeWidth={3} /> <span>네이버 부동산 매물 보기</span>
                        </button>
                      </div>
                    )}
                  </div>
                  );
                })}
                <div className="mt-4 p-6 pb-32 bg-orange-50/50 rounded-[2rem] border border-orange-100 text-center space-y-2">
                  <div className="text-[20px]">&#9888;&#65039;</div>
                  <h6 className="text-[12px] font-black text-gray-900 leading-tight">"보이지 않는 비용"이 진짜 비용입니다</h6>
                  <p className="text-[10px] font-bold text-gray-500 leading-relaxed">매일 왕복 2시간 통근 = 연간 <span className="text-orange-600 font-black">480시간</span> = <span className="text-orange-600 font-black">20일</span>을 길 위에서 소비합니다.<br/>그 시간의 가치를 당신의 시급으로 환산하면?</p>
                </div>
              </>
            ) : (
              <div className="flex flex-col items-center justify-center text-center p-6 py-12 animate-in fade-in zoom-in duration-700">
                <div className="w-14 h-14 bg-blue-600/10 rounded-2xl flex items-center justify-center mb-6 relative"><div className="absolute inset-0 bg-blue-400 rounded-2xl animate-ping opacity-20" /><Coins size={24} className="text-blue-600" /></div>
                <h4 className="text-[19px] font-black text-gray-900 mb-5 tracking-tighter leading-[1.25]">매일 버려지는 당신의 시간은<br/><span className="text-blue-600 text-[21px]">수백만원의 기회비용</span>입니다</h4>
                <div className="space-y-4 max-w-[270px] mx-auto text-left">
                  <div className="flex items-start space-x-3"><div className="shrink-0 mt-1 w-4 h-4 rounded-full bg-blue-50 flex items-center justify-center"><Zap size={10} className="text-blue-600" /></div><p className="text-[11.5px] font-bold text-gray-500 leading-tight">왕복 2시간 통근은 <span className="text-gray-900 font-black">연간 약 20일</span>의 자유시간을 연기처럼 사라지게 만듭니다.</p></div>
                  <div className="flex items-start space-x-3"><div className="shrink-0 mt-1 w-4 h-4 rounded-full bg-green-50 flex items-center justify-center"><ShieldCheck size={10} className="text-green-600" /></div><p className="text-[11.5px] font-bold text-gray-500 leading-tight">당신의 <span className="text-gray-900 font-black">인생 시급</span>을 기준으로 가장 '풍요로운' 삶을 찾아보세요.</p></div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 3. Mobile Result Carousel (Slider) */}
      {results && !isSidebarOpen && (
        <div className="md:hidden absolute bottom-6 inset-x-0 z-[1100] flex overflow-x-auto no-scrollbar gap-4 px-4 snap-x">
          {results.map((spot, i) => (
            <div key={i} onClick={() => handleSpotClick(spot, i)} className={`flex-none w-[80vw] snap-center bg-white/90 backdrop-blur-xl p-5 rounded-[2rem] shadow-2xl border-2 transition-all ${expandedSpotIndex === i ? 'border-blue-500' : 'border-transparent'}`}>
              <div className="flex justify-between items-center">
                <div className="flex items-center gap-3">
                  <div className={`w-10 h-10 rounded-2xl flex items-center justify-center font-black ${i === 0 ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-400'}`}>{i + 1}</div>
                  <div><div className="text-[10px] font-black text-blue-500 uppercase">{spot.name} 인근</div><h6 className="text-base font-black tracking-tight truncate w-32">{spot.complexes[0]?.name}</h6></div>
                </div>
                <div className="text-right"><div className="text-[18px] font-black text-gray-900 leading-none">월 {spot.total_cost}만</div><div className="text-[9px] font-black text-gray-300 uppercase mt-1">총 손실 비용</div></div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 4. Unified Mobile FAB */}
      <button 
        onClick={() => setIsSidebarOpen(!isSidebarOpen)}
        className="md:hidden absolute bottom-8 right-6 z-[1100] w-14 h-14 bg-gray-900 text-white rounded-2xl shadow-2xl flex items-center justify-center active:scale-90 transition-all border-2 border-white/20"
      >
        {isSidebarOpen ? <X size={24} /> : (results ? <List size={24} /> : <Search size={24} />)}
      </button>
    </div>
  );
}

export default App;
