import os
import requests
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load .env
load_dotenv()

logger = logging.getLogger(__name__)
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")

def get_kakao_commute(db_path, from_lat, from_lng, to_lat, to_lng, transport_mode='car', departure_time=None, goal_arrive_time=None):
    """
    카카오 모빌리티 API를 통해 정밀 통근 시간을 반환.
    - goal_arrive_time (HHMM): 해당 시간에 도착하기 위한 시뮬레이션 수행
    - departure_time (YYYYMMDDHHMM): 특정 시간에 출발하는 정보 획득
    """
    f_lat, f_lng = round(from_lat, 4), round(from_lng, 4)
    t_lat, t_lng = round(to_lat, 4), round(to_lng, 4)
    
    # 1. 캐시 확인
    cache_key = departure_time if departure_time else f"arrive_{goal_arrive_time}"
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS commute_cache_v3 (
                from_lat REAL, from_lng REAL, to_lat REAL, to_lng REAL,
                transport_mode TEXT, cache_key TEXT,
                duration_min INTEGER, distance_km REAL,
                PRIMARY KEY (from_lat, from_lng, to_lat, to_lng, transport_mode, cache_key)
            )
        ''')
        cursor.execute('''
            SELECT duration_min, distance_km FROM commute_cache_v3
            WHERE from_lat = ? AND from_lng = ? AND to_lat = ? AND to_lng = ? 
            AND transport_mode = ? AND cache_key = ?
        ''', (f_lat, f_lng, t_lat, t_lng, transport_mode, cache_key))
        cache = cursor.fetchone()
        if cache:
            conn.close()
            return cache[0], cache[1]
    except Exception as e:
        logger.error(f"Cache lookup error: {e}")

    # 2. API 호출 로직
    def call_kakao_api(d_time):
        if not KAKAO_REST_API_KEY: 
            logger.warning("[Kakao API] KAKAO_REST_API_KEY is missing in .env")
            return None
        
        # [중요] JavaScript Key 오사용 방지 (feb4... 는 JS 키일 확률 높음)
        if KAKAO_REST_API_KEY.startswith('feb433'):
            logger.error("[Kakao API] Detected JavaScript Key in KAKAO_REST_API_KEY. Please use REST API Key instead.")
            return None

        url = "https://apis-navi.kakaomobility.com/v1/future/directions"
        headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY.strip()}"}
        params = {
            "origin": f"{from_lng},{from_lat}",
            "destination": f"{to_lng},{to_lat}",
            "departure_time": d_time,
            "priority": "RECOMMEND"
        }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if data.get('routes') and data['routes'][0]['result_code'] == 0:
                    route = data['routes'][0]['summary']
                    return int(route['duration'] / 60), route['distance'] / 1000
                else:
                    logger.error(f"[Kakao API] API Error: {data}")
            elif res.status_code == 401:
                logger.error("[Kakao API] 401 Unauthorized: REST API Key is invalid or not allowed.")
            else:
                logger.error(f"[Kakao API] HTTP Error {res.status_code}")
        except Exception as e:
            logger.error(f"API Call failed: {e}")
        return None

    # 3. 시간 설정 및 시뮬레이션
    duration, distance = 0, 0
    now = datetime.now()
    days_ahead = 0 - now.weekday()
    if days_ahead <= 0: days_ahead += 7
    target_date = (now + timedelta(days=days_ahead))

    # hour 추출 (가중치용)
    current_hour = 0
    if goal_arrive_time:
        current_hour = int(goal_arrive_time[:2])
        # "08:00 도착" 시뮬레이션
        goal_h = int(goal_arrive_time[:2])
        goal_m = int(goal_arrive_time[2:])
        test_departure = target_date.replace(hour=goal_h, minute=goal_m) - timedelta(minutes=45)
        
        res1 = call_kakao_api(test_departure.strftime("%Y%m%d%H%M"))
        if res1:
            dur1, dist1 = res1
            actual_arrive = test_departure + timedelta(minutes=dur1)
            target_arrive = target_date.replace(hour=goal_h, minute=goal_m)
            diff_min = (actual_arrive - target_arrive).total_seconds() / 60
            if abs(diff_min) > 5:
                refined_departure = test_departure - timedelta(minutes=int(diff_min))
                res2 = call_kakao_api(refined_departure.strftime("%Y%m%d%H%M"))
                if res2: duration, distance = res2
                else: duration, distance = dur1, dist1
            else:
                duration, distance = dur1, dist1
    
    elif departure_time:
        current_hour = int(departure_time[8:10])
        res = call_kakao_api(departure_time)
        if res: duration, distance = res

    # 4. Fallback (API 실패 혹은 대중교통)
    if not duration:
        R = 6371
        import math
        dLat, dLon = math.radians(to_lat - from_lat), math.radians(to_lng - from_lng)
        a = math.sin(dLat/2)**2 + math.cos(math.radians(from_lat)) * math.cos(math.radians(to_lat)) * math.sin(dLon/2)**2
        dist = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance = dist
        
        # 기본 속도 설정
        speed = 25 if transport_mode == 'public' else 35
        base_duration = (dist / speed) * 60
        
        # 시간대별 트래픽 가중치 (API 실패 시에도 차이를 보여주기 위함)
        traffic_multiplier = 1.0
        if 7 <= current_hour <= 9: traffic_multiplier = 1.35 # 출근
        elif 17 <= current_hour <= 19: traffic_multiplier = 1.20 # 퇴근
            
        duration = int(base_duration * traffic_multiplier) + (15 if transport_mode == 'public' else 5)

    # 5. 결과 캐싱
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO commute_cache_v3
            (from_lat, from_lng, to_lat, to_lng, transport_mode, cache_key, duration_min, distance_km)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (f_lat, f_lng, t_lat, t_lng, transport_mode, cache_key, duration, distance))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Cache save error: {e}")

    return duration, distance
