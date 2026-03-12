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
from datetime import datetime

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

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "server", "data", "search_house.db")
STATIONS_PATH = os.path.join(BASE_DIR, "server", "data", "stations.json")
FRONTEND_DIST = os.path.join(BASE_DIR, "client", "dist")

# --- Global Data ---
STATIONS_DATA = []

def load_stations():
    global STATIONS_DATA
    try:
        if os.path.exists(STATIONS_PATH):
            with open(STATIONS_PATH, "r", encoding="utf-8") as f:
                STATIONS_DATA = json.load(f)
            logger.info(f"Loaded {len(STATIONS_DATA)} stations from {STATIONS_PATH}")
        else:
            logger.warning(f"Stations file not found: {STATIONS_PATH}")
            STATIONS_DATA = []
    except Exception as e:
        logger.error(f"Failed to load stations: {e}")
        STATIONS_DATA = []

# Initial load (모듈 레벨 동기 로드)
load_stations()

@app.on_event("startup")
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

def calculate_hidden_life_cost(salary, commute_minutes):
    hourly_wage = (salary * 10000) / 12 / 209
    base_time_value = (hourly_wage / 60) * commute_minutes * 2 * 20
    multiplier = 1.0
    if commute_minutes >= 60: multiplier = 1.3
    elif commute_minutes >= 45: multiplier = 1.15
    return round((base_time_value * multiplier) / 10000)

def get_complexes_with_costs(city_code, salary1, time1, salary2=0, time2=0, resident_type='rent'):
    if not os.path.exists(DB_PATH): return []
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 최근 전월세 거래 가져오기
        cursor.execute('''
            SELECT apt_name, dong_name, AVG(deposit) as avg_deposit, AVG(monthly_rent) as avg_rent, COUNT(*) as cnt
            FROM rent_transactions
            WHERE city_code = ? AND deal_year >= 2024
            GROUP BY apt_name, dong_name
            ORDER BY cnt DESC LIMIT 3
        ''', (city_code,))
        rows = cursor.fetchall()
        conn.close()
        
        complexes = []
        for row in rows:
            avg_deposit = int(row[2])
            avg_rent = int(row[3])
            
            rent_type = "전세" if avg_rent == 0 else "월세"
            display_price_label = rent_type
            
            # 억 단위 포맷팅
            if avg_deposit >= 10000:
                eok = avg_deposit // 10000
                man = avg_deposit % 10000
                dep_str = f"{eok}억" + (f" {man}만" if man > 0 else "")
            else:
                dep_str = f"{avg_deposit}만"
            
            if rent_type == "월세":
                display_price_value = f"{dep_str} / {avg_rent}만"
            else:
                display_price_value = f"{dep_str}"
            
            # 월 주거비용 (보증금 이자 4% 가정 + 월세)
            monthly_housing_cost = round((avg_deposit * 0.04) / 12) + avg_rent
            base_transport_cost = 10 
            hidden_cost1 = calculate_hidden_life_cost(salary1, time1)
            hidden_cost2 = calculate_hidden_life_cost(salary2, time2) if salary2 > 0 else 0
            fixed_monthly_exp = monthly_housing_cost + base_transport_cost
            total_hidden_life_cost = hidden_cost1 + hidden_cost2
            total_opp_cost = fixed_monthly_exp + total_hidden_life_cost
            
            complexes.append({
                "name": row[0], "dong": row[1], 
                "rent_type": rent_type,
                "deposit": avg_deposit,
                "monthly_rent": avg_rent,
                "display_price_label": display_price_label,
                "display_price_value": display_price_value,
                "fixed_monthly_exp": fixed_monthly_exp,
                "hidden_life_cost": total_hidden_life_cost,
                "total_opp_cost": total_opp_cost,
                "housing_cost_only": monthly_housing_cost
            })
        return complexes
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
        if not STATIONS_DATA:
            load_stations()
        stations = STATIONS_DATA
        mid_lat = (request.user1.workplace.lat + (request.user2.workplace.lat if request.user2 else request.user1.workplace.lat)) / 2
        mid_lng = (request.user1.workplace.lng + (request.user2.workplace.lng if request.user2 else request.user1.workplace.lng)) / 2
        results = []
        for spot in stations:
            dist_from_mid = calculate_distance(spot['lat'], spot['lng'], mid_lat, mid_lng)
            if dist_from_mid > 50: continue
            time1 = estimate_commute_time(calculate_distance(spot['lat'], spot['lng'], request.user1.workplace.lat, request.user1.workplace.lng), request.user1.transport)
            time2 = 0
            if request.mode == 'couple' and request.user2:
                time2 = estimate_commute_time(calculate_distance(spot['lat'], spot['lng'], request.user2.workplace.lat, request.user2.workplace.lng), request.user2.transport)
            complexes = get_complexes_with_costs(spot.get('city_code', ''), request.user1.salary, time1, request.user2.salary if request.user2 else 0, time2, resident_type=request.resident_type)
            if not complexes: continue
            representative_cost = complexes[0]['total_opp_cost']
            results.append({
                "name": spot['name'], "lat": spot['lat'], "lng": spot['lng'],
                "total_cost": representative_cost, "commute_time_1": time1, "commute_time_2": time2,
                "complexes": complexes, "score": representative_cost
            })
        results.sort(key=lambda x: x['score'])
        # 중복 단지 제거: 이미 노출된 단지명은 건너뛰기
        seen_complexes = set()
        deduplicated = []
        for r in results:
            top_name = r['complexes'][0]['name']
            if top_name in seen_complexes:
                continue
            for c in r['complexes']:
                seen_complexes.add(c['name'])
            deduplicated.append(r)
            if len(deduplicated) >= 5:
                break
        return {"results": deduplicated}
    except Exception as e:
        logger.error(f"Optimize error: {e}")
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
