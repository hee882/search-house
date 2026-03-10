import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { Search, MapPin, Coins, User, Heart, Car, Bus, Navigation, Loader2, ChevronRight, X, ChevronDown, ChevronUp, ExternalLink, Calculator, Clock, Wallet, Building2, Key, Edit3, Info, Scale, Sunrise, Sparkles, Trophy, Zap, Coffee, BatteryCharging, ShieldCheck, Menu, ChevronLeft } from 'lucide-react';
import { useMap, addMarker, addOverlay, clearMarkers, geocodeAddress, drawPolyline, setBounds } from './lib/map';

// 지하철 호선별 공식 색상
const LINE_COLORS = {
  '1호선': '#0052A4', '2호선': '#00A84D', '3호선': '#EF7C1C', '4호선': '#00A5DE',
  '5호선': '#996CAC', '6호선': '#CD7C2F', '7호선': '#747F00', '8호선': '#E6186C',
  '9호선': '#BDB092', '수인분당선': '#F5A200', '신분당선': '#D4003B', '경의중앙선': '#77C4A3',
  '경의선': '#77C4A3', '경춘선': '#0C8E72', '공항철도': '#0090D2', '서해선': '#81A914', 
  '경강선': '#003DA5', 'GTX-A': '#9A6292', '우이신설선': '#B7C452', '신림선': '#6789CA'
};

const getLineColor = (line) => LINE_COLORS[line.trim()] || '#A0AEC0';
const getShortLineName = (line) => {
  const l = line.trim();
  if (l.endsWith('호선')) return l.replace('호선', '');
  if (l.endsWith('선')) return l.replace('선', '');
  return l;
};

