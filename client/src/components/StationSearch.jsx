import { useState, useRef, useEffect, useMemo } from 'react';
import { Loader2, Train, X } from 'lucide-react';
import LineBadge from './LineBadge';
import { STATION_ALIASES, searchStations } from '../lib/stations';
import { buildUniqueKeys } from '../lib/keys';
import { useIsMobile } from '../lib/useIsMobile';

// iconFocusClass 는 'group-focus-within:text-blue-500' 처럼 완성된 클래스 이름이어야 한다.
// Tailwind 는 소스에 적힌 문자열만 보고 CSS 를 만들기 때문에 런타임에 조립한 이름은 스타일이 생성되지 않는다.
function StationSearch({ value, onChange, placeholder, stations, icon: IconComponent, iconFocusClass, stationLoading, stationError, onRetry }) {
  const [keyword, setKeyword] = useState(value?.name || "");
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const dropdownRef = useRef(null);
  const listRef = useRef(null);

  const isMobile = useIsMobile();

  const filteredStations = useMemo(() => searchStations(stations, keyword, value?.name), [keyword, stations, value]);
  const stationKeys = useMemo(() => buildUniqueKeys(filteredStations, (s) => `${s.name}|${s.line || ''}`), [filteredStations]);

  const handleSelect = (station) => {
    onChange(station);
    setKeyword(station.name);
    setIsOpen(false);
    setSelectedIndex(-1);
  };

  const handleKeyDown = (e) => {
    if (!isOpen) {
      if (e.key === 'ArrowDown' || e.key === 'Enter') setIsOpen(true);
      return;
    }
    const list = filteredStations;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(prev => {
        const next = Math.min(prev + 1, list.length - 1);
        listRef.current?.children[next]?.scrollIntoView({ block: 'nearest' });
        return next;
      });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(prev => {
        const next = Math.max(prev - 1, 0);
        listRef.current?.children[next]?.scrollIntoView({ block: 'nearest' });
        return next;
      });
    } else if ((e.key === 'Enter' || e.key === 'Tab') && selectedIndex >= 0 && list[selectedIndex]) {
      e.preventDefault();
      handleSelect(list[selectedIndex]);
    } else if (e.key === 'Escape') {
      setIsOpen(false);
      setSelectedIndex(-1);
    }
  };

  useEffect(() => {
    const handleClickOutside = (e) => { if (dropdownRef.current && !dropdownRef.current.contains(e.target)) setIsOpen(false); };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div className={`relative group w-full ${isOpen && isMobile ? 'z-[9999]' : ''}`} ref={dropdownRef}>
      <div className={`flex items-center relative transition-all duration-300 ${isOpen && isMobile ? 'fixed top-0 inset-x-0 p-4 bg-white shadow-xl z-[10000]' : ''}`}>
        {IconComponent && <IconComponent className={`absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-300 ${iconFocusClass} transition-colors ${isOpen && isMobile ? 'left-8' : ''}`} />}
        <input
          type="text" value={keyword}
          onChange={(e) => { setKeyword(e.target.value); setIsOpen(true); setSelectedIndex(0); }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
          className={`w-full pl-10 pr-10 py-3 bg-gray-50 border-none rounded-xl text-[14px] font-black focus:ring-2 focus:ring-blue-500/20 outline-none transition-all placeholder:text-gray-300 ${isOpen && isMobile ? 'pl-14 py-4 text-[16px] bg-gray-100 rounded-2xl' : ''}`}
          placeholder={placeholder}
        />
        {(keyword || (isOpen && isMobile)) && (
            <button aria-label="검색어 지우기"
            onClick={() => { setKeyword(""); if(isMobile) setIsOpen(false); }}
            className={`absolute right-3 top-1/2 -translate-y-1/2 p-1.5 text-gray-400 hover:text-gray-600 rounded-full bg-gray-200/50 ${isOpen && isMobile ? 'right-8' : ''}`}
          >
            <X size={14} strokeWidth={3} />
          </button>
        )}
      </div>

      {isOpen && (
        <div className={`absolute left-0 w-full mb-2 md:mt-1.5 bg-white rounded-2xl shadow-[0_20px_50px_rgba(0,0,0,0.15)] border border-gray-100 z-[2000] overflow-hidden transition-all duration-300
          ${isMobile
            ? 'fixed inset-0 top-[72px] rounded-none border-none shadow-none z-[9999]'
            : 'absolute top-full'
          }
        `}>
          <div className="px-4 py-3 bg-gray-50/50 text-[10px] font-black text-gray-400 uppercase tracking-widest border-b border-gray-100 flex justify-between items-center">
            <span>{stationLoading ? '데이터 로딩 중...' : (!keyword ? '주요 거점 추천' : '검색 결과')}</span>
            {stationError && <button onClick={onRetry} className="text-blue-600 hover:underline" aria-label="지하철역 목록 다시 불러오기">재시도</button>}
          </div>
          {stationLoading ? (
            <div className="p-12 flex flex-col items-center gap-4">
              <Loader2 className="animate-spin text-blue-500" size={32} />
              <p className="text-[12px] font-bold text-gray-400">전국 지하철역 매핑 중...</p>
            </div>
          ) : (
            <div ref={listRef} className={`overflow-y-auto custom-scrollbar ${isMobile ? 'h-[calc(100%-40px)] pb-20' : 'max-h-[350px]'}`}>
              {filteredStations.length > 0 ? (
                filteredStations.map((s, i) => (
                  <button
                    key={stationKeys[i]}
                    onClick={() => handleSelect(s)}
                    onMouseEnter={() => setSelectedIndex(i)}
                    className={`w-full text-left px-6 py-4 flex items-center gap-5 transition-colors duration-150 relative overflow-hidden group/item ${selectedIndex === i ? 'bg-blue-50/80' : 'text-gray-600 border-b border-gray-50 last:border-0'}`}
                  >
                    <div className={`absolute left-0 top-0 bottom-0 w-1.5 bg-blue-500 transition-transform duration-200 ease-out ${selectedIndex === i ? 'translate-x-0' : '-translate-x-full'}`} />
                    <div className={`shrink-0 p-2.5 rounded-2xl transition-all duration-200 ${selectedIndex === i ? 'bg-white shadow-md scale-110' : 'bg-gray-100'}`}>
                      <Train className={`h-5 w-5 ${selectedIndex === i ? 'text-blue-500' : 'text-gray-400'}`} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className={`text-[16px] font-black tracking-tight truncate transition-colors ${selectedIndex === i ? 'text-blue-700' : 'text-gray-800'}`}>
                        {s.name}
                        {STATION_ALIASES[s.name] && <span className="ml-2 text-[13px] font-bold text-gray-400">({STATION_ALIASES[s.name][0].replace('역', '')})</span>}
                      </div>
                      <div className="mt-1.5 flex items-center gap-2 overflow-x-auto no-scrollbar"><LineBadge line={s.line} /></div>
                    </div>
                  </button>
                ))
              ) : (
                <div className="p-20 text-center">
                  <p className="text-[14px] font-black text-gray-300">검색 결과가 없습니다.</p>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default StationSearch;
