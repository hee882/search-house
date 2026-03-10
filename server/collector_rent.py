import os
import json
import sqlite3
import argparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import xmltodict
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "search_house.db")
REGIONS_PATH = os.path.join(os.path.dirname(__file__), "data", "region_codes.json")
API_KEY = "7c7b7f2b751248958a8bf6bba48481d621f202f946cf8028056a89b3c9feb532"  # 사용자 제공 키
API_URL = "http://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"

def get_latest_month():
    return datetime.now().strftime("%Y%m")

def parse_int(val):
    if not val:
        return 0
    try:
        return int(str(val).replace(',', '').strip())
    except:
        return 0

def fetch_and_save_rent(city_code, deal_ymd):
    session = requests.Session()
    retry = Retry(
        total=3, read=3, connect=3,
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
            response.raise_for_status()
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
                    deposit = parse_int(item.get('deposit') or item.get('보증금액'))
                    monthly_rent = parse_int(item.get('monthlyRent') or item.get('월세금액'))

                    dong = (item.get('umdNm') or item.get('법정동', '')).strip()
                    apt = (item.get('aptNm') or item.get('아파트', '')).strip()
                    area = float(item.get('excluUseAr') or item.get('전용면적', 0))
                    year = parse_int(item.get('dealYear') or item.get('년'))
                    month = parse_int(item.get('dealMonth') or item.get('월'))
                    day = parse_int(item.get('dealDay') or item.get('일'))
                    floor_val = parse_int(item.get('floor') or item.get('층'))
                    build_yr = parse_int(item.get('buildYear') or item.get('건축년도'))

                    cursor.execute('''
                        INSERT OR IGNORE INTO rent_transactions (
                            city_code, dong_name, apt_name, exclusive_area,
                            deal_year, deal_month, deal_day, deposit, monthly_rent, floor, build_year
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        city_code, dong, apt, area, year, month, day, deposit, monthly_rent, floor_val, build_yr
                    ))
                    
                    if cursor.rowcount > 0:
                        total_saved += 1
                        
                except Exception as e:
                    print(f"  - Skip: {e}")

            conn.commit()
            conn.close()

            if page_no * 1000 >= total_count:
                break
            page_no += 1

        except requests.exceptions.RequestException as e:
            print(f"Error fetching {city_code} (page {page_no}): {e}")
            break

    return total_saved


def run_collector(target_month=None):
    with open(REGIONS_PATH, "r", encoding="utf-8") as f:
        regions = json.load(f)

    if not target_month:
        target_month = get_latest_month()

    print(f"Starting Rent data collection for {target_month}...")

    total_new = 0
    # Let's limit the collection for test to save API calls
    # Or just run it.
    for province, cities in regions.items():
        print(f"Processing {province}...")
        for city_name, code in cities.items():
            try:
                new_records = fetch_and_save_rent(code, target_month)
                total_new += new_records
                print(f"  - {city_name}: {new_records} new rent records saved.")
            except Exception as e:
                print(f"  - An error occurred while processing {city_name} ({code}): {e}")

    print(f"Finished. Total {total_new} new rent records added to DB.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect rent data for a specific month.")
    parser.add_argument("--month", type=str, help="The target month in YYYYMM format. Defaults to the current month.")
    args = parser.parse_args()
    
    run_collector(target_month=args.month)
