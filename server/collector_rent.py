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
API_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"

def get_latest_month():
    return datetime.now().strftime("%Y%m")

# 국토부 API가 내려주지만 초기 스키마에 없던 컬럼들.
# 갱신계약은 2년 전 시세 기반이라 신규계약과 섞으면 대표 시세가 실제보다 낮아진다.
EXTRA_COLUMNS = {
    "apt_seq": "TEXT",           # 단지 고유 일련번호 (동명 단지 구분)
    "jibun": "TEXT",
    "road_name": "TEXT",
    "contract_type": "TEXT",     # 신규 / 갱신
    "use_rr_right": "TEXT",      # 갱신요구권 사용 여부
    "contract_term": "TEXT",
    "pre_deposit": "INTEGER",    # 종전 계약 보증금
    "pre_monthly_rent": "INTEGER",
}

def ensure_table():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rent_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city_code TEXT,
            dong_name TEXT,
            apt_name TEXT,
            exclusive_area REAL,
            deal_year INTEGER,
            deal_month INTEGER,
            deal_day INTEGER,
            deposit INTEGER,
            monthly_rent INTEGER,
            floor INTEGER,
            build_year INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(city_code, apt_name, dong_name, deal_year, deal_month, deal_day, deposit, monthly_rent, floor)
        )
    ''')
    existing = {row[1] for row in cursor.execute("PRAGMA table_info(rent_transactions)")}
    for column, column_type in EXTRA_COLUMNS.items():
        if column not in existing:
            cursor.execute(f"ALTER TABLE rent_transactions ADD COLUMN {column} {column_type}")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_rent_city ON rent_transactions(city_code, deal_year, deal_month)")
    conn.commit()
    conn.close()

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

                    def text_of(*keys):
                        for key in keys:
                            value = item.get(key)
                            if value:
                                return str(value).strip()
                        return None

                    # 이미 저장된 거래도 계약구분 등 신규 컬럼을 채워야 하므로 UPSERT를 사용한다.
                    cursor.execute('''
                        INSERT INTO rent_transactions (
                            city_code, dong_name, apt_name, exclusive_area,
                            deal_year, deal_month, deal_day, deposit, monthly_rent, floor, build_year,
                            apt_seq, jibun, road_name, contract_type, use_rr_right, contract_term,
                            pre_deposit, pre_monthly_rent
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(city_code, apt_name, dong_name, deal_year, deal_month, deal_day,
                                    deposit, monthly_rent, floor)
                        DO UPDATE SET
                            apt_seq = COALESCE(excluded.apt_seq, apt_seq),
                            jibun = COALESCE(excluded.jibun, jibun),
                            road_name = COALESCE(excluded.road_name, road_name),
                            contract_type = COALESCE(excluded.contract_type, contract_type),
                            use_rr_right = COALESCE(excluded.use_rr_right, use_rr_right),
                            contract_term = COALESCE(excluded.contract_term, contract_term),
                            pre_deposit = COALESCE(excluded.pre_deposit, pre_deposit),
                            pre_monthly_rent = COALESCE(excluded.pre_monthly_rent, pre_monthly_rent)
                    ''', (
                        city_code, dong, apt, area, year, month, day, deposit, monthly_rent, floor_val, build_yr,
                        text_of('aptSeq'), text_of('jibun', '지번'), text_of('roadnm', '도로명'),
                        text_of('contractType', '계약구분'), text_of('useRRRight', '갱신요구권사용'),
                        text_of('contractTerm', '계약기간'),
                        parse_int(item.get('preDeposit') or item.get('종전계약보증금')),
                        parse_int(item.get('preMonthlyRent') or item.get('종전계약월세')),
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


def recent_months(count):
    """현재월부터 과거로 count개월치 YYYYMM 목록"""
    now = datetime.now()
    months = []
    year, month = now.year, now.month
    for _ in range(max(1, count)):
        months.append(f"{year}{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return months


def run_collector(target_month=None, months=3):
    if not API_KEY:
        print("Error: DATA_API_KEY not found in environment.")
        return

    ensure_table()

    with open(REGIONS_PATH, "r", encoding="utf-8") as f:
        regions = json.load(f)

    # 전월세 신고도 계약 후 30일까지 들어오므로 당월만 받으면 후반 신고분을 놓친다.
    target_months = [target_month] if target_month else recent_months(months)

    print(f"Starting Rent data collection for {', '.join(target_months)}...")

    grand_total = 0
    for deal_ymd in target_months:
        total_new = 0
        for province, cities in regions.items():
            print(f"[{deal_ymd}] Processing {province}...")
            for city_name, code in cities.items():
                try:
                    new_records = fetch_and_save_rent(code, deal_ymd)
                    total_new += new_records
                    print(f"  - {city_name}: {new_records} rent records saved/updated.")
                except Exception as e:
                    print(f"  - An error occurred while processing {city_name} ({code}): {e}")
        print(f"[{deal_ymd}] {total_new} rent records saved/updated.")
        grand_total += total_new

    print(f"Finished. Total {grand_total} rent records saved/updated in DB.")

    # WAL 모드에서는 변경분이 -wal 파일에 남을 수 있다.
    # CI가 커밋하는 것은 DB 본체뿐이므로 종료 전에 합쳐준다.
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    except Exception as e:
        print(f"WAL checkpoint failed: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect rent transaction data.")
    parser.add_argument("--month", type=str, help="The target month in YYYYMM format. Defaults to recent months.")
    parser.add_argument("--months", type=int, default=3,
                        help="How many recent months to re-collect when --month is omitted (default 3).")
    args = parser.parse_args()

    run_collector(target_month=args.month, months=args.months)
