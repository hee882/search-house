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

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("server.log", encoding="utf-8")]
)
logger = logging.getLogger(__name__)

app = FastAPI()

# --- CORS (가장 호환성 높은 설정으로 변경) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 모든 출처 허용
    allow_credentials=False, # 와일드카드(*) 사용 시 False 필수
    allow_methods=["*"],
    allow_headers=["*"],
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

def get_complexes_with_costs(city_code, salary1, time1, salary2=0, time2=0, resident_type='buy'):
    if not os.path.exists(DB_PATH): return []
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT apt_name, dong_name, AVG(deal_amount) as avg_price, COUNT(*) as cnt
            FROM transactions
            WHERE city_code = ? AND deal_year >= 2024
            GROUP BY apt_name, dong_name
            ORDER BY cnt DESC LIMIT 3
        ''', (city_code,))
        rows = cursor.fetchall()
        conn.close()
        
        complexes = []
        for row in rows:
            avg_price = int(row[2])
            if resident_type == 'buy':
                monthly_housing_cost = round((avg_price * 0.04) / 12)
                display_price_label = "평균 매매가"
                display_price_value = avg_price
            else:
                estimated_jeonse = avg_price * 0.65
                monthly_housing_cost = round((estimated_jeonse * 0.035) / 12)
                display_price_label = "추정 전세가"
                display_price_value = int(estimated_jeonse)
            
            base_transport_cost = 10 
            hidden_cost1 = calculate_hidden_life_cost(salary1, time1)
            hidden_cost2 = calculate_hidden_life_cost(salary2, time2) if salary2 > 0 else 0
            fixed_monthly_exp = monthly_housing_cost + base_transport_cost
            total_hidden_life_cost = hidden_cost1 + hidden_cost2
            total_opp_cost = fixed_monthly_exp + total_hidden_life_cost
            
            complexes.append({
                "name": row[0], "dong": row[1], 
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

@app.get("/api/stations")
async def get_stations():
    try:
        with open(STATIONS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading stations: {e}")
        return []

@app.post("/api/optimize")
async def optimize_location(request: OptimizeRequest):
    with open(STATIONS_PATH, "r", encoding="utf-8") as f:
        stations = json.load(f)
    mid_lat = (request.user1.workplace.lat + (request.user2.workplace.lat if request.user2 else request.user1.workplace.lat)) / 2
    mid_lng = (request.user1.workplace.lng + (request.user2.workplace.lng if request.user2 else request.user1.workplace.lng)) / 2
    results = []
    for spot in stations:
        dist_from_mid = calculate_distance(spot['lat'], spot['lng'], mid_lat, mid_lng)
        if dist_from_mid > 15: continue
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
    return {"results": results[:5]}

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
