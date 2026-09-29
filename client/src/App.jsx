import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { Search, MapPin, Coins, Car, Bus, Loader2, ChevronDown, ExternalLink, Trophy, Zap, ShieldCheck, Settings2, X, HelpCircle, Home, AlertTriangle, ChevronLeft, ChevronRight, Coffee, ArrowUpRight, ArrowDownLeft } from 'lucide-react';
import { useMap, addMarker, addOverlay, clearMarkers, drawPolyline, setBounds, getZoom, setZoom, geocodeAddress } from './lib/map';
import { findNearestStations, isWithinCorrectionRange } from './lib/geo';
import { RESIDENT_TYPES, getResidentTypeLabel, getTimeStatus, getBudgetStatus, getIncomeRatio, getNaverLandUrl } from './lib/housing';
import { getRequestErrorMessage, getSearchErrorMessage } from './lib/errors';
import { escapeHtml } from './lib/html';
import { buildUniqueKeys } from './lib/keys';
import { useIsMobile } from './lib/useIsMobile';
import StationSearch from './components/StationSearch';
import HelpModal from './components/HelpModal';

const REQUEST_TIMEOUT_MS = 15000;
// 진행 문구를 읽을 틈도 없이 넘어가지 않게 하는 순환 간격
const LOADING_MESSAGE_INTERVAL_MS = 1200;

const fetchWithTimeout = async (url, options = {}, timeoutMs = REQUEST_TIMEOUT_MS) => {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    window.clearTimeout(timeoutId);
  }
};

