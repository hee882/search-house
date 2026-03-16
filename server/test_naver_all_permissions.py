import os
import requests
from dotenv import load_dotenv

load_dotenv()

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

def test_api(name, url, params):
    headers = {
        "X-NCP-APIGW-API-KEY-ID": NAVER_CLIENT_ID,
        "X-NCP-APIGW-API-KEY": NAVER_CLIENT_SECRET
    }
    print(f"Testing [{name}]...")
    try:
        res = requests.get(url, headers=headers, params=params, timeout=5)
        if res.status_code == 200:
            print(f"  ✅ SUCCESS: 200 OK")
        else:
            data = res.json()
            error_code = data.get('error', {}).get('errorCode') or data.get('code')
            message = data.get('error', {}).get('message') or data.get('message')
            print(f"  ❌ FAILED: {res.status_code} ({error_code}) - {message}")
    except Exception as e:
        print(f"  ⚠️ ERROR: {e}")

if __name__ == "__main__":
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        print("API Keys missing in .env")
        exit(1)

    print(f"--- Naver API Permission Audit (Client ID: {NAVER_CLIENT_ID[:5]}...) ---\n")
    
    # 1. Geocoding (주소 -> 좌표)
    test_api("Geocoding", 
             "https://naveropenapi.apigw.ntruss.com/map-geocoding/v2/geocode", 
             {"query": "분당구 불정로 6"})

    # 2. Reverse Geocoding (좌표 -> 주소)
    test_api("Reverse Geocoding", 
             "https://naveropenapi.apigw.ntruss.com/map-reversegeocoding/v2/gc", 
             {"coords": "127.1054328,37.3595953", "output": "json"})

    # 3. Static Map (지도 이미지)
    test_api("Static Map", 
             "https://naveropenapi.apigw.ntruss.com/map-static/v2/raster", 
             {"w": "300", "h": "300", "center": "127.1054328,37.3595953", "level": "16"})

    # 4. Directions 5 (길찾기)
    test_api("Directions 5", 
             "https://naveropenapi.apigw.ntruss.com/map-direction/v1/driving", 
             {"start": "127.1058,37.3595", "goal": "127.1097,37.3675", "option": "trafast"})