function LineBadge({ line }) {
  if (!line) return null;
  const lines = line.split(/[,,/]/);
  return (
    <div className="flex flex-wrap gap-1 items-center">
      {lines.map((l, i) => (
        <div key={i} className="px-1.5 py-0.5 rounded-md text-[9px] font-black text-white shadow-sm flex items-center justify-center min-w-[18px]" style={{ backgroundColor: getLineColor(l) }}>
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

function StationSearch({ value, onChange, placeholder, stations, icon: Icon, colorClass }) {
  const [keyword, setKeyword] = useState(value?.name || "");
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const dropdownRef = useRef(null);

  const filteredStations = useMemo(() => {
    if (!keyword || keyword === value?.name) return stations.slice(0, 5);
    const searchChosung = getChosung(keyword);
    return stations.filter(s => s.name.includes(keyword) || getChosung(s.name).includes(searchChosung)).slice(0, 8);
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
      <Icon className={`absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-300 group-focus-within:${colorClass} transition-colors`} />
      <input
        type="text" value={keyword}
        onChange={(e) => { setKeyword(e.target.value); setIsOpen(true); }}
        onFocus={() => setIsOpen(true)}
        className="w-full pl-12 pr-4 py-4 bg-gray-50 border border-transparent rounded-2xl text-[15px] font-bold focus:bg-white focus:border-blue-500 outline-none transition-all placeholder:text-gray-300 shadow-inner"
        placeholder={placeholder}
      />
      {isOpen && filteredStations.length > 0 && (
        <div className="absolute top-full left-0 w-full mt-2 bg-white rounded-2xl shadow-[0_20px_50px_rgba(0,0,0,0.15)] border border-gray-100 z-[2000] overflow-hidden">
          <div className="px-4 py-2 bg-gray-50/50 text-[10px] font-black text-gray-400 uppercase tracking-widest border-b border-gray-100 text-center">
            {!keyword ? '주요 거점 추천' : '검색 결과'}
          </div>
          {filteredStations.map((s, i) => (
            <button key={i} onClick={() => handleSelect(s)} onMouseEnter={() => setSelectedIndex(i)} className={`w-full text-left px-5 py-4 flex items-center transition-colors ${selectedIndex === i ? 'bg-blue-50 text-blue-600' : 'text-gray-600 border-b border-gray-50 last:border-0'}`}>
              <div className="w-16 shrink-0"><LineBadge line={s.line} /></div>
              <div className="flex-1 text-base font-black tracking-tight">{s.name}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function App() {
  const [mapCenter, setMapCenter] = useState({ lat: 37.5665, lng: 126.9780 });
  const [zoomLevel, setZoomLevel] = useState(15);
  const [mode, setMode] = useState('single');
  const [residentType, setResidentType] = useState('buy');
  const [loading, setLoading] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const [expandedSpotIndex, setExpandedSpotIndex] = useState(null);
  const [expandedComplexIdx, setExpandedComplexIdx] = useState(0);
  const [workplaceLocs, setWorkplaceLocs] = useState({ user1: null, user2: null });
  const [stationList, setStationList] = useState([]);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  const [inputs, setInputs] = useState({
    user1: { workplace: null, salary: 5000, transport: 'public' },
    user2: { workplace: null, salary: 4500, transport: 'public' },
  });

  const [results, setResults] = useState(null);
  const mapContainerRef = useRef(null);
  const markersRef = useRef([]);
  const pathsRef = useRef([]);

  const { map, isReady, error: mapError } = useMap(mapContainerRef, { center: mapCenter, zoom: zoomLevel });

  const API_BASE_URL = import.meta.env.VITE_API_URL || 'https://search-house.onrender.com';

  useEffect(() => {
    fetch(`${API_BASE_URL}/api/stations`).then(res => res.json()).then(setStationList).catch(console.error);
  }, []);

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
    }
  }, [expandedSpotIndex, workplaceLocs, mode, drawCommutePaths, results]);

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

  const calculateHourly = (salaryManWon) => Math.round((salaryManWon * 10000) / 12 / 209);

  const handleSearch = async () => {
    if (!inputs.user1.workplace) { alert("나의 직장 위치를 선택해 주세요."); return; }
    setLoading(true);
    try {
      const loc1 = inputs.user1.workplace;
      const loc2 = mode === 'couple' ? inputs.user2.workplace : null;
      setWorkplaceLocs({ user1: loc1, user2: loc2 });
      const payload = { mode, resident_type: residentType, user1: { workplace: loc1, salary: inputs.user1.salary, transport: inputs.user1.transport }, user2: loc2 ? { workplace: loc2, salary: inputs.user2.salary, transport: inputs.user2.transport } : null };
      const response = await fetch(`${API_BASE_URL}/api/optimize`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const data = await response.json();
      setResults(data.results);
      setIsMinimized(true);
      if (data.results?.length > 0) {
        const allPts = [...data.results, loc1];
        if (loc2) allPts.push(loc2);
        setBounds(map, allPts);
        setExpandedSpotIndex(0);
        setExpandedComplexIdx(0);
        setTimeout(() => { drawCommutePaths(data.results[0], { user1: loc1, user2: loc2 }, mode); }, 600);
      }
    } catch (e) { alert("분석 중 오류가 발생했습니다."); } finally { setLoading(false); }
  };

  return (
    <div className="relative w-full h-screen overflow-hidden antialiased bg-gray-50 text-gray-900 font-sans">
      {/* Map Layer */}
      <div ref={mapContainerRef} className="absolute inset-0 w-full h-full z-0 bg-gray-100 flex items-center justify-center">
        {!isReady && !mapError && (
          <div className="flex flex-col items-center space-y-4">
            <Loader2 className="animate-spin text-blue-500" size={40} />
            <p className="text-sm font-bold text-gray-400 text-center">지능형 지도를 로드하고 있습니다...</p>
          </div>
        )}
      </div>

      {/* Mobile Toggle Button */}
      <button 
        onClick={() => setIsSidebarOpen(true)}
        className={`md:hidden absolute bottom-8 left-1/2 -translate-x-1/2 z-[1100] px-6 py-3.5 bg-gray-900 text-white rounded-full shadow-2xl flex items-center space-x-2 font-black transition-all active:scale-95 ${isSidebarOpen ? 'translate-y-24 opacity-0' : 'translate-y-0 opacity-100'}`}
      >
        <Search size={18} />
        <span>분석 도구 열기</span>
      </button>

      {/* Sidebar / Bottom Sheet */}
      <div className={`absolute z-[1000] bg-white transition-all duration-500 ease-in-out flex flex-col border-gray-100
        ${isSidebarOpen 
          ? 'inset-x-0 bottom-0 h-[85vh] md:h-full md:inset-y-0 md:left-0 md:w-[420px] md:border-r shadow-[0_-10px_40px_rgba(0,0,0,0.1)] md:shadow-[10px_0_40px_rgba(0,0,0,0.04)]' 
          : 'inset-x-0 bottom-[-100%] md:h-full md:inset-y-0 md:left-[-420px] md:w-[420px]'
        }
      `}>
        
        {/* Mobile Handle Bar */}
        <div className="md:hidden w-full h-8 shrink-0 flex items-center justify-center cursor-pointer" onClick={() => setIsSidebarOpen(false)}>
          <div className="w-12 h-1.5 bg-gray-200 rounded-full" />
        </div>

        {/* Sidebar Header */}
        <div className="px-6 md:px-8 py-4 md:pt-10 shrink-0 border-b border-gray-50 relative">
          <button onClick={() => setIsSidebarOpen(false)} className="absolute top-4 right-4 p-2 text-gray-400 hover:text-gray-900 transition-colors">
            <X size={24} />
          </button>

          <div className="flex items-center space-x-3 cursor-pointer mb-6 md:mb-8" onClick={() => window.location.reload()}>
            <img src="logo.svg" alt="Logo" className="w-10 h-10 md:w-12 md:h-12 shrink-0 object-contain" />
            <span className="text-xl md:text-2xl font-black tracking-[-0.08em] uppercase text-gray-900 leading-none">Search House</span>
          </div>

          {!isMinimized ? (
            <div className="space-y-4 animate-in fade-in slide-in-from-top-4 duration-500">
              <div className="bg-blue-50/50 p-4 rounded-2xl border border-blue-100/50">
                <p className="text-[12px] md:text-[13px] font-bold text-gray-600 leading-tight">
                  <span className="text-blue-600">워라밸 생존</span>을 위한 지능형 입지 분석 엔진 v1.0
                </p>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div className="flex p-1 bg-gray-100 rounded-2xl">
                  <button onClick={() => setMode('single')} className={`flex-1 flex items-center justify-center py-2 rounded-xl text-[11px] md:text-xs font-black transition-all ${mode === 'single' ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400'}`}>1인</button>
                  <button onClick={() => setMode('couple')} className={`flex-1 flex items-center justify-center py-2 rounded-xl text-[11px] md:text-xs font-black transition-all ${mode === 'couple' ? 'bg-white shadow-sm text-pink-500' : 'text-gray-400'}`}>부부</button>
                </div>
                <div className="flex p-1 bg-gray-100 rounded-2xl">
                  <button onClick={() => setResidentType('buy')} className={`flex-1 flex items-center justify-center py-2 rounded-xl text-[11px] md:text-xs font-black transition-all ${residentType === 'buy' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-400'}`}>매매</button>
                  <button onClick={() => setResidentType('rent')} className={`flex-1 flex items-center justify-center py-2 rounded-xl text-[11px] md:text-xs font-black transition-all ${residentType === 'rent' ? 'bg-white shadow-sm text-gray-900' : 'text-gray-400'}`}>임대</button>
                </div>
              </div>
              <div className="space-y-3">
                <StationSearch stations={stationList} value={inputs.user1.workplace} onChange={(val) => setInputs({...inputs, user1: {...inputs.user1, workplace: val}})} placeholder="나의 직장 위치 (역 검색)" icon={MapPin} colorClass="text-blue-500" />
                <div className="flex gap-2">
                  <div className="flex-1 relative group">
                    <Coins className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-300" />
                    <input type="number" value={inputs.user1.salary} onChange={(e) => setInputs({...inputs, user1: {...inputs.user1, salary: parseInt(e.target.value)||0}})} className="w-full pl-12 pr-10 py-3.5 bg-gray-50 border border-transparent rounded-2xl text-[14px] md:text-[15px] font-black outline-none focus:bg-white focus:border-blue-500" />
                    <span className="absolute right-4 top-1/2 -translate-y-1/2 text-[10px] font-black text-gray-400">만원</span>
                  </div>
                  <div className="flex bg-gray-100 rounded-2xl p-1 shrink-0">
                    <button onClick={() => setInputs({...inputs, user1: {...inputs.user1, transport: 'public'}})} className={`px-3 md:px-4 rounded-xl ${inputs.user1.transport === 'public' ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400'}`}><Bus size={18} /></button>
                    <button onClick={() => setInputs({...inputs, user1: {...inputs.user1, transport: 'car'}})} className={`px-3 md:px-4 rounded-xl ${inputs.user1.transport === 'car' ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400'}`}><Car size={18} /></button>
                  </div>
                </div>
              </div>
              {mode === 'couple' && (
                <div className="space-y-3 pt-3 border-t border-gray-50 animate-in fade-in slide-in-from-top-2 duration-300">
                  <StationSearch stations={stationList} value={inputs.user2.workplace} onChange={(val) => setInputs({...inputs, user2: {...inputs.user2, workplace: val}})} placeholder="배우자 직장 위치" icon={MapPin} colorClass="text-pink-500" />
                  <div className="flex gap-3">
                    <div className="flex-1 relative group">
                      <Coins className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-300" />
                      <input type="number" value={inputs.user2.salary} onChange={(e) => setInputs({...inputs, user2: {...inputs.user2, salary: parseInt(e.target.value)||0}})} className="w-full pl-12 pr-10 py-3.5 bg-gray-50 border border-transparent rounded-2xl text-[14px] md:text-[15px] font-black outline-none focus:bg-white focus:border-pink-500" />
                      <span className="absolute right-4 top-1/2 -translate-y-1/2 text-[10px] font-black text-gray-400">만원</span>
                    </div>
                    <div className="flex bg-gray-100 rounded-2xl p-1 shrink-0">
                      <button onClick={() => setInputs({...inputs, user2: {...inputs.user2, transport: 'public'}})} className={`px-4 rounded-xl ${inputs.user2.transport === 'public' ? 'bg-white shadow-sm text-pink-500' : 'text-gray-400'}`}><Bus size={18} /></button>
                      <button onClick={() => setInputs({...inputs, user2: {...inputs.user2, transport: 'car'}})} className={`px-4 rounded-xl ${inputs.user2.transport === 'car' ? 'bg-white shadow-sm text-pink-500' : 'text-gray-400'}`}><Car size={18} /></button>
                    </div>
                  </div>
                </div>
              )}
              <button onClick={handleSearch} disabled={loading || !isReady} className="w-full bg-[#111] hover:bg-black text-white font-black py-4.5 rounded-2xl shadow-2xl active:scale-[0.98] flex items-center justify-center space-x-2">
                {loading ? <Loader2 className="animate-spin" size={20} /> : <Search size={20} strokeWidth={3} />}
                <span className="text-base uppercase tracking-tighter">워라밸 구출하기</span>
              </button>
            </div>
          ) : (
            <div className="flex items-center justify-between bg-gray-900 p-4 rounded-2xl md:rounded-[1.75rem] animate-in slide-in-from-bottom-2 duration-500 shadow-xl">
              <div className="flex items-center space-x-3 md:space-x-4">
                <div className="flex -space-x-2">
                  <div className="w-8 h-8 rounded-full bg-blue-600 border-2 border-gray-900 flex items-center justify-center text-white text-[9px] font-black shadow-lg">나</div>
                  {mode === 'couple' && <div className="w-8 h-8 rounded-full bg-pink-500 border-2 border-gray-900 flex items-center justify-center text-white text-[9px] font-black shadow-lg">배</div>}
                </div>
                <div>
                  <div className="text-[13px] md:text-[14px] font-black text-white tracking-tight leading-none mb-1">{inputs.user1.workplace?.name}{mode === 'couple' ? ` & ${inputs.user2.workplace?.name}` : ''}</div>
                  <div className="text-[9px] font-black text-gray-400 uppercase tracking-widest">분석 완료 • 07:00 기준</div>
                </div>
              </div>
              <button onClick={() => setIsMinimized(false)} className="p-2 text-gray-400 hover:text-white"><Edit3 size={16} /></button>
            </div>
          )}
        </div>

        {/* Scroll Area */}
        <div className="flex-1 overflow-y-auto px-4 md:px-6 py-6 md:py-8 custom-scrollbar space-y-6">
          {results ? (
            <>
              <div className="flex items-center justify-between px-2">
                <h5 className="text-[11px] font-black text-gray-400 uppercase tracking-widest">최적 생존 입지 <span className="ml-2 text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">{results.length}</span></h5>
                <div className="flex items-center space-x-1 text-[10px] font-bold text-blue-500 animate-pulse"><Zap size={12} className="fill-blue-500" /> <span>Al-Driven</span></div>
              </div>
              <div className="space-y-4 pb-20">
                {results.map((spot, i) => {
                  const isExpanded = expandedSpotIndex === i;
                  return (
                    <div key={i} className="space-y-4">
                      <div className={`transition-all rounded-[2rem] md:rounded-[2.5rem] border overflow-hidden ${isExpanded ? 'bg-white border-blue-200 shadow-2xl scale-[1.01] md:scale-[1.02] ring-1 ring-blue-100' : 'bg-white border-gray-100 hover:border-gray-200 hover:shadow-lg'}`}>
                        <button onClick={() => handleSpotClick(spot, i)} className="w-full p-5 md:p-7 text-left flex justify-between items-center">
                          <div className="flex items-center space-x-3 md:space-x-4 shrink-0">
                            <div className={`w-10 h-10 md:w-12 md:h-12 rounded-2xl flex items-center justify-center text-base font-black ${i === 0 ? 'bg-blue-600 text-white shadow-lg' : 'bg-gray-100 text-gray-400'}`}>
                              {i === 0 ? <Trophy size={18} /> : i + 1}
                            </div>
                            <div>
                              <div className="text-[10px] font-black text-blue-500 uppercase tracking-tighter mb-0.5">{spot.name} 인근</div>
                              <h6 className="text-[16px] md:text-[20px] font-black tracking-tighter text-gray-900 leading-none truncate max-w-[120px] md:max-w-none">{spot.complexes[0]?.name}</h6>
                            </div>
                          </div>
                          <div className="text-right shrink-0 ml-2">
                            <div className="text-[9px] font-black text-gray-300 uppercase mb-0.5 whitespace-nowrap">총 손실 비용</div>
                            <div className="text-[18px] md:text-[22px] font-black text-gray-900 tracking-tighter leading-none whitespace-nowrap">월 {spot.total_cost}만</div>
                          </div>
                        </button>
                        {isExpanded && (
                          <div className="px-5 md:px-7 pb-8 animate-in slide-in-from-top-4 duration-500">
                            <div className="h-px bg-gray-100 mb-6" />
                            <div className="space-y-3 mb-8">
                              {spot.complexes.map((apt, idx) => (
                                <div key={idx} onClick={() => setExpandedComplexIdx(idx)} className={`p-4 md:p-5 rounded-2xl border transition-all cursor-pointer ${expandedComplexIdx === idx ? 'bg-blue-50 border-blue-200' : 'bg-gray-50 border-transparent hover:bg-gray-100'}`}>
                                  <div className="flex justify-between items-center mb-1 gap-2">
                                    <div className="flex items-center space-x-2 overflow-hidden">
                                      <span className="text-[13px] md:text-[15px] font-black text-gray-800 tracking-tight truncate">{apt.name}</span>
                                      <ExternalLink size={12} className="text-gray-300 shrink-0" />
                                    </div>
                                    <span className="text-[12px] md:text-[14px] font-black text-blue-600 shrink-0 whitespace-nowrap">{Math.round(apt.display_price_value/10000)}억{(apt.display_price_value%10000) > 0 ? ` ${apt.display_price_value%10000}만` : ''}</span>
                                  </div>
                                  {expandedComplexIdx === idx && (
                                    <div className="mt-4 grid grid-cols-2 gap-2 md:gap-3 animate-in fade-in duration-300">
                                      <div className="bg-white p-3 md:p-4 rounded-xl border border-blue-100 shadow-sm text-center">
                                        <div className="text-[9px] font-black text-gray-400 uppercase mb-1">월 고정 지출</div>
                                        <div className="text-[14px] md:text-base font-black text-gray-900">{apt.fixed_monthly_exp}만</div>
                                      </div>
                                      <div className="bg-white p-3 md:p-4 rounded-xl border border-blue-100 shadow-sm text-center">
                                        <div className="text-[9px] font-black text-gray-400 uppercase mb-1 text-orange-500">에너지 비용</div>
                                        <div className="text-[14px] md:text-base font-black text-gray-900">{apt.hidden_life_cost}만</div>
                                      </div>
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                            <button onClick={() => window.open(`https://m.land.naver.com/search/result?query=${spot.complexes[expandedComplexIdx].dong} ${spot.complexes[expandedComplexIdx].name}`, '_blank')} className="w-full bg-[#111] hover:bg-black text-white font-black py-4 rounded-[1.25rem] text-sm md:text-base transition-all flex items-center justify-center space-x-2 shadow-2xl active:scale-95">
                              <ExternalLink size={18} strokeWidth={3} /> <span>네이버 부동산 매물 보기</span>
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="mt-8 p-8 md:p-10 bg-gray-50/30 rounded-[3rem] border border-gray-100 text-center">
                <div className="space-y-6 opacity-40 text-[9px] font-medium text-gray-400">
                  <div className="flex justify-center space-x-4 uppercase tracking-widest">
                    <button className="hover:text-blue-600 transition-colors underline underline-offset-2">이용약관</button>
                    <button className="hover:text-blue-600 transition-colors underline underline-offset-2">개인정보처리방침</button>
                  </div>
                  <p>수도권 샐러리맨의 워라밸을 응원합니다. <br/>© 2026 SEARCH HOUSE. All rights reserved.</p>
                </div>
              </div>
            </>
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-center p-8 md:p-12 mt-4">
              <div className="w-20 h-20 bg-blue-50 rounded-[3rem] flex items-center justify-center mb-6 animate-bounce duration-[2000ms]">
                <Coffee size={32} className="text-blue-500" />
              </div>
              <h4 className="text-lg font-black text-gray-900 mb-3 tracking-tighter">워라밸 구출 작전</h4>
              <p className="text-xs md:text-[15px] font-bold leading-relaxed text-gray-400 tracking-tight px-4">당신의 인생 에너지를 구출하는 <br/>샐러리맨 전용 입지 최적화 엔진.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