function App() {
  const isMobile = useIsMobile();
  const [mapCenter] = useState({ lat: 37.5665, lng: 126.9780 });
  const [zoomLevel] = useState(15);
  const [mode, setMode] = useState('single');
  const [residentType, setResidentType] = useState('jeonse'); // jeonse/wolse/buy
  const [housingRatio, setHousingRatio] = useState(0.25);
  const [availableCash, setAvailableCash] = useState(0); // 보유 자금 (만원), 0=미입력
  const [roomType, setRoomType] = useState('all');
  const [buildingAge, setBuildingAge] = useState(0);
  const [preference, setPreference] = useState('balance'); // 'money', 'balance', 'time'
  const [inputsCollapsed, setInputsCollapsed] = useState(false);
  const [inputs, setInputs] = useState({
    user1: { workplace: null, salary: 4000, transport: 'public' },
    user2: { workplace: null, salary: 4000, transport: 'public' }
  });
  const [loading, setLoading] = useState(false);
  const [loadingMessage, setLoadingMessage] = useState("");
  const [results, setResults] = useState(null);
  const [isSidebarOpen, setIsSidebarOpen] = useState(!isMobile);
  const [mobileSheetState, setMobileSheetState] = useState('peek'); // 'hidden', 'peek', 'full'
  const [expandedSpotIndex, setExpandedSpotIndex] = useState(null);
  const [expandedComplexIdx, setExpandedComplexIdx] = useState(0);
  const [workplaceLocs, setWorkplaceLocs] = useState({ user1: null, user2: null });
  const [stationList, setStationList] = useState([]);
  const [stationLoading, setStationLoading] = useState(true);
  const [stationError, setStationError] = useState(null);
  const [searchError, setSearchError] = useState(null);
  const [realtimeRouting, setRealtimeRouting] = useState(null); // 서버가 실제 경로 API를 쓰는지 여부
  const [searchedResidentType, setSearchedResidentType] = useState(null); // 현재 결과가 어떤 주거 형태로 나온 것인지
  const [showHelp, setShowHelp] = useState(false);

  const mapContainerRef = useRef(null);
  const markersRef = useRef([]);
  const pathsRef = useRef([]);
  const loadingTimerRef = useRef(null);
  // 분석 응답을 기다리는 사이 창 크기나 화면 방향이 바뀔 수 있다. await 나 타이머 뒤에 실행되는 코드는
  // 클로저에 잡힌 값이 아니라 실행 시점의 값을 읽어야 하므로 훅 값을 ref 로도 들고 있는다.
  const isMobileRef = useRef(isMobile);
  useEffect(() => { isMobileRef.current = isMobile; }, [isMobile]);
  const { map, isReady, error: mapError } = useMap(mapContainerRef, { center: mapCenter, zoom: zoomLevel });

  const API_BASE_URL = import.meta.env.VITE_API_URL || 'https://search-house.onrender.com';

  const fetchStations = useCallback(async () => {
    setStationLoading(true); setStationError(null);
    for (let i = 0; i < 3; i++) {
      try {
        const res = await fetchWithTimeout(`${API_BASE_URL}/api/stations`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (Array.isArray(data) && data.length > 0 && data.every(station => station && typeof station.name === 'string')) { setStationList(data); setStationLoading(false); return; }
        throw new Error('데이터 없음');
      } catch (e) {
        if (i === 2) { setStationError(getRequestErrorMessage(e, '지하철역 목록을 불러오지 못했습니다.')); setStationLoading(false); return; }
        await new Promise(r => setTimeout(r, 1500 * (i + 1)));
      }
    }
  }, [API_BASE_URL]);

  useEffect(() => { fetchStations(); }, [fetchStations]);

  const stopLoadingMessages = useCallback(() => {
    if (loadingTimerRef.current === null) return;
    clearInterval(loadingTimerRef.current);
    loadingTimerRef.current = null;
  }, []);

  const startLoadingMessages = useCallback((messages) => {
    stopLoadingMessages();
    let index = 0;
    setLoadingMessage(messages[0]);
    loadingTimerRef.current = setInterval(() => {
      index = (index + 1) % messages.length;
      setLoadingMessage(messages[index]);
    }, LOADING_MESSAGE_INTERVAL_MS);
  }, [stopLoadingMessages]);

  // 요청 도중 화면이 사라져도 타이머가 남아 상태를 갱신하지 않도록 한다.
  useEffect(() => stopLoadingMessages, [stopLoadingMessages]);

  const drawCommutePaths = useCallback((spot, workplaceLocs, mode) => {
    if (!map) return;
    pathsRef.current.forEach(p => p.setMap(null));
    pathsRef.current = [];
    const pts = [{ lat: spot.lat, lng: spot.lng }];
    if (workplaceLocs.user1) {
      pts.push(workplaceLocs.user1);
      const p1 = drawPolyline(map, [{ lat: spot.lat, lng: spot.lng }, { lat: workplaceLocs.user1.lat, lng: workplaceLocs.user1.lng }], { color: '#3B82F6', style: 'dashed', weight: 5 });
      if (p1) pathsRef.current.push(p1);
    }
    if (mode === 'couple' && workplaceLocs.user2) {
      pts.push(workplaceLocs.user2);
      const p2 = drawPolyline(map, [{ lat: spot.lat, lng: spot.lng }, { lat: workplaceLocs.user2.lat, lng: workplaceLocs.user2.lng }], { color: '#EC4899', style: 'dashed', weight: 5 });
      if (p2) pathsRef.current.push(p2);
    }
    
    // 사이드바 영역을 고려한 패딩 적용 (데스크탑 460px)
    // 검색 직후에는 타이머 뒤에 호출되므로 실행 시점의 화면 크기를 읽는다.
    const isDesktop = !isMobileRef.current;
    const padding = {
      left: isDesktop ? 460 : 40,
      right: 40,
      top: 100,
      bottom: 100
    };
    setBounds(map, pts, padding);
  }, [map]);

  const handleSpotClick = useCallback((spot, index) => {
    const isAlreadyExpanded = expandedSpotIndex === index;
    setExpandedSpotIndex(isAlreadyExpanded ? null : index);
    setExpandedComplexIdx(0);
    if (!isAlreadyExpanded) {
      drawCommutePaths(spot, workplaceLocs, mode);
      if (isMobile) setMobileSheetState('hidden');
    } else {
      pathsRef.current.forEach(p => p.setMap(null));
      pathsRef.current = [];
      const allPts = [...results, workplaceLocs.user1];
      if (workplaceLocs.user2) allPts.push(workplaceLocs.user2);

      const isDesktop = !isMobile;
      const padding = {
        left: isDesktop ? 460 : 40,
        right: 40,
        top: 100,
        bottom: 100
      };
      setBounds(map, allPts, padding);
      setTimeout(() => { const currentZoom = getZoom(map); setZoom(map, currentZoom - 2); }, 300);
    }
  }, [expandedSpotIndex, workplaceLocs, mode, drawCommutePaths, results, map, isMobile]);

  useEffect(() => {
    if (!map || !isReady) return;
    clearMarkers(markersRef.current);
    markersRef.current = [];
    if (results) {
      results.forEach((spot, index) => {
        const isSelected = expandedSpotIndex === index;
        const zIndex = isSelected ? 1000 : (100 - index);
        const content = `
          <div style="cursor:pointer; display: flex; flex-direction: column; align-items: center; z-index: ${zIndex};" onclick="window.dispatchSpotClick(${index})">
            <div style="background:${isSelected ? '#3B82F6' : 'rgba(31,41,55,0.9)'}; backdrop-filter: blur(8px); color:white; padding: 8px 14px; border-radius: 40px; font-weight: 900; font-size: 13px; white-space: nowrap; border: 2.5px solid ${isSelected ? '#FACC15' : 'white'}; box-shadow: 0 12px 30px rgba(0,0,0,0.25); transition: all 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275); ${isSelected ? 'transform: scale(1.1);' : ''}">
              <div style="display:flex; align-items:center; gap:6px;">
                <span style="font-size: 14px;">${index === 0 ? '🏆' : (index+1)}</span>
                <span style="letter-spacing: -0.02em;">${escapeHtml(spot.name)}</span>
              </div>
            </div>
            <div style="width: 3px; height: 10px; background: ${isSelected ? '#FACC15' : 'white'};"></div>
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

  useEffect(() => { window.dispatchSpotClick = (index) => { if (results && results[index]) handleSpotClick(results[index], index); }; }, [results, handleSpotClick]);

  const usesCarRouting = inputs.user1.transport === 'car' || (mode === 'couple' && inputs.user2.transport === 'car');

  const spotKeys = useMemo(() => buildUniqueKeys(results || [], (spot) => `${spot.name}|${spot.dong || ''}`), [results]);
  const complexKeys = useMemo(() => (results || []).map((spot) => buildUniqueKeys(spot.complexes, (apt) => `${apt.name}|${apt.dong || ''}`)), [results]);

  const handleSearch = async () => {
    setSearchError(null);
    if (!inputs.user1.workplace) { setSearchError("나의 직장 위치를 선택해 주세요."); return; }
    if (mode === 'couple' && !inputs.user2.workplace) { setSearchError("커플 모드에서는 배우자의 직장 위치도 선택해 주세요."); return; }
    setLoading(true);
    try {
      const loc1 = inputs.user1.workplace;
      const loc2 = mode === 'couple' ? inputs.user2.workplace : null;
      setWorkplaceLocs({ user1: loc1, user2: loc2 });
      const areaMap = { all: [33, 200], '10': [33, 66], '20': [66, 99], '30': [99, 132], '40': [132, 200] };
      const [minArea, maxArea] = areaMap[roomType] || areaMap.all;
      const payload = {
        mode,
        resident_type: residentType,
        housing_ratio: housingRatio,
        available_cash: availableCash,
        min_area: minArea,
        max_area: maxArea, 
        max_building_age: buildingAge, 
        preference: preference,
        user1: { workplace: loc1, salary: inputs.user1.salary, transport: inputs.user1.transport }, 
        user2: loc2 ? { workplace: loc2, salary: inputs.user2.salary, transport: inputs.user2.transport } : null 
      };

      // 진행 문구는 안내일 뿐이라 요청을 늦추지 않는다. 요청은 바로 보내고 문구만 응답을 기다리는 동안 순환시킨다.
      startLoadingMessages([
        "수도권 3만 개 단지 실거래 데이터 필터링 중...",
        `${inputs.user1.salary}만원 연봉 기반 최적 예산 구간 산출 완료`,
        "08:00 출근 피크 실시간 교통망 시뮬레이션 중...",
        "기회비용 및 피로도 가중치 랭킹 산출 중...",
      ]);
      const response = await fetchWithTimeout(`${API_BASE_URL}/api/optimize`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }, 30000);
      if (!response.ok) {
        const error = new Error(`분석 요청 실패 (HTTP ${response.status})`);
        error.status = response.status;
        throw error;
      }
      const data = await response.json();
      stopLoadingMessages();
      if (!data || !Array.isArray(data.results)) throw new Error('INVALID_RESPONSE');
      setRealtimeRouting(typeof data.meta?.realtime_routing === 'boolean' ? data.meta.realtime_routing : null);
      setSearchedResidentType(data.meta?.resident_type || residentType);
      const validResults = data.results.filter(spot => spot && Number.isFinite(Number(spot.lat)) && Number.isFinite(Number(spot.lng)) && Array.isArray(spot.complexes));
      if (validResults.length !== data.results.length) throw new Error('INVALID_RESPONSE');

      // 클라이언트 사이드 좌표 보정: 카카오 지도 JS SDK로 단지 정밀 위치 조회
      setLoadingMessage("단지 위치 정밀 보정 중...");
      const geocodedResults = await Promise.all(
        validResults.map(async (spot) => {
          // 서버가 이미 단지 좌표로 통근 시간을 계산했다면, 여기서 좌표를 바꾸는 순간 그 계산과 어긋난다.
          if (spot.coord_precise === true) return spot;
          const dong = spot.complexes?.[0]?.dong || '';
          const query = `${dong} ${spot.name}`.trim();
          try {
            const coords = await geocodeAddress(query);
            if (coords && isWithinCorrectionRange(spot, coords)) {
              const nearby = findNearestStations(coords.lat, coords.lng, stationList);
              return {
                ...spot,
                lat: coords.lat,
                lng: coords.lng,
                nearest_stations: nearby.length > 0 ? nearby : spot.nearest_stations,
              };
            }
          } catch { /* 실패시 서버 좌표 유지 */ }
          return spot;
        })
      );

      setResults(geocodedResults);
      if (geocodedResults.length > 0) {
        setInputsCollapsed(true);
        if (isMobileRef.current) setMobileSheetState('hidden');
      } else {
        if (isMobileRef.current) setMobileSheetState('full');
      }

      if (geocodedResults.length > 0) {
        const allPts = [...geocodedResults, loc1];
        if (loc2) allPts.push(loc2);
        const padding = { left: !isMobileRef.current && isSidebarOpen ? 460 : 60, right: 60, top: 60, bottom: 60 };
        setBounds(map, allPts, padding);
        setTimeout(() => { const currentZoom = getZoom(map); setZoom(map, currentZoom - 2); }, 300);
        setExpandedSpotIndex(0); setExpandedComplexIdx(0);
        setTimeout(() => { drawCommutePaths(geocodedResults[0], { user1: loc1, user2: loc2 }, mode); }, 600);
      }
    } catch (err) {
      console.error(err);
      setSearchError(getSearchErrorMessage(err));
    } finally { stopLoadingMessages(); setLoading(false); setLoadingMessage(""); }
  };

  return (
    <div className="relative w-full h-[100dvh] overflow-hidden antialiased bg-gray-50 text-gray-900 font-sans">
      <div ref={mapContainerRef} className="absolute inset-0 w-full h-full z-0 bg-gray-100 flex items-center justify-center">
        {!isReady && !mapError && (
          <div className="flex flex-col items-center space-y-4" role="status" aria-live="polite">
            <Loader2 className="animate-spin text-blue-500" size={40} />
            <p className="text-sm font-bold text-gray-400 text-center px-6">지능형 지도를 로드하고 있습니다...</p>
          </div>
        )}
        {mapError && (
          <div className="max-w-sm mx-6 rounded-2xl border border-red-100 bg-white/95 p-5 text-center shadow-lg" role="alert">
            <AlertTriangle className="mx-auto mb-3 text-red-500" size={30} />
            <p className="text-sm font-black text-gray-900">지도를 불러오지 못했습니다</p>
            <p className="mt-1 text-xs font-bold text-gray-500">네트워크 또는 지도 API 설정을 확인한 뒤 페이지를 새로고침해 주세요.</p>
            <button onClick={() => window.location.reload()} className="mt-4 rounded-xl bg-gray-900 px-4 py-2 text-xs font-black text-white">페이지 새로고침</button>
          </div>
        )}
      </div>

      {loading && (
        <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-white/70 backdrop-blur-md animate-in fade-in duration-300" role="status" aria-live="polite" aria-busy="true">
          <div className="flex flex-col items-center space-y-6 max-w-[280px] text-center">
            <div className="relative">
              <div className="absolute inset-0 bg-blue-400/20 rounded-full animate-ping" />
              <div className="relative w-20 h-20 bg-gray-900 rounded-[2.5rem] flex items-center justify-center shadow-2xl">
                <Loader2 className="animate-spin text-blue-400" size={32} strokeWidth={3} />
              </div>
            </div>
            <div className="space-y-2">
              <h4 className="text-[18px] font-black text-gray-900 tracking-tighter">데이터 정밀 분석 중</h4>
              <p className="text-[12px] font-bold text-blue-600 animate-pulse">{loadingMessage}</p>
            </div>
            <div className="w-full h-1 bg-gray-100 rounded-full overflow-hidden">
              <div className="h-full bg-blue-500 animate-loading-bar transition-all duration-1000" />
            </div>
          </div>
        </div>
      )}

      <div className={`absolute z-[1000] transition-all duration-500 cubic-bezier(0.4, 0, 0.2, 1) flex flex-col 
        md:inset-y-0 md:left-0 md:w-[420px] md:bg-white md:border-r md:border-gray-100 md:shadow-[10px_0_30px_rgba(0,0,0,0.02)]
        ${isMobile
          ? `inset-x-0 bottom-0 bg-white rounded-t-[2.5rem] shadow-[0_-20px_60px_rgba(0,0,0,0.12)] overflow-hidden 
             ${mobileSheetState === 'hidden' ? 'translate-y-full' : (mobileSheetState === 'peek' ? 'translate-y-[calc(100%-80px)]' : 'translate-y-0 h-[85vh]')}`
          : (isSidebarOpen ? 'translate-x-0' : '-translate-x-full')
        }
      `}>
        <button onClick={() => setIsSidebarOpen(!isSidebarOpen)} aria-label={isSidebarOpen ? '검색 패널 닫기' : '검색 패널 열기'} className={`hidden md:flex absolute top-1/2 -right-4 -translate-y-1/2 w-8 h-12 bg-white border border-gray-100 shadow-sm rounded-r-xl items-center justify-center text-gray-400 hover:text-blue-600 transition-all z-[1100]`}>
          {isSidebarOpen ? <ChevronLeft size={20} strokeWidth={3} /> : <ChevronRight size={20} strokeWidth={3} className="ml-4" />}
        </button>

        <div className="md:hidden w-full h-8 flex items-center justify-center cursor-pointer shrink-0 border-b border-gray-50" onClick={() => setMobileSheetState(prev => prev === 'full' ? 'peek' : 'full')}>
          <div className="w-12 h-1.5 bg-gray-200 rounded-full" />
        </div>

        <div className="flex flex-col h-full overflow-hidden relative">
          <div className="p-6 md:p-8 shrink-0 relative bg-white z-[100] border-b border-gray-50">
            <div className="flex items-center justify-between mb-4 md:mb-6">
              <div className="flex items-center space-x-3 cursor-pointer" onClick={() => window.location.reload()}>
                <img src="logo.svg" alt="Logo" className="w-10 h-10 md:w-12 md:h-12" />
                <span className="text-lg md:text-2xl font-black uppercase tracking-tight text-slate-900">Search House</span>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => setShowHelp(true)} aria-label="사용 가이드 열기" className="p-2 bg-gray-100 rounded-full transition-colors hover:bg-blue-50 active:bg-blue-100" title="사용 가이드"><HelpCircle size={16} className="text-gray-400 hover:text-blue-500" /></button>
                <button onClick={() => { if(isMobile) setMobileSheetState('hidden'); else setIsSidebarOpen(false); }} aria-label="검색 패널 닫기" className="p-2 bg-gray-100 rounded-full md:hidden transition-colors active:bg-gray-200"><X size={20} /></button>
              </div>
            </div>

            {inputsCollapsed ? (
              <div className="space-y-3">
                <div className="flex flex-wrap gap-1.5 overflow-hidden max-h-[24px] md:max-h-none">
                  <span className="text-[10px] font-black bg-blue-50 text-blue-600 px-2 py-1 rounded-full">{inputs.user1.workplace?.name || '미선택'}</span>
                  <span className="text-[10px] font-black bg-gray-100 text-gray-500 px-2 py-1 rounded-full">{inputs.user1.salary}만</span>
                  <span className="text-[10px] font-black bg-gray-100 text-gray-500 px-2 py-1 rounded-full">주거비 {Math.round(housingRatio * 100)}%</span>
                </div>
                <button onClick={() => { setInputsCollapsed(false); if(isMobile) setMobileSheetState('full'); }} className="w-full py-2 bg-gray-100 hover:bg-gray-200 rounded-xl text-[11px] font-black text-gray-500 flex items-center justify-center gap-1.5 transition-colors"><Settings2 size={13} /> 조건 수정</button>
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
                  <StationSearch stations={stationList} value={inputs.user1.workplace} onChange={(val) => setInputs({...inputs, user1: {...inputs.user1, workplace: val}})} placeholder="나의 직장 위치 검색" icon={MapPin} iconFocusClass="group-focus-within:text-blue-500" stationLoading={stationLoading} stationError={stationError} onRetry={fetchStations} />
                </div>
                <div className="flex gap-2">
                  <div className="flex-1 space-y-1">
                    <div className="text-[10px] font-black text-gray-400 uppercase tracking-widest pl-1">연봉 (만원)</div>
                    <div className="relative group"><Coins className="absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-300" /><input type="number" value={inputs.user1.salary} onChange={(e) => setInputs({...inputs, user1: {...inputs.user1, salary: parseInt(e.target.value)||0}})} className="w-full pl-10 pr-4 py-2.5 bg-gray-50 border-none rounded-xl text-[13px] font-black outline-none focus:ring-2 focus:ring-blue-500/20" /></div>
                  </div>
                  <div className="shrink-0 space-y-1">
                    <div className="text-[10px] font-black text-gray-400 uppercase tracking-widest pl-1">이동 수단</div>
                    <div className="flex bg-gray-100 rounded-xl p-0.5 h-[42px]">
                      <button onClick={() => setInputs({...inputs, user1: {...inputs.user1, transport: 'public'}})} aria-label="내 이동 수단 대중교통" className={`px-3 rounded-lg ${inputs.user1.transport === 'public' ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400'}`}><Bus size={16} /></button>
                      <button onClick={() => setInputs({...inputs, user1: {...inputs.user1, transport: 'car'}})} aria-label="내 이동 수단 자동차" className={`px-3 rounded-lg ${inputs.user1.transport === 'car' ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400'}`}><Car size={16} /></button>
                    </div>
                  </div>
                </div>
              </div>
              {mode === 'couple' && (
                <div className="space-y-3 pt-3 border-t border-gray-100 animate-in fade-in">
                  <div className="space-y-1">
                    <div className="text-[10px] font-black text-pink-400 uppercase tracking-widest pl-1">배우자 직장</div>
                    <StationSearch stations={stationList} value={inputs.user2.workplace} onChange={(val) => setInputs({...inputs, user2: {...inputs.user2, workplace: val}})} placeholder="배우자 직장 위치" icon={MapPin} iconFocusClass="group-focus-within:text-pink-500" stationLoading={stationLoading} stationError={stationError} onRetry={fetchStations} />
                  </div>
                  <div className="flex gap-2">
                    <div className="flex-1 space-y-1">
                      <div className="text-[10px] font-black text-pink-400 uppercase tracking-widest pl-1">연봉 (만원)</div>
                      <div className="relative group"><Coins className="absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-300" /><input type="number" value={inputs.user2.salary} onChange={(e) => setInputs({...inputs, user2: {...inputs.user2, salary: parseInt(e.target.value)||0}})} className="w-full pl-10 pr-4 py-2.5 bg-gray-50 border-none rounded-xl text-[13px] font-black outline-none focus:ring-2 focus:ring-pink-500/20" /></div>
                    </div>
                    <div className="shrink-0 space-y-1">
                      <div className="text-[10px] font-black text-pink-400 uppercase tracking-widest pl-1">이동 수단</div>
                      <div className="flex bg-gray-100 rounded-xl p-0.5 h-[42px]">
                        <button onClick={() => setInputs({...inputs, user2: {...inputs.user2, transport: 'public'}})} aria-label="배우자 이동 수단 대중교통" className={`px-3 rounded-lg ${inputs.user2.transport === 'public' ? 'bg-white shadow-sm text-pink-500' : 'text-gray-400'}`}><Bus size={16} /></button>
                        <button onClick={() => setInputs({...inputs, user2: {...inputs.user2, transport: 'car'}})} aria-label="배우자 이동 수단 자동차" className={`px-3 rounded-lg ${inputs.user2.transport === 'car' ? 'bg-white shadow-sm text-pink-500' : 'text-gray-400'}`}><Car size={16} /></button>
                      </div>
                    </div>
                  </div>
                </div>
              )}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between px-1"><div className="text-[10px] font-black text-gray-400 uppercase tracking-widest">소득 대비 주거비 한도</div><div className={`text-[11px] font-black ${getBudgetStatus(housingRatio).color}`}>{getBudgetStatus(housingRatio).icon} 월 {Math.round(((mode === 'couple' ? inputs.user1.salary + inputs.user2.salary : inputs.user1.salary) * housingRatio / 12))}만원 이내 ({getBudgetStatus(housingRatio).label})</div></div>
                <div className="flex bg-gray-100 rounded-xl p-1 gap-0.5">
                  {[0.1, 0.2, 0.25, 0.3, 0.4].map((ratio) => { const status = getBudgetStatus(ratio); return (<button key={ratio} onClick={() => setHousingRatio(ratio)} className={`flex-1 py-1.5 rounded-lg text-[11px] font-black transition-all ${housingRatio === ratio ? `bg-white shadow-sm ${status.color}` : 'text-gray-400 hover:text-gray-600'}`}>{Math.round(ratio * 100)}%</button>); })}
                </div>
              </div>

              <div className="space-y-1.5">
                <div className="text-[10px] font-black text-gray-400 uppercase tracking-widest pl-1">주거 형태</div>
                <div className="flex bg-gray-100 rounded-xl p-1 gap-0.5">
                  {RESIDENT_TYPES.map((option) => (
                    <button
                      key={option.id}
                      onClick={() => setResidentType(option.id)}
                      className={`flex-1 py-1.5 rounded-lg text-[11px] font-black transition-all ${residentType === option.id ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400 hover:text-gray-600'}`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-1.5">
                <div className="flex items-center justify-between px-1">
                  <div className="text-[10px] font-black text-gray-400 uppercase tracking-widest">{residentType === 'buy' ? '보유 자금 (자기자본)' : '보유 자금 (보증금으로 쓸 수 있는 현금)'}</div>
                  {availableCash > 0 && <div className="text-[10px] font-black text-blue-600">{availableCash.toLocaleString()}만원</div>}
                </div>
                <div className="relative group">
                  <Home className="absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-300" />
                  <input
                    type="number"
                    value={availableCash || ''}
                    onChange={(e) => setAvailableCash(parseInt(e.target.value) || 0)}
                    placeholder="예: 5000  (미입력 시 기회비용 모델)"
                    className="w-full pl-10 pr-4 py-2.5 bg-gray-50 border-none rounded-xl text-[13px] font-black outline-none focus:ring-2 focus:ring-blue-500/20 placeholder:text-gray-300 placeholder:font-medium"
                  />
                </div>
                {availableCash > 0 && (
                  <div className="text-[10px] font-medium text-blue-500 pl-1 leading-snug">
                    {residentType === 'buy'
                      ? '매매가 초과분은 주택담보대출 금리 4.2% 이자로 계산됩니다 (취득세·보유세 제외)'
                      : '보증금 초과분은 전세대출 금리 3.5% 이자로 계산됩니다'}
                  </div>
                )}
              </div>

              <div className="space-y-1.5">
                <div className="text-[10px] font-black text-gray-400 uppercase tracking-widest pl-1">라이프스타일 성향</div>
                <div className="flex bg-gray-100 rounded-xl p-1 gap-0.5">
                  {[
                    { id: 'money', label: '가성비', icon: <Coins size={12} /> },
                    { id: 'balance', label: '밸런스', icon: <Zap size={12} /> },
                    { id: 'time', label: '워라밸', icon: <Coffee size={12} /> }
                  ].map((p) => (
                    <button 
                      key={p.id} 
                      onClick={() => setPreference(p.id)} 
                      className={`flex-1 py-1.5 rounded-lg text-[11px] font-black transition-all flex items-center justify-center gap-1.5 
                        ${preference === p.id ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400 hover:text-gray-600'}`}
                    >
                      {p.icon} {p.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex gap-2">
                <div className="flex-1 space-y-1"><div className="text-[10px] font-black text-gray-400 uppercase tracking-widest pl-1">집 크기</div><div className="flex bg-gray-100 rounded-xl p-0.5 gap-0.5">{[['all', '전체'], ['10', '10평대'], ['20', '20평대'], ['30', '30평대'], ['40', '40평+']].map(([val, label]) => (<button key={val} onClick={() => setRoomType(val)} className={`flex-1 py-1.5 rounded-lg text-[10px] font-black transition-all ${roomType === val ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400'}`}>{label}</button>))}</div></div>
                <div className="flex-1 space-y-1"><div className="text-[10px] font-black text-gray-400 uppercase tracking-widest pl-1">준공</div><div className="flex bg-gray-100 rounded-xl p-0.5 gap-0.5">{[[0, '전체'], [5, '5년'], [10, '10년'], [20, '20년']].map(([val, label]) => (<button key={val} onClick={() => setBuildingAge(val)} className={`flex-1 py-1.5 rounded-lg text-[11px] font-black transition-all ${buildingAge === val ? 'bg-white shadow-sm text-blue-600' : 'text-gray-400'}`}>{label}</button>))}</div></div>
              </div>
              <div className="pt-1 px-1"><p className="text-[9px] font-black text-gray-300">{usesCarRouting && realtimeRouting !== false
                  ? '※ 카카오 길찾기 API 08:00 도착 / 18:00 출발 실시간 교통 반영'
                  : '※ 소요시간은 거리·출근 시간대 기반 추정치입니다 (08:00 도착 / 18:00 출발 기준)'}</p></div>
              {results && searchedResidentType && searchedResidentType !== residentType && (
                <div className="rounded-xl border border-amber-100 bg-amber-50 p-3" role="status">
                  <p className="text-[11px] font-bold text-amber-700">
                    현재 결과는 {getResidentTypeLabel(searchedResidentType)} 기준입니다. 다시 검색하면 {getResidentTypeLabel(residentType)} 시세로 분석합니다.
                  </p>
                </div>
              )}
              {searchError && (
                <div className="rounded-xl border border-red-100 bg-red-50 p-3" role="alert" aria-live="assertive">
                  <p className="text-[11px] font-bold text-red-700">{searchError}</p>
                  <button onClick={handleSearch} disabled={loading || !isReady} className="mt-2 text-[11px] font-black text-red-700 underline disabled:opacity-50">다시 시도</button>
                </div>
              )}
              <button onClick={handleSearch} disabled={loading || !isReady} className="w-full bg-gray-900 hover:bg-black text-white font-black py-4 rounded-xl shadow-xl active:scale-[0.98] flex items-center justify-center space-x-2 transition-all">{loading ? <Loader2 className="animate-spin" size={20} /> : <Search size={20} strokeWidth={3} />}<span>스마트 주거 탐색 시작</span></button>
            </div>
            )}
          </div>

          <div className="flex-1 overflow-y-auto px-6 py-4 custom-scrollbar space-y-3 border-t border-gray-50 bg-gray-50/30 pb-32">
            {results && results.length > 0 ? (
              <>
                <div className="flex items-center justify-between px-1 mb-1">
                  <h5 className="text-[10px] font-black text-gray-400 uppercase tracking-widest">최적 생존 입지 <span className="ml-1 text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded-full text-[9px]">{results.length}</span></h5>
                  <div className="flex items-center space-x-1 text-[9px] font-bold text-blue-500"><Zap size={11} className="fill-blue-500" /> <span>Al-Driven</span></div>
                </div>
                {results.map((spot, i) => {
                  const topApt = spot.complexes[0];
                  const monthlyIncome = ((mode === 'couple' ? inputs.user1.salary + inputs.user2.salary : inputs.user1.salary) * 10000 / 12) / 10000;
                  const actualRatio = getIncomeRatio(topApt?.fixed_monthly_exp, monthlyIncome);
                  const status = actualRatio === null ? null : getBudgetStatus(actualRatio);
                  return (
                  <div key={spotKeys[i]} className={`transition-all rounded-[1.5rem] border overflow-hidden ${expandedSpotIndex === i ? 'bg-white border-blue-200 shadow-xl ring-1 ring-blue-100' : 'bg-white border-gray-100 hover:border-gray-200'}`}>
                    <button onClick={() => handleSpotClick(spot, i)} className="w-full p-4 pb-3 text-left">
                      <div className="flex justify-between items-start mb-3">
                        <div className="flex items-center space-x-3">
                          <div className={`w-8 h-8 rounded-xl flex items-center justify-center text-xs font-black shrink-0 ${i === 0 ? 'bg-blue-600 text-white shadow-md' : 'bg-gray-100 text-gray-400'}`}>{i === 0 ? <Trophy size={16} /> : i + 1}</div>
                          <div><div className="text-[9px] font-black text-blue-500 uppercase tracking-tighter mb-0.5">{spot.nearest_stations?.length > 0 ? spot.nearest_stations.join(' / ') + ' 인근' : (spot.dong || spot.name) + ' 인근'}</div><h6 className="text-[14px] font-black tracking-tighter text-gray-900 leading-none truncate max-w-[180px]">{topApt?.name}</h6></div>
                        </div>
                        <div className="text-right shrink-0 ml-2">
                          {status && <div className={`text-[9px] font-black px-2 py-0.5 rounded-full ${status.bg} ${status.color} border ${status.border} mb-1 inline-block`}>소득의 {Math.round(actualRatio * 100)}% ({status.label})</div>}
                          <div className="text-[12px] font-black text-gray-700 tracking-tight">{topApt?.display_price_value}</div>
                          {topApt?.avg_area && <div className="text-[9px] font-bold text-gray-400 mt-0.5">{topApt.avg_area}㎡ (약 {Math.round(topApt.avg_area / 3.3058)}평)</div>}
                          {topApt?.loan_amount > 0 && (
                            <div className="text-[9px] font-bold text-blue-500 mt-0.5">대출 {topApt.loan_amount.toLocaleString()}만 · 이자 {topApt.loan_monthly}만/월</div>
                          )}
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <div className="flex-1 bg-gray-50 rounded-xl p-2.5 text-center border border-gray-100"><div className="text-[8px] font-black text-gray-400 uppercase mb-1">실제 지출</div><div className="text-[18px] font-black text-gray-900 tracking-tighter leading-none">{topApt?.fixed_monthly_exp}<span className="text-[11px] text-gray-400 ml-0.5">만</span></div><div className="text-[8px] font-bold text-gray-300 mt-0.5">주거비 + 교통비</div></div>
                        <div className="flex-1 bg-orange-50 rounded-xl p-2.5 text-center border border-orange-100"><div className="text-[8px] font-black text-orange-500 uppercase mb-1">보이지 않는 비용</div><div className="text-[18px] font-black text-orange-600 tracking-tighter leading-none">{topApt?.hidden_life_cost}<span className="text-[11px] text-orange-400 ml-0.5">만</span></div><div className="text-[8px] font-bold text-orange-300 mt-0.5">당신의 시간 가치</div></div>
                      </div>
                      <div className="flex flex-col gap-1.5 mt-2.5">
                        <div className="flex items-center gap-2">
                          <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border transition-all ${getTimeStatus(spot.commute_time_1).bg} ${getTimeStatus(spot.commute_time_1).border}`}>
                            {inputs.user1.transport === 'car' ? <Car size={10} className={getTimeStatus(spot.commute_time_1).color} /> : <Bus size={10} className={getTimeStatus(spot.commute_time_1).color} />}
                            <span className={`text-[11px] font-black ${getTimeStatus(spot.commute_time_1).color}`}>나: {spot.commute_time_1}분</span>
                            <div className="flex gap-1.5 ml-1.5 pl-1.5 border-l border-gray-200">
                              <div className="flex items-center gap-0.5">
                                <ArrowUpRight size={10} className="text-blue-500" />
                                <span className="text-[9px] font-bold text-gray-400">출근 {spot.commute_morning_1}</span>
                              </div>
                              <div className="flex items-center gap-0.5">
                                <ArrowDownLeft size={10} className="text-pink-500" />
                                <span className="text-[9px] font-bold text-gray-400">퇴근 {spot.commute_evening_1}</span>
                              </div>
                            </div>
                          </div>
                          {mode === 'couple' && spot.commute_time_2 > 0 && (
                            <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border transition-all ${getTimeStatus(spot.commute_time_2).bg} ${getTimeStatus(spot.commute_time_2).border}`}>
                              {inputs.user2.transport === 'car' ? <Car size={10} className={getTimeStatus(spot.commute_time_2).color} /> : <Bus size={10} className={getTimeStatus(spot.commute_time_2).color} />}
                              <span className={`text-[11px] font-black ${getTimeStatus(spot.commute_time_2).color}`}>짝: {spot.commute_time_2}분</span>
                              <div className="flex gap-1.5 ml-1.5 pl-1.5 border-l border-gray-200">
                                <div className="flex items-center gap-0.5">
                                  <ArrowUpRight size={10} className="text-blue-500" />
                                  <span className="text-[9px] font-bold text-gray-400">출근 {spot.commute_morning_2}</span>
                                </div>
                                <div className="flex items-center gap-0.5">
                                  <ArrowDownLeft size={10} className="text-pink-500" />
                                  <span className="text-[9px] font-bold text-gray-400">퇴근 {spot.commute_evening_2}</span>
                                </div>
                              </div>
                            </div>
                          )}
                          <div className="ml-auto flex items-center gap-1">
                            <div className="text-[10px] font-black text-gray-400 mr-1">총 {spot.total_cost}만/월</div>
                            <ChevronDown size={14} className={`text-gray-300 transition-transform ${expandedSpotIndex === i ? 'rotate-180' : ''}`} />
                          </div>
                        </div>
                      </div>
                    </button>
                    {expandedSpotIndex === i && (
                      <div className="px-4 pb-4 animate-in slide-in-from-top-4 duration-500">
                        <div className="h-px bg-gray-100 mb-3" />
                        {spot.complexes.length > 1 && (
                          <div className="space-y-1.5 mb-3">
                            <div className="text-[9px] font-black text-gray-400 uppercase tracking-widest px-1">같은 역세권 다른 단지</div>
                            {spot.complexes.map((apt, idx) => (
                              <div key={complexKeys[i][idx]} onClick={() => setExpandedComplexIdx(idx)} className={`p-2.5 rounded-xl border transition-all cursor-pointer ${expandedComplexIdx === idx ? 'bg-blue-50 border-blue-200' : 'bg-gray-50/50 border-transparent'}`}>
                                <div className="flex justify-between items-center gap-2">
                                  <div className="flex items-center space-x-1.5 overflow-hidden"><span className={`text-[12px] font-black tracking-tight truncate ${expandedComplexIdx === idx ? 'text-blue-700' : 'text-gray-700'}`}>{apt.name}</span><ExternalLink size={9} className="text-gray-300 shrink-0 hover:text-blue-500 transition-colors" onClick={(e) => { e.stopPropagation(); window.open(getNaverLandUrl(apt.name, apt.dong), '_blank'); }} /></div>
                                  <div className="text-right shrink-0"><span className="text-[10px] font-black text-blue-600">{apt.display_price_value}</span></div>
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
                        <button onClick={() => {const c = spot.complexes?.[expandedComplexIdx] || spot.complexes?.[0]; if(c) window.open(getNaverLandUrl(c.name, c.dong), '_blank');}} className="w-full bg-gray-900 hover:bg-black text-white font-black py-3 rounded-xl text-xs transition-all flex items-center justify-center space-x-2 active:scale-95 shadow-lg"><ExternalLink size={14} strokeWidth={3} /> <span>네이버 부동산 매물 보기</span></button>
                      </div>
                    )}
                  </div>
                  );
                })}
                <div className="mt-4 p-6 bg-orange-50/50 rounded-[2rem] border border-orange-100 text-center space-y-3">
                  <div className="text-[20px]">💡</div>
                  <h6 className="text-[13px] font-black text-gray-900 leading-tight">혹시 '저렴한 집'만 찾고 계셨나요?</h6>
                  <p className="text-[11px] font-bold text-gray-500 leading-relaxed">부자들은 집을 살 때 시간을 함께 삽니다. 왕복 2시간의 통근은 한 달에 약 40시간의 자유를 뺏습니다.</p>
                </div>
              </>
            ) : results && results.length === 0 ? (
              <div className="flex flex-col items-center justify-center text-center p-8 py-16 animate-in fade-in duration-500">
                <div className="w-16 h-16 bg-red-50 rounded-full flex items-center justify-center mb-6 text-red-500"><AlertTriangle size={32} /></div>
                <h4 className="text-[18px] font-black text-gray-900 mb-2">분석 결과가 없습니다</h4>
                <p className="text-[12px] font-bold text-gray-400 leading-relaxed mb-8">조건이 너무 까다로워 적절한 단지를 찾지 못했습니다.<br/>다음 조정을 통해 다시 시도해 보세요.</p>
                <div className="w-full space-y-2">
                  {[
                    ['주거비 한도 높이기', '현재보다 5~10% 정도 예산을 높여보세요.'],
                    ['방 타입 변경', '면적 제한을 조금 더 넓게 설정해 보세요.'],
                    ['준공 연한 해제', '신축 위주라면 구축까지 범위를 넓혀보세요.'],
                  ].map(([title, desc], idx) => (
                    <div key={idx} className="bg-white p-3 rounded-xl border border-gray-100 text-left">
                      <div className="text-[11px] font-black text-gray-700 mb-0.5">{title}</div>
                      <div className="text-[10px] font-medium text-gray-400 leading-tight">{desc}</div>
                    </div>
                  ))}
                </div>
                <button onClick={() => { setInputsCollapsed(false); setMobileSheetState('full'); }} className="mt-8 w-full py-3 bg-blue-600 text-white rounded-xl font-black text-[13px] shadow-lg">조건 수정하러 가기</button>
              </div>
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

      {results && results.length > 0 && mobileSheetState === 'hidden' && (
        <div className="md:hidden absolute bottom-6 inset-x-0 z-[1100] flex overflow-x-auto no-scrollbar gap-4 px-4 snap-x pb-4">
          {results.map((spot, i) => {
            const topApt = spot.complexes[0];
            const isSelected = expandedSpotIndex === i;
            return (
              <div
                key={spotKeys[i]}
                onClick={() => handleSpotClick(spot, i)}
                className={`flex-none w-[85vw] snap-center bg-white/95 backdrop-blur-xl p-5 rounded-[2rem] shadow-[0_20px_50px_rgba(0,0,0,0.2)] border-2 transition-all duration-300
                  ${isSelected ? 'border-blue-500 scale-100' : 'border-transparent scale-[0.96] opacity-90'}
                `}
              >
                <div className="flex justify-between items-start mb-3">
                  <div className="flex items-center gap-3">
                    <div className={`w-10 h-10 rounded-2xl flex items-center justify-center font-black ${i === 0 ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-400'}`}>{i + 1}</div>
                    <div><div className="text-[10px] font-black text-blue-500 uppercase">{spot.nearest_stations?.length > 0 ? spot.nearest_stations.join(' / ') + ' 인근' : (spot.dong || spot.name) + ' 인근'}</div><h6 className="text-[16px] font-black tracking-tighter truncate w-[40vw]">{topApt?.name}</h6></div>
                  </div>
                  <div className="text-right">
                    <div className="text-[18px] font-black text-gray-900 leading-none">월 {spot.total_cost}만</div>
                    <div className="text-[9px] font-black text-gray-300 uppercase mt-1">총 기회비용</div>
                  </div>
                </div>
                {/* 커플 모드는 배지가 하나 늘어 한 줄에 다 들어가지 않으므로 그때만 줄바꿈을 허용한다 */}
                <div className={`flex items-center gap-2 ${mode === 'couple' ? 'flex-wrap' : ''}`}>
                  <div className={`flex items-center gap-1.5 px-2 py-1 rounded-lg text-[10px] font-black ${getTimeStatus(spot.commute_time_1).bg} ${getTimeStatus(spot.commute_time_1).color} border ${getTimeStatus(spot.commute_time_1).border}`}>
                    {inputs.user1.transport === 'car' ? <Car size={12} /> : <Bus size={12} />} {mode === 'couple' ? '나: ' : ''}{spot.commute_time_1}분
                    <span className="opacity-60 ml-1.5 pl-1.5 border-l border-gray-200 flex gap-1">
                      <span className="flex items-center gap-0.5"><ArrowUpRight size={8} /> {spot.commute_morning_1}</span>
                      <span className="flex items-center gap-0.5"><ArrowDownLeft size={8} /> {spot.commute_evening_1}</span>
                    </span>
                  </div>
                  {mode === 'couple' && spot.commute_time_2 > 0 && (
                    <div className={`flex items-center gap-1.5 px-2 py-1 rounded-lg text-[10px] font-black ${getTimeStatus(spot.commute_time_2).bg} ${getTimeStatus(spot.commute_time_2).color} border ${getTimeStatus(spot.commute_time_2).border}`}>
                      {inputs.user2.transport === 'car' ? <Car size={12} /> : <Bus size={12} />} 짝: {spot.commute_time_2}분
                      <span className="opacity-60 ml-1.5 pl-1.5 border-l border-gray-200 flex gap-1">
                        <span className="flex items-center gap-0.5"><ArrowUpRight size={8} /> {spot.commute_morning_2}</span>
                        <span className="flex items-center gap-0.5"><ArrowDownLeft size={8} /> {spot.commute_evening_2}</span>
                      </span>
                    </div>
                  )}
                  <div className="bg-gray-50 px-2.5 py-1 rounded-lg text-[10px] font-black text-gray-500">지출 {topApt?.fixed_monthly_exp}만</div>
                  <div className="ml-auto flex items-center gap-1 text-blue-500 font-black text-[11px]">상세보기 <ChevronRight size={14} /></div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <button onClick={() => setMobileSheetState(prev => prev === 'hidden' ? 'peek' : 'full')} aria-label={mobileSheetState === 'full' ? '검색 패널 접기' : '검색 패널 열기'} className="md:hidden absolute bottom-8 right-6 z-[1100] w-14 h-14 bg-gray-900 text-white rounded-2xl shadow-2xl flex items-center justify-center active:scale-90 transition-all border-2 border-white/20">
        {mobileSheetState === 'full' ? <ChevronDown size={24} /> : (results ? <Settings2 size={24} /> : <Search size={24} />)}
      </button>

      <HelpModal isOpen={showHelp} onClose={() => setShowHelp(false)} />
    </div>
  );
}

export default App;
