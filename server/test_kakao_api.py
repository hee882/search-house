import os
import requests
from dotenv import load_dotenv

load_dotenv()

KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")

def test_future_directions():
    if not KAKAO_REST_API_KEY:
        print("❌ Error: KAKAO_REST_API_KEY not found in .env")
        return

    url = "https://apis-navi.kakaomobility.com/v1/future/directions"
    headers = {
        "Authorization": f"KakaoAK {KAKAO_REST_API_KEY.strip()}",
        "Content-Type": "application/json"
    }
    
    # 판교역 -> 카카오 (예시 좌표)
    params = {
        "origin": "127.1101,37.3947",
        "destination": "127.1082,37.4019",
        "departure_time": "202603230800", # 다음 주 월요일 08:00
        "priority": "RECOMMEND"
    }
    
    try:
        print(f"📡 Requesting Kakao Future Directions...")
        res = requests.get(url, headers=headers, params=params)
        print(f"Status Code: {res.status_code}")
        data = res.json()
        
        if res.status_code == 200:
            if 'routes' in data and data['routes'][0]['result_code'] == 0:
                duration = data['routes'][0]['summary']['duration'] / 60
                print(f"✅ Success! Duration: {duration:.1f} min")
            else:
                print(f"❌ API Result Error: {data}")
        else:
            print(f"❌ HTTP Error: {data}")
            
    except Exception as e:
        print(f"💥 Exception: {e}")

if __name__ == "__main__":
    test_future_directions()
