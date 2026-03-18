from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional
import math
import json
import os
import logging
import sqlite3
from datetime import datetime, timedelta
from lib.kakao_api import get_kakao_commute, get_precise_coordinates

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(os.path.join(os.path.dirname(__file__), "server.log"), encoding="utf-8")]
)
logger = logging.getLogger(__name__)

app = FastAPI()

# --- CORS Configuration ---
# GitHub Pages와 로컬 개발 환경 모두에서 안정적으로 작동하도록 설정
origins = [
    "http://localhost:5173",      # 로컬 Vite 환경
    "http://127.0.0.1:5173",      # 로컬 Vite 환경 (IP)
    "https://hee882.github.io",   # 배포된 프론트엔드 환경
    "https://hee882.github.io/search-house",
    "https://search-house.onrender.com"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, 
    allow_credentials=True, # 명시적인 origin 목록을 사용할 경우 credential 허용 가능
    allow_methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# --- Models ---
class Location(BaseModel):
    lat: float
    lng: float
    name: str = "Unknown"

class UserProfile(BaseModel):
    workplace: Location
    salary: int
    transport: str

class OptimizeRequest(BaseModel):
    user1: UserProfile
    user2: Optional[UserProfile] = None
    mode: str = 'single'
    resident_type: str = 'buy'
    housing_ratio: float = 0.25
    min_area: float = 40
    max_area: float = 200
    max_building_age: int = 0
    preference: str = 'balance' # money, balance, time
    available_cash: int = 0    # 보유 자금 (만원), 0이면 기존 기회비용 모델 사용

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "server", "data", "search_house.db")
STATIONS_PATH = os.path.join(BASE_DIR, "server", "data", "stations.json")
DONG_COORDS_PATH = os.path.join(BASE_DIR, "server", "data", "dong_coordinates.json")
FRONTEND_DIST = os.path.join(BASE_DIR, "client", "dist")

# --- Global Data ---
STATIONS_DATA = []
DONG_COORDS = {}

def load_global_data():
    global STATIONS_DATA, DONG_COORDS
    try:
        if os.path.exists(STATIONS_PATH):
            with open(STATIONS_PATH, "r", encoding="utf-8") as f:
                STATIONS_DATA = json.load(f)
            logger.info(f"Loaded {len(STATIONS_DATA)} stations")

        if os.path.exists(DONG_COORDS_PATH):
            with open(DONG_COORDS_PATH, "r", encoding="utf-8") as f:
                DONG_COORDS = json.load(f)
            logger.info(f"Loaded {len(DONG_COORDS)} dong coordinates")
    except Exception as e:
        logger.error(f"Failed to load global data: {e}")

# Initial load
load_global_data()

# --- Database & Helper Functions ---
async def startup_event():
    """서버 시작 시 stations 데이터 보장"""
    if not STATIONS_DATA:
        load_stations()
    logger.info(f"Server ready: {len(STATIONS_DATA)} stations loaded")

@app.get("/api/health")
async def health():
    return {"status": "ok", "stations": len(STATIONS_DATA)}

# --- Database & Helper Functions ---

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371
    dLat, dLon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dLat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dLon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def estimate_commute_time(distance_km, transport_mode):
    speed = 30 if transport_mode == 'car' else 20
    return int((distance_km / speed) * 60) + (5 if transport_mode == 'car' else 10)

