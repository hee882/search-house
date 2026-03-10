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

NEW_SCHEMA_COLUMNS = [
    "id INTEGER PRIMARY KEY AUTOINCREMENT",
    "city_code TEXT NOT NULL",
    "dong_name TEXT NOT NULL",
    "dong_code TEXT",
    "apt_name TEXT NOT NULL",
    "apt_seq TEXT",
    "apt_dong TEXT",
    "exclusive_area REAL NOT NULL",
    "deal_amount INTEGER NOT NULL",
    "deal_year INTEGER NOT NULL",
    "deal_month INTEGER NOT NULL",
    "deal_day INTEGER NOT NULL",
    "floor INTEGER NOT NULL",
    "build_year INTEGER",
    "jibun TEXT",
    "road_name TEXT",
    "buyer_type TEXT",
    "seller_type TEXT",
    "is_direct_deal TEXT",
    "cancel_deal_day TEXT",
    "cancel_deal_type TEXT",
    "rgst_date TEXT",
    "is_new_high_price INTEGER DEFAULT 0",
    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
]

UNIQUE_CONSTRAINT = "UNIQUE(city_code, apt_seq, exclusive_area, deal_year, deal_month, deal_day, floor)"
UNIQUE_FALLBACK = "UNIQUE(city_code, dong_name, apt_name, exclusive_area, deal_year, deal_month, deal_day, floor)"


def get_latest_month():
    return datetime.now().strftime("%Y%m")


