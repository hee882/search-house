import os
import requests
import json
import sqlite3
from datetime import datetime
from dotenv import load_dotenv

# Load .env
load_dotenv()

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

def get_precise_commute(db_path, from_lat, from_lng, to_lat, to_lng, transport_mode='public'):
    """
    네이버 API를 통해 정밀 통근 시간(분)과 거리(km)를 반환.
    캐시 우선 조회 로직 포함.
    """
    # 1. 캐시 확인
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        f_lat, f_lng = round(from_lat, 4), round(from_lng, 4)
        t_lat, t_lng = round(to_lat, 4), round(to_lng, 4)
        
        cursor.execute('''
            SELECT duration_min, distance_km FROM commute_cache
            WHERE from_lat = ? AND from_lng = ? AND to_lat = ? AND to_lng = ? AND transport_mode = ?
        ''', (f_lat, f_lng, t_lat, t_lng, transport_mode))
        cache = cursor.fetchone()
        if cache:
            conn.close()
            return cache[0], cache[1]
    except Exception as e:
        print(f"Cache lookup error: {e}")

    # 2. 캐시 없으면 API 호출 (자차: Naver Directions 5)
    duration, distance = 0, 0
    
    if transport_mode == 'car':
        if NAVER_CLIENT_ID and NAVER_CLIENT_SECRET:
            url = "https://naveropenapi.apigw.ntruss.com/map-direction/v1/driving"
            headers = {
                "X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
                "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET
            }
            
            # 현실적인 통근 시간 시뮬레이션 (출근 07:30 출발 기준)
            # 네이버 API 형식: YYYY-MM-DDTHH:mm:ss
            now = datetime.now()
            departure_time = now.replace(hour=7, minute=30, second=0, microsecond=0).isoformat()
            
            params = {
                "start": f"{from_lng},{from_lat}",
                "goal": f"{to_lng},{to_lat}",
                "option": "trafast",
                "departure_time": departure_time # 실시간 교통정보 반영
            }
            try:
                res = requests.get(url, headers=headers, params=params, timeout=3)
                data = res.json()
                if data.get('code') == 0:
                    duration = int(data['route']['trafast'][0]['summary']['duration'] / 60000)
                    distance = data['route']['trafast'][0]['summary']['distance'] / 1000 # km
            except Exception as e:
                print(f"Naver API error: {e}")
    
    # 3. 대중교통 (현재는 직선거리 보정치 사용, 향후 ODsay 등 연동)
    if not duration:
        # Fallback logic
        R = 6371
        import math
        dLat = math.radians(to_lat - from_lat)
        dLon = math.radians(to_lng - from_lng)
        a = math.sin(dLat/2)**2 + math.cos(math.radians(from_lat)) * math.cos(math.radians(to_lat)) * math.sin(dLon/2)**2
        dist = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance = dist
        speed = 20 if transport_mode == 'public' else 30
        duration = int((dist / speed) * 60) + (15 if transport_mode == 'public' else 5)

    # 4. 결과 캐싱
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO commute_cache 
            (from_lat, from_lng, to_lat, to_lng, transport_mode, duration_min, distance_km)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (f_lat, f_lng, t_lat, t_lng, transport_mode, duration, distance))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Cache save error: {e}")

    return duration, distance
