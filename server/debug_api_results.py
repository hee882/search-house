import os
import requests
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")
KAKAO_REST_API_KEY = 'feb433e26a2ced15800280d98c464a14' # 테스트용 키 주입

def call_kakao_api(origin, destination, d_time):
    if not KAKAO_REST_API_KEY:
        return "ERROR: No API Key"
    url = "https://apis-navi.kakaomobility.com/v1/future/directions"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY.strip()}"}
    params = {
        "origin": origin,
        "destination": destination,
        "departure_time": d_time,
        "priority": "RECOMMEND"
    }
    try:
        res = requests.get(url, headers=headers, params=params, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get('routes') and data['routes'][0]['result_code'] == 0:
                route = data['routes'][0]['summary']
                return int(route['duration'] / 60)
            return f"API ERROR: {data.get('routes', [{}])[0].get('result_msg')}"
        return f"HTTP ERROR: {res.status_code}"
    except Exception as e:
        return f"EXCEPTION: {e}"

def run_debug():
    # 수원역 -> 강남역 (출퇴근 정체 구간 예시)
    suwon = "127.0002,37.2659"
    gangnam = "127.0276,37.4979"
    
    now = datetime.now()
    days_ahead = 0 - now.weekday()
    if days_ahead <= 0: days_ahead += 7
    target_date = (now + timedelta(days=days_ahead))
    
    # 1. 출근 피크 (07:30 출발)
    time_morning = target_date.replace(hour=7, minute=30, second=0).strftime("%Y%m%d%H%M")
    # 2. 퇴근 피크 (18:00 출발)
    time_evening = target_date.replace(hour=18, minute=0, second=0).strftime("%Y%m%d%H%M")
    # 3. 한가한 시간 (새벽 03:00 출발)
    time_midnight = target_date.replace(hour=3, minute=0, second=0).strftime("%Y%m%d%H%M")

    print(f"--- Kakao API Real-world Traffic Test ---")
    print(f"Route: Suwon Station <-> Gangnam Station")
    
    print(f"\n[MORNING] Suwon -> Gangnam ({time_morning}):")
    dur_m = call_kakao_api(suwon, gangnam, time_morning)
    print(f"Result: {dur_m} min")

    print(f"\n[EVENING] Gangnam -> Suwon ({time_evening}):")
    dur_e = call_kakao_api(gangnam, suwon, time_evening)
    print(f"Result: {dur_e} min")

    print(f"\n[MIDNIGHT] Suwon -> Gangnam ({time_midnight}):")
    dur_mid = call_kakao_api(suwon, gangnam, time_midnight)
    print(f"Result: {dur_mid} min")

    if isinstance(dur_m, int) and isinstance(dur_mid, int):
        print(f"\nTraffic Delta (Morning vs Midnight): {dur_m - dur_mid} min")
    
    if isinstance(dur_m, int) and isinstance(dur_e, int):
        print(f"Direction Delta (Morning vs Evening): {dur_m - dur_e} min")

if __name__ == "__main__":
    run_debug()
