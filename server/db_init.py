import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "search_house.db")

def init_db():
    """데이터베이스 및 테이블 초기화"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. 아파트 매매 실거래가 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city_code TEXT,
            dong_name TEXT,
            apt_name TEXT,
            exclusive_area REAL,
            deal_amount INTEGER,
            deal_year INTEGER,
            deal_month INTEGER,
            deal_day INTEGER,
            floor INTEGER,
            build_year INTEGER,
            is_direct_deal TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(city_code, apt_name, dong_name, deal_year, deal_month, deal_day, deal_amount, floor)
        )
    ''')
    
    # 2. 지역별 통계 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS region_stats (
            region_name TEXT PRIMARY KEY,
            median_price INTEGER,
            avg_price INTEGER,
            last_updated DATETIME
        )
    ''')

    # 3. 전월세 거래 테이블
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

    # 4. 통근 시간 캐시 테이블 (Naver API 비용 절감용)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS commute_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_lat REAL,
            from_lng REAL,
            to_lat REAL,
            to_lng REAL,
            transport_mode TEXT,
            duration_min INTEGER,
            distance_km REAL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(from_lat, from_lng, to_lat, to_lng, transport_mode)
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"Database initialized successfully at: {DB_PATH}")

if __name__ == "__main__":
    init_db()
