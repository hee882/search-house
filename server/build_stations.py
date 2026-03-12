"""
수도권 전체 지하철역 데이터 빌드 스크립트 (1회성)
GitHub stripe2933/SeoulMetropolitanSubway parquet → stations.json

v1 — 2026-03-11: 초기 생성 (620개역, 22개 노선)
"""
import pandas as pd
import io
import json
import math
import urllib.request
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- 데이터 소스 URL ---
STATION_URL = "https://raw.githubusercontent.com/stripe2933/SeoulMetropolitanSubway/main/data/output/station_id_table.parquet"
LINE_URL = "https://raw.githubusercontent.com/stripe2933/SeoulMetropolitanSubway/main/data/output/line_no_table.parquet"

# --- 수도권 66개 시군구 대표 좌표 (centroid) + city_code ---
REGION_CENTROIDS = {
    # 서울 25구
    "11110": (37.5735, 126.9790),  # 종로구
    "11140": (37.5641, 126.9979),  # 중구
    "11170": (37.5326, 126.9910),  # 용산구
    "11200": (37.5634, 127.0369),  # 성동구
    "11215": (37.5385, 127.0823),  # 광진구
    "11230": (37.5744, 127.0396),  # 동대문구
    "11260": (37.6066, 127.0928),  # 중랑구
    "11290": (37.5894, 127.0167),  # 성북구
    "11305": (37.6397, 127.0255),  # 강북구
    "11320": (37.6688, 127.0472),  # 도봉구
    "11350": (37.6542, 127.0568),  # 노원구
    "11380": (37.6027, 126.9291),  # 은평구
    "11410": (37.5791, 126.9368),  # 서대문구
    "11440": (37.5663, 126.9014),  # 마포구
    "11470": (37.5171, 126.8664),  # 양천구
    "11500": (37.5510, 126.8495),  # 강서구
    "11530": (37.4954, 126.8874),  # 구로구
    "11545": (37.4569, 126.8955),  # 금천구
    "11560": (37.5264, 126.8963),  # 영등포구
    "11590": (37.5124, 126.9393),  # 동작구
    "11620": (37.4784, 126.9516),  # 관악구
    "11650": (37.4837, 127.0324),  # 서초구
    "11680": (37.5173, 127.0473),  # 강남구
    "11710": (37.5145, 127.1060),  # 송파구
    "11740": (37.5301, 127.1238),  # 강동구
    # 인천 10구군
    "28110": (37.4738, 126.6217),  # 중구
    "28140": (37.4737, 126.6432),  # 동구
    "28177": (37.4425, 126.6502),  # 미추홀구
    "28185": (37.4101, 126.6783),  # 연수구
    "28200": (37.4488, 126.7309),  # 남동구
    "28237": (37.5067, 126.7218),  # 부평구
    "28245": (37.5372, 126.7375),  # 계양구
    "28260": (37.5449, 126.6760),  # 서구
    "28710": (37.7469, 126.4878),  # 강화군
    "28720": (37.4464, 126.6367),  # 옹진군
    # 경기 31시군
    "41110": (37.2636, 127.0286),  # 수원시
    "41130": (37.4200, 127.1267),  # 성남시
    "41150": (37.7381, 127.0337),  # 의정부시
    "41170": (37.3943, 126.9568),  # 안양시
    "41190": (37.5034, 126.7660),  # 부천시
    "41210": (37.4784, 126.8644),  # 광명시
    "41220": (36.9922, 127.1130),  # 평택시
    "41250": (37.9034, 127.0607),  # 동두천시
    "41270": (37.3219, 126.8309),  # 안산시
    "41280": (37.6584, 126.8320),  # 고양시
    "41290": (37.4292, 126.9876),  # 과천시
    "41310": (37.5943, 127.1295),  # 구리시
    "41360": (37.6360, 127.2148),  # 남양주시
    "41370": (37.1498, 127.0774),  # 오산시
    "41390": (37.3800, 126.8029),  # 시흥시
    "41410": (37.3617, 126.9352),  # 군포시
    "41430": (37.3448, 126.9682),  # 의왕시
    "41450": (37.5393, 127.2148),  # 하남시
    "41460": (37.2411, 127.1775),  # 용인시
    "41480": (37.7599, 126.7801),  # 파주시
    "41500": (37.2796, 127.4425),  # 이천시
    "41550": (37.0080, 127.2797),  # 안성시
    "41570": (37.6152, 126.7156),  # 김포시
    "41590": (37.1995, 127.0964),  # 화성시
    "41610": (37.4294, 127.2551),  # 광주시
    "41630": (37.7853, 127.0458),  # 양주시
    "41650": (37.8947, 127.2002),  # 포천시
    "41670": (37.2983, 127.6367),  # 여주시
    "41800": (38.0964, 127.0748),  # 연천군
    "41820": (37.8313, 127.5098),  # 가평군
    "41830": (37.4917, 127.4878),  # 양평군
}

