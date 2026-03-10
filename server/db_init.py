import sqlite3
import os

DB_PATH = "D:/workspace/search-house/server/data/search_house.db"

def init_db():
    """데이터베이스 및 테이블 초기화"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 실거래가 저장 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city_code TEXT,          -- 법정동 시군구 코드 (5자리)
            dong_name TEXT,          -- 법정동명
            apt_name TEXT,           -- 아파트명
            exclusive_area REAL,     -- 전용면적
            deal_amount INTEGER,     -- 거래금액 (만원)
            deal_year INTEGER,
            deal_month INTEGER,
            deal_day INTEGER,
            floor INTEGER,
            build_year INTEGER,
            is_direct_deal TEXT,     -- 직거래 여부
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 지역별 통계 테이블 (미리 계산해서 저장)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS region_stats (
            region_name TEXT PRIMARY KEY,
            median_price INTEGER,
            avg_price INTEGER,
            last_updated DATETIME
        )
    ''')
    
    # 전월세 실거래가 저장 테이블
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
    
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

if __name__ == "__main__":
    init_db()