def _filter_complexes_by_iqr(raw_rows, min_samples=3):
    """
    단지별 GROUP_CONCAT 거래 데이터에 IQR 아웃라이어 제거 적용.
    price_pairs 포맷: "deposit:rent:area,..."
    반환: [(apt_name, dong_name, city_code, avg_deposit, avg_rent, avg_area, build_year), ...]
    """
    result = []
    for row in raw_rows:
        apt_name, dong_name, city_code = row[0], row[1], row[2]
        price_pairs_str = row[3]  # "5000:240:59,10000:200:59,25000:140:84,..."
        build_year = row[4]

        if not price_pairs_str:
            continue

        pairs = []
        for p in price_pairs_str.split(','):
            try:
                parts = p.split(':')
                d, r, a = int(parts[0]), int(parts[1]), float(parts[2])
                pairs.append((d, r, a))
            except Exception:
                continue

        if len(pairs) < min_samples:
            continue

        deposits = [d for d, _, _ in pairs]

        # IQR 계산 (보증금 기준 — 같은 면적 버킷 내 이상치 제거)
        if len(deposits) >= 4:
            sd = sorted(deposits)
            n = len(sd)
            q1 = sd[n // 4]
            q3 = sd[(3 * n) // 4]
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * iqr
            clean_pairs = [(d, r, a) for d, r, a in pairs if d >= lower_bound]
        else:
            clean_pairs = pairs

        if len(clean_pairs) < min_samples:
            continue

        avg_d = int(sum(d for d, _, _ in clean_pairs) / len(clean_pairs))
        avg_r = int(sum(r for _, r, _ in clean_pairs) / len(clean_pairs))
        avg_a = round(sum(a for _, _, a in clean_pairs) / len(clean_pairs), 1)

        result.append((apt_name, dong_name, city_code, avg_d, avg_r, avg_a, build_year))

    return result

def get_nearest_stations(lat, lng, n=3, max_distance_km=2.0):
    """좌표 기준 가장 가까운 지하철역 top n 반환 (2km 이내)"""
    with_dist = []
    for s in STATIONS_DATA:
        d = calculate_distance(lat, lng, s['lat'], s['lng'])
        if d <= max_distance_km:
            with_dist.append((d, s['name']))
    with_dist.sort(key=lambda x: x[0])
    return [name for _, name in with_dist[:n]]

JEONSE_LOAN_RATE = 0.035  # 전세대출 금리 연 3.5% 기준

def calculate_monthly_housing_cost(deposit, monthly_rent, available_cash=0):
    """보유 자금을 고려한 월 주거비 계산.
    available_cash > 0: 보유 자금 초과분은 전세대출(3.5%), 보유분은 기회비용(4%)
    available_cash == 0: 기존 방식 (전체 보증금에 4% 기회비용)
    """
    if available_cash > 0:
        own_cash = min(deposit, available_cash)
        loan_amount = max(0, deposit - available_cash)
        return monthly_rent + round(own_cash * 0.04 / 12) + round(loan_amount * JEONSE_LOAN_RATE / 12)
    else:
        return monthly_rent + round(deposit * 0.04 / 12)

def calculate_hidden_life_cost(salary, commute_minutes):
    hourly_wage = (salary * 10000) / 12 / 209
    base_time_value = (hourly_wage / 60) * commute_minutes * 2 * 20
    multiplier = 1.0
    if commute_minutes >= 60: multiplier = 1.3
    elif commute_minutes >= 45: multiplier = 1.15
    return round((base_time_value * multiplier) / 10000)

def get_complexes_with_costs(city_code, station_lat, station_lng, salary1, time1, salary2=0, time2=0,
                             resident_type='rent', max_housing_budget=0,
                             min_area=40, max_area=200, min_build_year=0):
    if not os.path.exists(DB_PATH): return []
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # 후보 단지를 넉넉히 가져와서 예산 및 거리 필터링
        query = '''
            SELECT apt_name, dong_name, AVG(deposit) as avg_deposit, AVG(monthly_rent) as avg_rent, COUNT(*) as cnt
            FROM rent_transactions
            WHERE city_code = ? AND deal_year >= 2024
            AND exclusive_area >= ? AND exclusive_area <= ?
        '''
        params = [city_code, min_area, max_area]
        if min_build_year > 0:
            query += ' AND build_year >= ?'
            params.append(min_build_year)

        query += '''
            GROUP BY apt_name, dong_name
            HAVING cnt >= 5
            ORDER BY cnt DESC LIMIT 50
        '''
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        candidates = []
        for row in rows:
            apt_name, dong_name = row[0], row[1]
            avg_deposit, avg_rent = int(row[2]), int(row[3])

            # 거리 필터링: 역과 동 좌표 사이의 거리 계산
            dong_key = f"{city_code}_{dong_name}"
            walk_time = 0
            if dong_key in DONG_COORDS:
                coord = DONG_COORDS[dong_key]
                dist_to_station = calculate_distance(station_lat, station_lng, coord['lat'], coord['lng'])
                if dist_to_station > 2.5: continue # 2.5km 초과 단지는 너무 멂
                walk_time = int(dist_to_station * 12) # 1km당 약 12분 도보 가정

            # 보정된 통근 시간
            adjusted_time1 = time1 + walk_time
            adjusted_time2 = time2 + (walk_time if salary2 > 0 else 0)

            # 월 주거비용 (보증금 이자 4% 가정 + 월세)
            monthly_housing_cost = round((avg_deposit * 0.04) / 12) + avg_rent

            # 예산 필터: 주거비가 예산 초과하면 건너뛰기
            if max_housing_budget > 0 and monthly_housing_cost > max_housing_budget:
                continue

            rent_type = "전세" if avg_rent == 0 else "월세"
            display_price_label = rent_type

            # 억 단위 포맷팅
            if avg_deposit >= 10000:
                eok, man = avg_deposit // 10000, avg_deposit % 10000
                dep_str = f"{eok}억" + (f" {man}만" if man > 0 else "")
            else:
                dep_str = f"{avg_deposit}만"

            display_price_value = f"{dep_str} / {avg_rent}만" if rent_type == "월세" else dep_str

            base_transport_cost = 10
            hidden_cost1 = calculate_hidden_life_cost(salary1, adjusted_time1)
            hidden_cost2 = calculate_hidden_life_cost(salary2, adjusted_time2) if salary2 > 0 else 0
            fixed_monthly_exp = monthly_housing_cost + base_transport_cost
            total_hidden_life_cost = hidden_cost1 + hidden_cost2
            total_opp_cost = fixed_monthly_exp + total_hidden_life_cost

            candidates.append({
                "name": apt_name, "dong": dong_name,
                "rent_type": rent_type,
                "deposit": avg_deposit,
                "monthly_rent": avg_rent,
                "display_price_label": display_price_label,
                "display_price_value": display_price_value,
                "fixed_monthly_exp": fixed_monthly_exp,
                "hidden_life_cost": total_hidden_life_cost,
                "total_opp_cost": total_opp_cost,
                "housing_cost_only": monthly_housing_cost,
                "commute_time_total": adjusted_time1 # 대표 시간으로 사용
            })

        # 예산 내에서 주거비 높은 순 정렬 (예산 꽉 채운 = 더 좋은 단지)
        candidates.sort(key=lambda x: x['housing_cost_only'], reverse=True)
        return candidates[:3]
    except Exception as e:
        logger.error(f"Complex calculation error: {e}")
        return []

@app.get("/api/stats/transactions")
async def get_transaction_stats(city_code: str, year: int = None, month: int = None):
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=404, detail="DB not found")
    try:
        now = datetime.now()
        year = year or now.year
        month = month or now.month

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute('''
            SELECT COUNT(*) FROM transactions
            WHERE city_code = ? AND deal_year = ? AND deal_month = ?
            AND (cancel_deal_day IS NULL OR cancel_deal_day = '')
        ''', (city_code, year, month))
        total = cursor.fetchone()[0]

        cursor.execute('''
            SELECT COUNT(*) FROM transactions
            WHERE city_code = ? AND deal_year = ? AND deal_month = ?
            AND is_new_high_price = 1
        ''', (city_code, year, month))
        new_high_count = cursor.fetchone()[0]

        cursor.execute('''
            SELECT COUNT(*) FROM transactions
            WHERE city_code = ? AND deal_year = ? AND deal_month = ?
            AND cancel_deal_day IS NOT NULL AND cancel_deal_day != ''
        ''', (city_code, year, month))
        cancel_count = cursor.fetchone()[0]

        cursor.execute('''
            SELECT deal_day, COUNT(*) as cnt,
                   SUM(CASE WHEN is_new_high_price = 1 THEN 1 ELSE 0 END) as new_high
            FROM transactions
            WHERE city_code = ? AND deal_year = ? AND deal_month = ?
            AND (cancel_deal_day IS NULL OR cancel_deal_day = '')
            GROUP BY deal_day ORDER BY deal_day
        ''', (city_code, year, month))
        daily = [{"day": r[0], "count": r[1], "new_high": r[2]} for r in cursor.fetchall()]

        cursor.execute('''
            SELECT buyer_type, COUNT(*) FROM transactions
            WHERE city_code = ? AND deal_year = ? AND deal_month = ?
            AND (cancel_deal_day IS NULL OR cancel_deal_day = '')
            AND buyer_type IS NOT NULL AND buyer_type != ''
            GROUP BY buyer_type
        ''', (city_code, year, month))
        buyer_types = {r[0]: r[1] for r in cursor.fetchall()}

        conn.close()

        return {
            "city_code": city_code,
            "period": f"{year}-{month:02d}",
            "summary": {
                "total": total,
                "new_high_count": new_high_count,
                "cancel_count": cancel_count,
                "buyer_types": buyer_types
            },
            "daily": daily
        }
    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/new-highs")
async def get_new_highs(city_code: str, limit: int = 20):
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=404, detail="DB not found")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT t.apt_name, t.dong_name, t.exclusive_area, t.deal_amount,
                   t.deal_year, t.deal_month, t.deal_day, t.floor, t.build_year,
                   (SELECT MAX(t2.deal_amount) FROM transactions t2
                    WHERE t2.apt_name = t.apt_name AND t2.dong_name = t.dong_name
                    AND t2.exclusive_area = t.exclusive_area
                    AND (t2.cancel_deal_day IS NULL OR t2.cancel_deal_day = '')
                    AND t2.id < t.id) as prev_high
            FROM transactions t
            WHERE t.city_code = ? AND t.is_new_high_price = 1
            AND (t.cancel_deal_day IS NULL OR t.cancel_deal_day = '')
            ORDER BY t.deal_year DESC, t.deal_month DESC, t.deal_day DESC
            LIMIT ?
        ''', (city_code, limit))
        rows = cursor.fetchall()
        conn.close()

        items = []
        for r in rows:
            prev = r[9] or 0
            increase_rate = round((r[3] - prev) / prev * 100, 2) if prev > 0 else 0
            items.append({
                "apt_name": r[0], "dong_name": r[1],
                "exclusive_area": r[2], "deal_amount": r[3],
                "deal_date": f"{r[4]}-{r[5]:02d}-{r[6]:02d}",
                "floor": r[7], "build_year": r[8],
                "prev_high": prev,
                "increase_rate": increase_rate
            })
        return {"city_code": city_code, "items": items}
    except Exception as e:
        logger.error(f"New highs error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stations")
async def get_stations():
    if not STATIONS_DATA:
        # Retry loading once if memory is empty
        load_stations()
    return STATIONS_DATA

@app.post("/api/optimize")
async def optimize_location(request: OptimizeRequest):
    try:
        # 1. 날짜 및 시간 설정 (차주 월요일 기준)
        now = datetime.now()
        days_ahead = 0 - now.weekday()
        if days_ahead <= 0: days_ahead += 7
        next_monday = now + timedelta(days=days_ahead)
        # 08:00 도착을 위해 보통 07:20분경 출발하는 피크 타임 설정
        time_morning = next_monday.replace(hour=7, minute=20, second=0, microsecond=0).strftime("%Y%m%d%H%M")
        # 18:00 정시 퇴근 피크 타임 설정
        time_evening = next_monday.replace(hour=18, minute=0, second=0, microsecond=0).strftime("%Y%m%d%H%M")

        # 2. 월 주거비 예산 계산 (만원 단위)
        total_salary = request.user1.salary
        if request.mode == 'couple' and request.user2:
            total_salary += request.user2.salary
        max_housing_budget = round((total_salary * 10000 / 12) * request.housing_ratio / 10000)
        
        # 2. 전역 스캐닝: 조건에 맞는 모든 단지 로드
        min_build_year = 0
        if request.max_building_age > 0:
            min_build_year = datetime.now().year - request.max_building_age

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 단지별 전체 거래를 GROUP_CONCAT으로 가져와 Python에서 IQR 아웃라이어 제거
        # 보증금 3000만원 미만 = 공공임대·갱신 특수계약으로 간주 1차 제외
        RENTAL_FILTER = """
            AND deposit >= 3000
            AND apt_name NOT LIKE '%임대%'
            AND apt_name NOT LIKE '%행복주택%'
            AND apt_name NOT LIKE '%LH%'
            AND apt_name NOT LIKE '%SH%'
            AND apt_name NOT LIKE '%공공임대%'
            AND apt_name NOT LIKE '%국민임대%'
            AND apt_name NOT LIKE '%영구임대%'
            AND apt_name NOT LIKE '%장기전세%'
            AND apt_name NOT LIKE '%시프트%'
            AND apt_name NOT LIKE '%뉴스테이%'
            AND apt_name NOT LIKE '%기업형임대%'
            AND apt_name NOT LIKE '%도시형%'
            AND apt_name NOT LIKE '%오피스텔%'
        """
        area_filter = "AND exclusive_area >= ? AND exclusive_area <= ?"
        year_filter = " AND build_year >= ?" if min_build_year > 0 else ""

        raw_query = f"""
            SELECT apt_name, dong_name, city_code,
                   GROUP_CONCAT(deposit || ':' || monthly_rent || ':' || exclusive_area) as price_pairs,
                   build_year
            FROM rent_transactions
            WHERE deal_year >= 2024
            {RENTAL_FILTER}
            {area_filter}
            {year_filter}
            GROUP BY apt_name, dong_name, city_code
            HAVING COUNT(*) >= 3
        """
        params = [request.min_area, request.max_area]
        if min_build_year > 0:
            params.append(min_build_year)

        cursor.execute(raw_query, params)
        raw_rows = cursor.fetchall()
        conn.close()

        # IQR 기반 아웃라이어 제거 후 클린 평균 산출
        all_complexes = _filter_complexes_by_iqr(raw_rows, min_samples=3)

        # 결과 없으면 IQR min_samples 완화해서 재시도 (거래량이 적은 지역 대응)
        if not all_complexes:
            logger.info("IQR 필터 후 결과 없음 → min_samples=2로 완화 재시도")
            all_complexes = _filter_complexes_by_iqr(raw_rows, min_samples=2)

        # 3. 직선거리 기준 후보군 100개 추출 (Fast Scan)
        mid_lat = (request.user1.workplace.lat + (request.user2.workplace.lat if request.user2 else request.user1.workplace.lat)) / 2
        mid_lng = (request.user1.workplace.lng + (request.user2.workplace.lng if request.user2 else request.user1.workplace.lng)) / 2
        
        candidates = []
        for row in all_complexes:
            apt_name, dong_name, city_code = row[0], row[1], row[2]
            avg_deposit, avg_rent, avg_area = int(row[3]), int(row[4]), row[5]
            
            # 월 주거비용 계산 (보유 자금 있으면 전세대출 이자 모델 적용)
            monthly_housing_cost = calculate_monthly_housing_cost(avg_deposit, avg_rent, request.available_cash)
            if max_housing_budget > 0 and monthly_housing_cost > max_housing_budget:
                continue

            # 좌표 정보 획득 (동 좌표 기반)
            dong_key = f"{city_code}_{dong_name}"
            lat, lng = None, None
            
            if dong_key in DONG_COORDS:
                coord = DONG_COORDS[dong_key]
                lat, lng = coord['lat'], coord['lng']
            else:
                # [고도화] 특정 동 좌표가 없으면 구 단위(city_code) 대표 좌표라도 매칭 시도
                # (지방이나 경기도 외곽 대응용)
                city_key = f"{city_code}_"
                # city_code로 시작하는 첫 번째 동의 좌표를 구 대표로 사용
                for k, v in DONG_COORDS.items():
                    if k.startswith(city_code):
                        lat, lng = v['lat'], v['lng']
                        break
            
            if not lat:
                continue # 여전히 좌표 정보 없으면 제외

            dist_from_mid = calculate_distance(lat, lng, mid_lat, mid_lng)
            if dist_from_mid > 80: continue # 수도권 광역 커버 (80km)

            candidates.append({
                "name": apt_name, "dong": dong_name, "city_code": city_code,
                "lat": lat, "lng": lng, "monthly_housing_cost": monthly_housing_cost,
                "dist_from_mid": dist_from_mid, "avg_deposit": avg_deposit, "avg_rent": avg_rent,
                "avg_area": avg_area
            })

        # 직장 중심점에서 가까운 순으로 50개 후보군 정밀 분석 (후보군 확대)
        candidates.sort(key=lambda x: x['dist_from_mid'])
        top_candidates = candidates[:50]

        results = []
        base_transport_cost = 10 # 기본 교통비

        for spot in top_candidates:
            # [고도화] 단지별 정밀 좌표 획득 시도 (동 좌표 -> 실제 단지 위치)
            precise_lat, precise_lng = get_precise_coordinates(DB_PATH, spot['name'], spot['dong'], spot['city_code'])
            if precise_lat and precise_lng:
                spot['lat'], spot['lng'] = precise_lat, precise_lng
                
            # 카카오 정밀 경로 분석 (출근/퇴근 각각)
            # 출근: 08:00 도착 시뮬레이션
            morning_time1, _ = get_kakao_commute(DB_PATH, spot['lat'], spot['lng'], request.user1.workplace.lat, request.user1.workplace.lng, request.user1.transport, goal_arrive_time="0800")
            # 퇴근: 18:00 정시 출발
            evening_time1, _ = get_kakao_commute(DB_PATH, request.user1.workplace.lat, request.user1.workplace.lng, spot['lat'], spot['lng'], request.user1.transport, departure_time=time_evening)
            
            avg_time1 = (morning_time1 + evening_time1) // 2
            
            morning_time2, evening_time2, avg_time2 = 0, 0, 0
            if request.mode == 'couple' and request.user2:
                morning_time2, _ = get_kakao_commute(DB_PATH, spot['lat'], spot['lng'], request.user2.workplace.lat, request.user2.workplace.lng, request.user2.transport, goal_arrive_time="0800")
                evening_time2, _ = get_kakao_commute(DB_PATH, request.user2.workplace.lat, request.user2.workplace.lng, spot['lat'], spot['lng'], request.user2.transport, departure_time=time_evening)
                avg_time2 = (morning_time2 + evening_time2) // 2
            
            # 기회비용 계산 (평균 시간 기준)
            hidden_cost1 = calculate_hidden_life_cost(request.user1.salary, avg_time1)
            hidden_cost2 = calculate_hidden_life_cost(request.user2.salary, avg_time2) if request.mode == 'couple' and request.user2 else 0
            
            # 성향 가중치 적용
            fixed_monthly_exp = spot['monthly_housing_cost'] + base_transport_cost
            total_hidden_life_cost = hidden_cost1 + hidden_cost2
            
            # 가중치 설정
            w_fixed, w_hidden = 1.0, 1.0
            if request.preference == 'money': w_fixed, w_hidden = 1.6, 0.4
            elif request.preference == 'time': w_fixed, w_hidden = 0.4, 1.6
            
            weighted_score = int(fixed_monthly_exp * w_fixed + total_hidden_life_cost * w_hidden)
            total_opp_cost = fixed_monthly_exp + total_hidden_life_cost

            nearest_stations = get_nearest_stations(spot['lat'], spot['lng'])
            results.append({
                "name": spot['name'], "lat": spot['lat'], "lng": spot['lng'],
                "nearest_stations": nearest_stations,
                "dong": spot['dong'],
                "total_cost": total_opp_cost,
                "commute_time_1": avg_time1,
                "commute_morning_1": morning_time1,
                "commute_evening_1": evening_time1,
                "commute_time_2": avg_time2,
                "commute_morning_2": morning_time2,
                "commute_evening_2": evening_time2,
                "complexes": [{
                    "name": spot['name'], "dong": spot['dong'], "rent_type": "전세" if spot['avg_rent'] == 0 else "월세",
                    "display_price_label": "전세" if spot['avg_rent'] == 0 else "월세",
                    "display_price_value": f"{spot['avg_deposit']}만 / {spot['avg_rent']}만" if spot['avg_rent'] > 0 else f"{spot['avg_deposit']}만",
                    "fixed_monthly_exp": fixed_monthly_exp,
                    "hidden_life_cost": total_hidden_life_cost,
                    "total_opp_cost": total_opp_cost,
                    "avg_area": spot['avg_area'],
                    "loan_amount": max(0, spot['avg_deposit'] - request.available_cash) if request.available_cash > 0 else 0,
                    "loan_monthly": round(max(0, spot['avg_deposit'] - request.available_cash) * JEONSE_LOAN_RATE / 12) if request.available_cash > 0 else 0,
                }],
                "score": weighted_score
            })

        # 최종 가성비 순으로 정렬
        results.sort(key=lambda x: x['score'])
        return {"results": results[:5]}
    except Exception as e:
        logger.error(f"Global Scan error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- Static Frontend Serving ---
if os.path.exists(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="static")
    @app.get("/{catchall:path}")
    async def serve_react_app(catchall: str):
        index_file = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.exists(index_file): return FileResponse(index_file)
        return {"error": "Frontend not built."}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
