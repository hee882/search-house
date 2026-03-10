import os
import json
import sqlite3
import argparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import xmltodict
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "search_house.db")
REGIONS_PATH = os.path.join(os.path.dirname(__file__), "data", "region_codes.json")
API_KEY = os.getenv("DATA_API_KEY")
API_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"

def get_latest_month():
    return datetime.now().strftime("%Y%m")

def init_db():
    """Initializes the database and creates the transactions table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Create table with a UNIQUE constraint to prevent duplicate entries
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city_code TEXT NOT NULL,
            dong_name TEXT NOT NULL,
            apt_name TEXT NOT NULL,
            exclusive_area REAL NOT NULL,
            deal_amount INTEGER NOT NULL,
            deal_year INTEGER NOT NULL,
            deal_month INTEGER NOT NULL,
            deal_day INTEGER NOT NULL,
            floor INTEGER NOT NULL,
            build_year INTEGER,
            is_direct_deal TEXT,
            cancel_deal_day TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(dong_name, apt_name, exclusive_area, deal_year, deal_month, deal_day, floor)
        )
    ''')
    conn.commit()
    conn.close()

def fetch_and_save(city_code, deal_ymd):
    session = requests.Session()
    retry = Retry(
        total=3,
        read=3,
        connect=3,
        backoff_factor=0.3,
        status_forcelist=(500, 502, 503, 504),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    
    page_no = 1
    total_saved = 0
    
    while True:
        params = {
            'serviceKey': API_KEY,
            'LAWD_CD': city_code,
            'DEAL_YMD': deal_ymd,
            'numOfRows': 1000,
            'pageNo': page_no
        }
        
        try:
            response = session.get(API_URL, params=params, timeout=10)
            response.raise_for_status()  # 200 OK가 아니면 예외 발생
            data = xmltodict.parse(response.text)
            
            body = data.get('response', {}).get('body', {})
            if not body:
                break
                
            total_count = int(body.get('totalCount', 0))
            items = body.get('items', {})
            if not items:
                break
                
            item_list = items.get('item', [])
            if isinstance(item_list, dict):
                item_list = [item_list]
            
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            for item in item_list:
                try:
                    # API 응답: 한글 필드명 또는 영문 필드명 모두 지원
                    amount_str = item.get('dealAmount') or item.get('거래금액', '0')
                    amount = int(str(amount_str).replace(',', '').strip())

                    dong = (item.get('umdNm') or item.get('법정동', '')).strip()
                    apt = (item.get('aptNm') or item.get('아파트', '')).strip()
                    area = float(item.get('excluUseAr') or item.get('전용면적', 0))
                    year = int(item.get('dealYear') or item.get('년', 0))
                    month = int(item.get('dealMonth') or item.get('월', 0))
                    day = int(item.get('dealDay') or item.get('일', 0))
                    floor_val = int(item.get('floor') or item.get('층', 0) or 0)
                    build_yr = int(item.get('buildYear') or item.get('건축년도', 0) or 0)
                    deal_type = (item.get('dealingGbn') or item.get('거래유형', '')).strip()
                    cancel_day = (item.get('cdealDay') or item.get('해제사유발생일') or '')
                    if cancel_day:
                        cancel_day = str(cancel_day).strip()

                    cursor.execute('''
                        INSERT INTO transactions (
                            city_code, dong_name, apt_name, exclusive_area,
                            deal_amount, deal_year, deal_month, deal_day,
                            floor, build_year, is_direct_deal, cancel_deal_day
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(dong_name, apt_name, exclusive_area, deal_year, deal_month, deal_day, floor)
                        DO UPDATE SET
                            deal_amount = excluded.deal_amount,
                            is_direct_deal = excluded.is_direct_deal,
                            cancel_deal_day = excluded.cancel_deal_day
                    ''', (
                        city_code, dong, apt, area,
                        amount, year, month, day,
                        floor_val, build_yr, deal_type, cancel_day
                    ))
                    if cursor.rowcount > 0:
                        total_saved += 1
                except Exception as e:
                    print(f"  - Skip: {e}")
                    
            conn.commit()
            conn.close()
            
            # Check if we need to fetch the next page
            if page_no * 1000 >= total_count:
                break
            page_no += 1
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching {city_code} (page {page_no}): {e}")
            break
            
    return total_saved

def run_collector(target_month=None):
    if not API_KEY:
        print("Error: DATA_API_KEY not found in environment.")
        return

    # Ensure the database and table are set up correctly
    init_db()

    with open(REGIONS_PATH, "r", encoding="utf-8") as f:
        regions = json.load(f)
    
    # If target_month is not provided via argument, use the current month
    if not target_month:
        target_month = get_latest_month()

    print(f"Starting data collection for {target_month}...")
    
    total_new = 0
    for province, cities in regions.items():
        print(f"Processing {province}...")
        for city_name, code in cities.items():
            try:
                new_records = fetch_and_save(code, target_month)
                total_new += new_records
                print(f"  - {city_name}: {new_records} new records saved.")
            except Exception as e:
                print(f"  - An error occurred while processing {city_name} ({code}): {e}")
            
    print(f"Finished. Total {total_new} new records added to DB.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect real estate transaction data for a specific month.")
    parser.add_argument("--month", type=str, help="The target month in YYYYMM format. Defaults to the current month.")
    args = parser.parse_args()
    
    run_collector(target_month=args.month)