# --- 주요 거점역 (stations.json 상단 배치) ---
FEATURED_STATIONS = [
    "강남", "여의도", "판교", "서울", "잠실",
    "홍대입구", "사당", "가산디지털단지", "광화문", "성수",
]


def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = math.sin(dLat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dLon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_city_code(lat, lng):
    """좌표에서 가장 가까운 시군구 city_code 반환"""
    best_code = ""
    best_dist = float("inf")
    for code, (clat, clng) in REGION_CENTROIDS.items():
        d = haversine(lat, lng, clat, clng)
        if d < best_dist:
            best_dist = d
            best_code = code
    return best_code


def download_parquet(url):
    print(f"  다운로드: {url.split('/')[-1]}")
    data = urllib.request.urlopen(url).read()
    return pd.read_parquet(io.BytesIO(data))


def build():
    print("[1/5] parquet 데이터 다운로드...")
    stations_df = download_parquet(STATION_URL)
    lines_df = download_parquet(LINE_URL)

    print(f"  → {len(stations_df)}개 레코드, {len(lines_df)}개 노선")

    # line_no → line_name 매핑 딕셔너리
    line_map = dict(zip(lines_df["line_no"].astype(str), lines_df["line_name"]))
    print(f"\n[2/5] 노선 매핑: {line_map}")

    print("\n[3/5] 환승역 그룹핑 및 데이터 병합...")
    # line_no를 한글 노선명으로 변환
    stations_df["line_name"] = stations_df["line_no"].astype(str).map(line_map)

    # station_name 기준 그룹핑 (환승역은 같은 이름으로 여러 행 존재)
    grouped = stations_df.groupby("station_name").agg(
        lat=("y", "first"),
        lng=("x", "first"),
        lines=("line_name", lambda x: ",".join(sorted(set(x.dropna())))),
    ).reset_index()

    print(f"  → 그룹핑 후 {len(grouped)}개 고유역")

    print("\n[4/5] city_code 매핑 (66개 시군구 centroid 기반)...")
    results = []
    featured_list = []
    normal_list = []

    for _, row in grouped.iterrows():
        name = row["station_name"]
        # "역" 접미사 통일
        display_name = name + "역" if not name.endswith("역") else name

        city_code = find_city_code(row["lat"], row["lng"])

        entry = {
            "name": display_name,
            "lat": round(row["lat"], 6),
            "lng": round(row["lng"], 6),
            "line": row["lines"],
            "city_code": city_code,
        }

        # 주요 거점역은 상단 배치
        clean_name = name.replace("역", "") if name.endswith("역") else name
        if clean_name in FEATURED_STATIONS:
            featured_list.append(entry)
        else:
            normal_list.append(entry)

    # featured 역을 FEATURED_STATIONS 순서대로 정렬
    featured_sorted = []
    for fname in FEATURED_STATIONS:
        for entry in featured_list:
            if entry["name"].replace("역", "") == fname:
                featured_sorted.append(entry)
                break

    results = featured_sorted + sorted(normal_list, key=lambda x: x["name"])

    print(f"\n[5/5] stations.json 저장...")
    output_path = os.path.join(BASE_DIR, "data", "stations.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n완료! {len(results)}개역 저장 → {output_path}")
    print(f"  주요 거점역 (상단): {[s['name'] for s in featured_sorted]}")

    # LINE_COLORS 검증용 출력
    all_lines = set()
    for entry in results:
        for line in entry["line"].split(","):
            all_lines.add(line.strip())
    print(f"\n포함된 전체 노선: {sorted(all_lines)}")

    # 샘플 출력
    print("\n--- 샘플 (처음 5개) ---")
    for s in results[:5]:
        print(f"  {s['name']} | {s['line']} | {s['city_code']} | ({s['lat']}, {s['lng']})")

    return results


if __name__ == "__main__":
    build()
