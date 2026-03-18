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

# city_code → 구/시 이름 역방향 조회 테이블 (정밀 검색 쿼리 구성용)
def _build_code_to_district():
    try:
        region_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "region_codes.json")
        with open(region_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        mapping = {}
        for city, districts in data.items():
            for district, code in districts.items():
                mapping[str(code)] = district
        return mapping
    except Exception:
        return {}

CODE_TO_DISTRICT = _build_code_to_district()

def get_precise_coordinates(db_path, apt_name, dong_name, city_code=None):
    """
    카카오 키워드/주소 검색 API를 통해 단지의 정밀 좌표를 반환.
    DB 캐싱 지원.
    """
    # 1. 캐시 확인
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS complex_coords (
                apt_name TEXT, dong_name TEXT,
                lat REAL, lng REAL,
                PRIMARY KEY (apt_name, dong_name)
            )
        ''')
        cursor.execute('SELECT lat, lng FROM complex_coords WHERE apt_name = ? AND dong_name = ?', (apt_name, dong_name))
        cache = cursor.fetchone()
        if cache:
            conn.close()
            return cache[0], cache[1]
    except Exception as e:
        logger.error(f"Complex cache lookup error: {e}")

    # 2. API 호출
    lat, lng = None, None
    if KAKAO_REST_API_KEY:
        if KAKAO_REST_API_KEY.startswith('feb433'):
            logger.error("[Kakao API] Detected JavaScript Key. Please use REST API Key instead.")
        else:
            url = "https://dapi.kakao.com/v2/local/search/keyword.json"
            headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY.strip()}"}

            # city_code로 구/시 이름을 가져와 검색 정확도 향상
            district = CODE_TO_DISTRICT.get(str(city_code), "") if city_code else ""
            clean_apt_name = apt_name if '아파트' in apt_name else f"{apt_name} 아파트"
            # 예: "강남구 역삼동 힐스테이트 아파트"
            query_parts = [p for p in [district, dong_name, clean_apt_name] if p]
            query = " ".join(query_parts)
            params = {"query": query, "size": 5} # 5개까지 받아서 필터링
            
            try:
                res = requests.get(url, headers=headers, params=params, timeout=5)
                if res.status_code == 200:
                    data = res.json()
                    if data.get('documents'):
                        # [개선] 결과 중 '아파트' 카테고리가 포함된 항목을 우선 탐색
                        docs = data['documents']
                        target_doc = None
                        for d in docs:
                            if '아파트' in d.get('category_name', ''):
                                target_doc = d
                                break
                        
                        # 아파트 카테고리가 없으면 첫 번째 결과 사용
                        if not target_doc: target_doc = docs[0]
                        
                        lat, lng = float(target_doc['y']), float(target_doc['x'])
                        logger.info(f"[Kakao Geocode] Success for {query}: {lat}, {lng} ({target_doc.get('place_name')})")
            except Exception as e:
                logger.error(f"Geocoding API failed: {e}")

    # 3. 결과 캐싱 및 반환
    if lat and lng:
        try:
            cursor.execute('INSERT OR IGNORE INTO complex_coords (apt_name, dong_name, lat, lng) VALUES (?, ?, ?, ?)', (apt_name, dong_name, lat, lng))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Complex cache save error: {e}")
        return lat, lng
    
    if 'conn' in locals() and conn: conn.close()
    return None, None

def call_kakao_api(origin_lng, origin_lat, dest_lng, dest_lat, d_time):
    """카카오 모빌리티 미래 경로 탐색 API 단일 호출 유틸리티"""
    if not KAKAO_REST_API_KEY or KAKAO_REST_API_KEY.startswith('feb433'): 
        return None
    
    url = "https://apis-navi.kakaomobility.com/v1/future/directions"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY.strip()}"}
    params = {
        "origin": f"{origin_lng},{origin_lat}",
        "destination": f"{dest_lng},{dest_lat}",
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
            logger.error("[Kakao API] 401 Unauthorized: REST API Key is invalid.")
    except Exception as e:
        logger.error(f"API Call failed: {e}")
    return None

def get_kakao_commute(db_path, from_lat, from_lng, to_lat, to_lng, transport_mode='car', departure_time=None, goal_arrive_time=None):
    """
    카카오 모빌리티 API를 통해 정밀 통근 시간을 반환 (시뮬레이션 포함).
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

    # 2. 시간 설정 및 시뮬레이션
    duration, distance = 0, 0
    now = datetime.now()
    days_ahead = 0 - now.weekday()
    if days_ahead <= 0: days_ahead += 7
    target_date = (now + timedelta(days=days_ahead))

    current_hour = 0
    if goal_arrive_time:
        current_hour = int(goal_arrive_time[:2])
        goal_h, goal_m = int(goal_arrive_time[:2]), int(goal_arrive_time[2:])
        test_departure = target_date.replace(hour=goal_h, minute=goal_m) - timedelta(minutes=45)
        
        res1 = call_kakao_api(from_lng, from_lat, to_lng, to_lat, test_departure.strftime("%Y%m%d%H%M"))
        if res1:
            dur1, dist1 = res1
            actual_arrive = test_departure + timedelta(minutes=dur1)
            target_arrive = target_date.replace(hour=goal_h, minute=goal_m)
            diff_min = (actual_arrive - target_arrive).total_seconds() / 60
            if abs(diff_min) > 5:
                refined_departure = test_departure - timedelta(minutes=int(diff_min))
                res2 = call_kakao_api(from_lng, from_lat, to_lng, to_lat, refined_departure.strftime("%Y%m%d%H%M"))
                if res2: duration, distance = res2
                else: duration, distance = dur1, dist1
            else:
                duration, distance = dur1, dist1
    
    elif departure_time:
        current_hour = int(departure_time[8:10])
        res = call_kakao_api(from_lng, from_lat, to_lng, to_lat, departure_time)
        if res: duration, distance = res

    # 3. Fallback (API 실패 혹은 대중교통)
    if not duration:
        R = 6371
        import math
        dLat, dLon = math.radians(to_lat - from_lat), math.radians(to_lng - from_lng)
        a = math.sin(dLat/2)**2 + math.cos(math.radians(from_lat)) * math.cos(math.radians(to_lat)) * math.sin(dLon/2)**2
        dist = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance = dist
        speed = 25 if transport_mode == 'public' else 35
        base_duration = (dist / speed) * 60
        traffic_multiplier = 1.0
        if 7 <= current_hour <= 8: traffic_multiplier = 1.35
        elif 17 <= current_hour <= 18: traffic_multiplier = 1.20
        duration = int(base_duration * traffic_multiplier) + (15 if transport_mode == 'public' else 5)

    # 4. 결과 캐싱
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