def _has_column(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'")
    table_exists = cursor.fetchone() is not None

    if table_exists and not _has_column(cursor, 'transactions', 'apt_seq'):
        print("Migrating DB schema to v2...")
        _migrate_v1_to_v2(conn)
    elif not table_exists:
        _create_new_table(cursor)
        conn.commit()

    _ensure_indexes(cursor)
    conn.commit()
    conn.close()


def _create_new_table(cursor):
    cols = ",\n            ".join(NEW_SCHEMA_COLUMNS)
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS transactions (
            {cols},
            {UNIQUE_FALLBACK}
        )
    ''')


def _migrate_v1_to_v2(conn):
    cursor = conn.cursor()

    cols = ",\n            ".join(NEW_SCHEMA_COLUMNS)
    cursor.execute(f'''
        CREATE TABLE transactions_v2 (
            {cols},
            {UNIQUE_FALLBACK}
        )
    ''')

    cursor.execute('''
        INSERT INTO transactions_v2 (
            city_code, dong_name, apt_name, exclusive_area,
            deal_amount, deal_year, deal_month, deal_day,
            floor, build_year, is_direct_deal, cancel_deal_day, created_at
        )
        SELECT
            city_code, dong_name, apt_name, exclusive_area,
            deal_amount, deal_year, deal_month, deal_day,
            floor, build_year, is_direct_deal, cancel_deal_day, created_at
        FROM transactions
    ''')

    cursor.execute("ALTER TABLE transactions RENAME TO transactions_backup")
    cursor.execute("ALTER TABLE transactions_v2 RENAME TO transactions")

    _backfill_new_high_prices(cursor)
    conn.commit()
    print("Migration complete. Old data preserved in 'transactions_backup'.")


def _ensure_indexes(cursor):
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stats ON transactions(city_code, deal_year, deal_month)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_new_high ON transactions(apt_seq, exclusive_area, deal_amount)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dong ON transactions(city_code, dong_code, deal_year, deal_month)")


def _backfill_new_high_prices(cursor):
    cursor.execute('''
        UPDATE transactions SET is_new_high_price = 1
        WHERE id IN (
            SELECT t1.id FROM transactions t1
            WHERE t1.cancel_deal_day IS NULL OR t1.cancel_deal_day = ''
            AND t1.deal_amount = (
                SELECT MAX(t2.deal_amount) FROM transactions t2
                WHERE t2.apt_name = t1.apt_name
                AND t2.dong_name = t1.dong_name
                AND t2.exclusive_area = t1.exclusive_area
                AND (t2.cancel_deal_day IS NULL OR t2.cancel_deal_day = '')
            )
            AND t1.deal_amount > (
                SELECT COALESCE(MAX(t3.deal_amount), 0) FROM transactions t3
                WHERE t3.apt_name = t1.apt_name
                AND t3.dong_name = t1.dong_name
                AND t3.exclusive_area = t1.exclusive_area
                AND (t3.cancel_deal_day IS NULL OR t3.cancel_deal_day = '')
                AND (t3.deal_year < t1.deal_year
                     OR (t3.deal_year = t1.deal_year AND t3.deal_month < t1.deal_month)
                     OR (t3.deal_year = t1.deal_year AND t3.deal_month = t1.deal_month AND t3.deal_day < t1.deal_day))
            )
        )
    ''')
    count = cursor.rowcount
    print(f"  Backfilled {count} new-high-price records.")


def check_new_high(cursor, apt_seq, apt_name, dong_name, exclusive_area, deal_amount):
    if apt_seq:
        cursor.execute('''
            SELECT MAX(deal_amount) FROM transactions
            WHERE apt_seq = ? AND exclusive_area = ?
            AND (cancel_deal_day IS NULL OR cancel_deal_day = '')
        ''', (apt_seq, exclusive_area))
    else:
        cursor.execute('''
            SELECT MAX(deal_amount) FROM transactions
            WHERE apt_name = ? AND dong_name = ? AND exclusive_area = ?
            AND (cancel_deal_day IS NULL OR cancel_deal_day = '')
        ''', (apt_name, dong_name, exclusive_area))
    row = cursor.fetchone()
    max_price = row[0] if row and row[0] else 0
    return 1 if deal_amount > max_price else 0


def fetch_and_save(city_code, deal_ymd):
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
                    cancel_day = str(item.get('cdealDay') or item.get('해제사유발생일') or '').strip()

                    apt_seq = str(item.get('aptSeq') or '').strip() or None
                    apt_dong_val = str(item.get('aptDong') or '').strip() or None
                    dong_code = str(item.get('umdCd') or '').strip() or None
                    jibun = str(item.get('jibun') or '').strip() or None
                    road_name = str(item.get('roadNm') or '').strip() or None
                    buyer_type = str(item.get('buyerGbn') or '').strip() or None
                    seller_type = str(item.get('slerGbn') or '').strip() or None
                    cancel_type = str(item.get('cdealType') or '').strip() or None
                    rgst_date = str(item.get('rgstDate') or '').strip() or None

                    is_new_high = check_new_high(cursor, apt_seq, apt, dong, area, amount)

                    cursor.execute('''
                        INSERT INTO transactions (
                            city_code, dong_name, dong_code, apt_name, apt_seq, apt_dong,
                            exclusive_area, deal_amount, deal_year, deal_month, deal_day,
                            floor, build_year, jibun, road_name,
                            buyer_type, seller_type, is_direct_deal,
                            cancel_deal_day, cancel_deal_type, rgst_date,
                            is_new_high_price
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT DO UPDATE SET
                            deal_amount = excluded.deal_amount,
                            apt_seq = COALESCE(excluded.apt_seq, apt_seq),
                            apt_dong = COALESCE(excluded.apt_dong, apt_dong),
                            dong_code = COALESCE(excluded.dong_code, dong_code),
                            jibun = COALESCE(excluded.jibun, jibun),
                            road_name = COALESCE(excluded.road_name, road_name),
                            buyer_type = COALESCE(excluded.buyer_type, buyer_type),
                            seller_type = COALESCE(excluded.seller_type, seller_type),
                            is_direct_deal = excluded.is_direct_deal,
                            cancel_deal_day = excluded.cancel_deal_day,
                            cancel_deal_type = excluded.cancel_deal_type,
                            rgst_date = COALESCE(excluded.rgst_date, rgst_date),
                            is_new_high_price = excluded.is_new_high_price
                    ''', (
                        city_code, dong, dong_code, apt, apt_seq, apt_dong_val,
                        area, amount, year, month, day,
                        floor_val, build_yr, jibun, road_name,
                        buyer_type, seller_type, deal_type,
                        cancel_day if cancel_day else None, cancel_type, rgst_date,
                        is_new_high
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
    if not API_KEY:
        print("Error: DATA_API_KEY not found in environment.")
        return

    init_db()

    with open(REGIONS_PATH, "r", encoding="utf-8") as f:
        regions = json.load(f)

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
