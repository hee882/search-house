import { Search, MapPin, Zap, ShieldCheck, X, DollarSign, Home, TrendingUp } from 'lucide-react';

function HelpModal({ isOpen, onClose }) {
  if (!isOpen) return null;
  return (
    <div className="fixed inset-0 z-[9999] flex items-end md:items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-slate-900/70 backdrop-blur-md animate-in fade-in duration-300" />
      <div className="relative bg-white w-full md:w-[520px] md:max-h-[88vh] max-h-[93vh] md:rounded-[2.5rem] rounded-t-[2.5rem] shadow-[0_30px_80px_rgba(0,0,0,0.35)] overflow-hidden flex flex-col animate-in slide-in-from-bottom-10 duration-500" onClick={e => e.stopPropagation()}>

        {/* 헤더 */}
        <div className="sticky top-0 bg-white/90 backdrop-blur-xl z-10 px-7 pt-6 pb-4 border-b border-gray-100 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-gray-900 rounded-2xl flex items-center justify-center shadow-lg">
              <Home size={18} className="text-white" />
            </div>
            <div>
              <span className="text-[17px] font-black tracking-tight text-gray-900 leading-none block">Search House 가이드</span>
              <span className="text-[10px] font-bold text-blue-500 uppercase tracking-widest">당신의 시간을 되찾는 방법</span>
            </div>
          </div>
          <button onClick={onClose} aria-label="사용 가이드 닫기" className="p-2 bg-gray-100 rounded-full hover:bg-gray-200 transition-all active:scale-90"><X size={18} className="text-gray-500" /></button>
        </div>

        <div className="flex-1 overflow-y-auto custom-scrollbar">

          {/* 히어로 훅 */}
          <div className="bg-gray-900 px-7 py-8 text-white">
            <div className="text-[11px] font-black text-blue-400 uppercase tracking-widest mb-3">The Hidden Cost</div>
            <h2 className="text-[22px] font-black leading-[1.2] tracking-tight mb-4">
              월세 80만원짜리 집이<br/>
              <span className="text-blue-400">실제로는 140만원</span>일 수 있습니다.
            </h2>
            <p className="text-[12px] font-medium text-slate-400 leading-relaxed">
              왕복 90분 통근 기준, 연봉 4천만원 직장인은 매달 약 <span className="text-white font-black">60만원의 시간</span>을 길 위에 버리고 있습니다. 이 앱은 그 숨겨진 비용까지 계산합니다.
            </p>
          </div>

          <div className="px-7 py-6 space-y-7">

            {/* 어떤 걸 찾아주나 */}
            <div className="space-y-3">
              <div className="text-[10px] font-black text-gray-400 uppercase tracking-widest">무엇을 찾아주나요</div>
              <div className="space-y-2.5">
                {[
                  { icon: <MapPin size={14} className="text-blue-500" />, bg: 'bg-blue-50', title: '최적 주거 입지', desc: '직장까지의 실제 출퇴근 시간과 주거비를 함께 고려한 수도권 최적 동네를 추천합니다.' },
                  { icon: <DollarSign size={14} className="text-green-500" />, bg: 'bg-green-50', title: '진짜 월 지출액', desc: '집세 + 교통비에 더해 "내 시급 × 통근시간"을 계산해 눈에 보이지 않는 비용을 수치화합니다.' },
                  { icon: <TrendingUp size={14} className="text-orange-500" />, bg: 'bg-orange-50', title: '실거래가 기반 단지', desc: '국토교통부 실거래가 API로 수집한 최근 전·월세 데이터를 기반으로 현실적인 단지를 제시합니다.' },
                ].map((item, i) => (
                  <div key={i} className="flex gap-3 p-3.5 bg-gray-50 rounded-2xl border border-gray-100">
                    <div className={`shrink-0 w-8 h-8 ${item.bg} rounded-xl flex items-center justify-center`}>{item.icon}</div>
                    <div>
                      <div className="text-[12px] font-black text-gray-900 mb-0.5">{item.title}</div>
                      <div className="text-[11px] font-medium text-gray-400 leading-snug">{item.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* 사용법 3스텝 */}
            <div className="space-y-3">
              <div className="text-[10px] font-black text-gray-400 uppercase tracking-widest">3단계로 끝나는 분석</div>
              <div className="flex gap-2">
                {[
                  { step: '1', label: '직장역 선택', sub: '통근 시작점' },
                  { step: '2', label: '연봉 입력', sub: '시급 자동 계산' },
                  { step: '3', label: '결과 확인', sub: '지도 위에 표시' },
                ].map((s, i) => (
                  <div key={i} className="flex-1 bg-gray-900 rounded-2xl p-3.5 text-center relative overflow-hidden">
                    <div className="absolute top-1 right-2 text-[28px] font-black text-white/5">{s.step}</div>
                    <div className="text-[18px] font-black text-blue-400 mb-1">{s.step}</div>
                    <div className="text-[11px] font-black text-white leading-tight">{s.label}</div>
                    <div className="text-[9px] font-medium text-slate-500 mt-0.5">{s.sub}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* 핵심 인사이트 */}
            <div className="bg-blue-600 rounded-[2rem] p-6 text-white space-y-3">
              <div className="flex items-center gap-2 mb-1">
                <Zap size={14} className="text-yellow-300 fill-yellow-300" />
                <span className="text-[10px] font-black uppercase tracking-widest text-blue-200">Key Insight</span>
              </div>
              <p className="text-[14px] font-black leading-snug">
                "같은 연봉이라도 어디에 사느냐에 따라<br/>
                <span className="text-yellow-300">실질 소득이 연 700만원 이상</span> 차이납니다."
              </p>
              <p className="text-[11px] font-medium text-blue-200 leading-relaxed">
                통근 1시간 단축 = 월 30만원 시간 절약. 10년이면 3,600만원. 이게 부동산 선택의 진짜 ROI입니다.
              </p>
            </div>

            {/* 맞벌이 특화 */}
            <div className="flex gap-3 p-4 bg-pink-50 rounded-2xl border border-pink-100">
              <div className="shrink-0 w-8 h-8 bg-pink-100 rounded-xl flex items-center justify-center"><ShieldCheck size={14} className="text-pink-500" /></div>
              <div>
                <div className="text-[12px] font-black text-pink-700 mb-0.5">맞벌이 부부 전용 모드</div>
                <div className="text-[11px] font-medium text-pink-400 leading-snug">두 사람의 직장을 동시에 고려한 '중간 지점 최적화'. 어느 한 쪽도 희생하지 않는 입지를 찾아드립니다.</div>
              </div>
            </div>

            {/* CTA */}
            <button onClick={onClose} className="w-full bg-gray-900 hover:bg-black text-white font-black py-4 rounded-2xl text-[14px] flex items-center justify-center gap-2 transition-all active:scale-[0.98] shadow-xl shadow-gray-200 mb-2">
              <Search size={16} strokeWidth={3} /> 지금 바로 분석 시작하기
            </button>

          </div>
        </div>
      </div>
    </div>
  );
}

export default HelpModal;
