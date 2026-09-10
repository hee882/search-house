"""법정동 좌표 사전(dong_coordinates.json) 생성·보강 스크립트.

/api/optimize는 단지의 대략 위치를 법정동 좌표로 잡은 뒤 카카오 키워드 검색으로
정밀 보정한다. 따라서 법정동 좌표가 비어 있으면 후보 선별과 통근 시간 추정이
구 단위로 뭉개진다. 이 스크립트는 실거래 DB에 실제로 등장하는 (구, 동) 조합을
모아 카카오 로컬 주소검색 API로 좌표를 채운다.

사용법:
    KAKAO_REST_API_KEY=... python server/build_dong_coords.py            # 없는 항목만 보강
    python server/build_dong_coords.py --since-year 2024 --limit 200     # 부분 실행
    python server/build_dong_coords.py --force                           # 기존 값도 갱신
"""

import argparse
import json
import os
import sqlite3
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "search_house.db")
DONG_PATH = os.path.join(BASE_DIR, "data", "dong_coordinates.json")
REGIONS_PATH = os.path.join(BASE_DIR, "data", "region_codes.json")
API_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")


def load_region_names():
    """city_code -> (시/도, 구/시) 이름 매핑"""
    with open(REGIONS_PATH, "r", encoding="utf-8") as f:
        regions = json.load(f)
    mapping = {}
    for province, districts in regions.items():
        for district, code in districts.items():
            mapping[str(code)] = (province, district)
    return mapping


def collect_dong_pairs(since_year):
    """실거래 DB에 등장하는 (city_code, dong_name) 조합 수집"""
    if not os.path.exists(DB_PATH):
        raise SystemExit(f"DB를 찾을 수 없습니다: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    pairs = set()
    for table in ("rent_transactions", "transactions"):
        try:
            rows = conn.execute(
                f"SELECT DISTINCT city_code, dong_name FROM {table} WHERE deal_year >= ?",
                (since_year,),
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        for city_code, dong_name in rows:
            if city_code and dong_name:
                pairs.add((str(city_code), dong_name.strip()))
    conn.close()
    return sorted(pairs)


def geocode(query, session):
    res = session.get(
        API_URL,
        headers={"Authorization": f"KakaoAK {KAKAO_REST_API_KEY.strip()}"},
        params={"query": query, "size": 1},
        timeout=5,
    )
    if res.status_code == 401:
        raise SystemExit("KAKAO_REST_API_KEY 인증 실패: REST API 키가 맞는지 확인하세요.")
    if res.status_code != 200:
        return None
    documents = res.json().get("documents") or []
    if not documents:
        return None
    doc = documents[0]
    return round(float(doc["y"]), 6), round(float(doc["x"]), 6)


def main():
    parser = argparse.ArgumentParser(description="법정동 좌표 사전 생성/보강")
    parser.add_argument("--since-year", type=int, default=2024, help="수집 기준 연도 (기본 2024)")
    parser.add_argument("--limit", type=int, default=0, help="이번 실행에서 조회할 최대 건수 (0=제한 없음)")
    parser.add_argument("--force", action="store_true", help="이미 좌표가 있는 항목도 다시 조회")
    parser.add_argument("--sleep", type=float, default=0.1, help="호출 간 대기 초 (기본 0.1)")
    args = parser.parse_args()

    if not KAKAO_REST_API_KEY:
        raise SystemExit(
            "KAKAO_REST_API_KEY가 설정되지 않았습니다. server/.env에 REST API 키를 추가한 뒤 다시 실행하세요."
        )

    region_names = load_region_names()
    coords = {}
    if os.path.exists(DONG_PATH):
        with open(DONG_PATH, "r", encoding="utf-8") as f:
            coords = json.load(f)

    pairs = collect_dong_pairs(args.since_year)
    targets = [
        (code, dong) for code, dong in pairs
        if args.force or f"{code}_{dong}" not in coords
    ]
    if args.limit:
        targets = targets[: args.limit]

    print(f"전체 {len(pairs)}개 조합 / 이번 조회 대상 {len(targets)}개 (기존 {len(coords)}개 보유)")

    session = requests.Session()
    added, failed = 0, []
    for index, (code, dong) in enumerate(targets, start=1):
        province, district = region_names.get(code, ("", ""))
        query = " ".join(part for part in (province, district, dong) if part)
        try:
            result = geocode(query, session)
        except SystemExit:
            raise
        except Exception as exc:  # 네트워크 오류는 건너뛰고 계속
            print(f"  - {query}: 조회 실패 ({exc})")
            failed.append(query)
            result = None

        if result:
            coords[f"{code}_{dong}"] = {"lat": result[0], "lng": result[1]}
            added += 1
        else:
            failed.append(query)

        if index % 50 == 0:
            print(f"  ... {index}/{len(targets)} 진행 (성공 {added})")
        time.sleep(args.sleep)

    with open(DONG_PATH, "w", encoding="utf-8") as f:
        json.dump(coords, f, ensure_ascii=False, indent=1, sort_keys=True)

    print(f"완료: {added}개 추가/갱신, 실패 {len(failed)}개, 최종 {len(coords)}개")
    if failed:
        print("실패 목록(최대 20개):", ", ".join(failed[:20]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
