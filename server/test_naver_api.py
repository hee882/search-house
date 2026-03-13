import os
from lib.naver_api import get_precise_commute
from dotenv import load_dotenv

# .env 로드
load_dotenv()

def test_naver_direction():
    # 완전히 새로운 좌표 (삼성역 ↔ 수서역)
    from_lat, from_lng = 37.5088, 127.0631
    to_lat, to_lng = 37.4872, 127.1014
    db_path = "data/search_house.db"
    
    print("--- Naver Direction API Test (Car Mode) ---")
    try:
        duration, distance = get_precise_commute(
            db_path, from_lat, from_lng, to_lat, to_lng, transport_mode='car'
        )
        print(f"Success!")
        print(f"Duration: {duration} mins")
        print(f"Distance: {distance:.2f} km")
        
        if duration == 0:
            print("Warning: API returned 0. Please check API Key or Quota.")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_naver_direction()
