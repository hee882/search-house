import os
import requests
import json
import math
import sqlite3
import logging
import threading
from contextlib import closing
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load .env
load_dotenv()

logger = logging.getLogger(__name__)
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")
CACHE_TTL_SECONDS = int(os.getenv("COMMUTE_CACHE_TTL_SECONDS", "900"))
# 검색 결과가 없던 단지도 나중에 카카오에 등록될 수 있어 영구 보관하지 않고 주기적으로 다시 묻는다
GEOCODE_NEGATIVE_TTL_SECONDS = int(os.getenv("GEOCODE_NEGATIVE_TTL_SECONDS", "604800"))

# 후보 분석이 ThreadPoolExecutor에서 병렬로 돌고, Session은 스레드 간 공유가 보장되지 않아 스레드마다 둔다
_thread_local = threading.local()

_schema_lock = threading.Lock()
_initialized_db_paths = set()


def _is_javascript_key(key):
    """지도 SDK용 JavaScript 키인지 판별한다 (REST API에 쓰면 인증이 거부된다)."""
    return key.startswith('feb433')


def is_realtime_routing_available():
    """카카오 모빌리티 실시간 경로 API를 실제로 호출할 수 있는 상태인지 반환.

    REST 키가 없거나 JavaScript 키가 잘못 설정된 경우 모든 소요시간이
    거리 기반 추정치로 계산되므로, 응답에서 이를 그대로 알려야 한다.
    """
    return bool(KAKAO_REST_API_KEY) and not _is_javascript_key(KAKAO_REST_API_KEY)


def _http_get(url, headers, params):
    """카카오 API GET 호출.

    요청 한 번에 같은 호스트를 여러 번 부르므로, 스레드별 Session을 재사용해
    호출마다 TCP·TLS 연결을 새로 맺지 않게 한다.
    """
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        _thread_local.session = session
    return session.get(url, headers=headers, params=params, timeout=5)


def _connect(db_path):
    """SQLite 커넥션 생성.

    후보를 병렬로 분석하면 캐시 쓰기가 동시에 몰린다. 기본 journal 모드에서는
    쓰기마다 DB 전체에 락이 걸려 계산만 하는 호출도 초 단위로 밀렸다.
    WAL은 DB 파일에 한 번 기록되는 속성이라 매번 설정해도 비용이 거의 없다.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.Error as e:  # 읽기 전용 파일시스템 등
        logger.debug(f"WAL 설정 실패: {e}")
    return conn


def _initialize_schema(db_path):
    """캐시 테이블 생성, 구버전 마이그레이션, 만료 행 정리를 수행한다."""
    now = datetime.now().timestamp()
    with closing(_connect(db_path)) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS complex_coords_v2 (
                city_code TEXT NOT NULL, apt_name TEXT NOT NULL, dong_name TEXT NOT NULL,
                lat REAL, lng REAL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (city_code, apt_name, dong_name)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS commute_cache_v3 (
                from_lat REAL, from_lng REAL, to_lat REAL, to_lng REAL,
                transport_mode TEXT, cache_key TEXT,
                duration_min INTEGER, distance_km REAL, updated_at REAL,
                PRIMARY KEY (from_lat, from_lng, to_lat, to_lng, transport_mode, cache_key)
            )
        ''')
        columns = {row[1] for row in conn.execute("PRAGMA table_info(commute_cache_v3)")}
        if "updated_at" not in columns:
            conn.execute("ALTER TABLE commute_cache_v3 ADD COLUMN updated_at REAL")
            conn.execute("UPDATE commute_cache_v3 SET updated_at = ? WHERE updated_at IS NULL", (now,))
        # cache_key에 출발 날짜가 들어가 매주 새 행이 쌓이므로, 지우지 않으면 테이블이 계속 커진다
        conn.execute(
            "DELETE FROM commute_cache_v3 WHERE updated_at IS NULL OR updated_at < ?",
            (now - CACHE_TTL_SECONDS,),
        )
        conn.commit()


def _ensure_schema(db_path):
    """db_path의 캐시 스키마를 프로세스당 한 번만 초기화한다.

    요청 한 번에 수십 번 호출되는 경로라, 매번 CREATE TABLE·PRAGMA·commit을
    실행하면 병렬 호출끼리 쓰기 락을 두고 경합한다.
    """
    key = os.path.abspath(db_path)
    with _schema_lock:
        if key in _initialized_db_paths:
            return
        _initialize_schema(db_path)
        _initialized_db_paths.add(key)


def _execute_cache_query(db_path, sql, params, write):
    _ensure_schema(db_path)
    with closing(_connect(db_path)) as conn:
        cursor = conn.execute(sql, params)
        if not write:
            return cursor.fetchone()
        conn.commit()
        return None


def _run_cache_query(db_path, sql, params, write=False):
    """캐시 DB에 쿼리 한 건을 실행한다. 조회면 첫 행을 반환하고, 쓰기면 커밋한다.

    프로세스가 떠 있는 동안 같은 경로의 DB 파일이 지워졌다 다시 만들어지면
    초기화 기록만 남고 테이블은 없는 상태가 되므로, 한 번만 재초기화 후 재시도한다.
    """
    try:
        return _execute_cache_query(db_path, sql, params, write)
    except sqlite3.OperationalError as e:
        if "no such table" not in str(e):
            raise
        with _schema_lock:
            _initialized_db_paths.discard(os.path.abspath(db_path))
        return _execute_cache_query(db_path, sql, params, write)

# city_code → 구/시 이름 역방향 조회 테이블 (정밀 검색 쿼리 구성용)
def _build_code_to_district():
    try:
        region_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "region_codes.json")
        with open(region_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        mapping = {}
        for city, districts in data.items():
            for district, code in districts.items():
                mapping[str(code)] = district
        return mapping
    except Exception:
        return {}

CODE_TO_DISTRICT = _build_code_to_district()

def get_precise_coordinates(db_path, apt_name, dong_name, city_code=None):
    """
    카카오 키워드/주소 검색 API를 통해 단지의 정밀 좌표를 반환.
    DB 캐싱 지원.
    """
    # 1. 캐시 확인 (외부 API 호출 전에 커넥션을 반드시 닫는다)
    normalized_city = str(city_code or "")
    try:
        cache = _run_cache_query(
            db_path,
            'SELECT lat, lng, updated_at FROM complex_coords_v2 WHERE city_code = ? AND apt_name = ? AND dong_name = ?',
            (normalized_city, apt_name, dong_name),
        )
        if cache:
            cached_lat, cached_lng, updated_at = cache
            if cached_lat is not None and cached_lng is not None:
                return cached_lat, cached_lng
            # 좌표가 NULL인 행은 "카카오에 검색 결과가 없었다"는 기록이라 TTL 동안은 다시 묻지 않는다
            if updated_at is not None and datetime.now().timestamp() - updated_at < GEOCODE_NEGATIVE_TTL_SECONDS:
                return None, None
    except Exception as e:
        logger.error(f"Complex cache lookup error: {e}")

    # 2. API 호출
    lat, lng = None, None
    # 장애나 쿼터 초과까지 "결과 없음"으로 굳지 않도록, 정상 응답에 문서가 없을 때만 True로 바꾼다
    no_result = False
    if KAKAO_REST_API_KEY:
        if _is_javascript_key(KAKAO_REST_API_KEY):
            logger.error("[Kakao API] Detected JavaScript Key. Please use REST API Key instead.")
        else:
            url = "https://dapi.kakao.com/v2/local/search/keyword.json"
            headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY.strip()}"}

            # city_code로 구/시 이름을 가져와 검색 정확도 향상
            district = CODE_TO_DISTRICT.get(str(city_code), "") if city_code else ""
            clean_apt_name = apt_name if '아파트' in apt_name else f"{apt_name} 아파트"
            # 예: "강남구 역삼동 힐스테이트 아파트"
            query_parts = [p for p in [district, dong_name, clean_apt_name] if p]
            query = " ".join(query_parts)
            params = {"query": query, "size": 5} # 5개까지 받아서 필터링
            
            try:
                res = _http_get(url, headers, params)
                if res.status_code == 200:
                    data = res.json()
                    if data.get('documents'):
                        # [개선] 결과 중 '아파트' 카테고리가 포함된 항목을 우선 탐색
                        docs = data['documents']
                        target_doc = None
                        for d in docs:
                            if '아파트' in d.get('category_name', ''):
                                target_doc = d
                                break
                        
                        # 아파트 카테고리가 없으면 첫 번째 결과 사용
                        if not target_doc: target_doc = docs[0]
                        
                        lat, lng = float(target_doc['y']), float(target_doc['x'])
                        logger.info(f"[Kakao Geocode] Success for {query}: {lat}, {lng} ({target_doc.get('place_name')})")
                    else:
                        no_result = True
                else:
                    logger.warning(f"[Kakao Geocode] Request failed for {query}: HTTP {res.status_code}")
            except Exception as e:
                logger.error(f"Geocoding API failed: {e}")

    # 3. 결과 캐싱 및 반환
    # 결과 없음도 기록해 두지 않으면 같은 단지를 요청마다 다시 조회해 쿼터와 응답 시간을 낭비한다
    found = bool(lat and lng)
    if found or no_result:
        try:
            _run_cache_query(
                db_path,
                '''INSERT OR REPLACE INTO complex_coords_v2
                   (city_code, apt_name, dong_name, lat, lng, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (normalized_city, apt_name, dong_name, lat, lng, datetime.now().timestamp()),
                write=True,
            )
        except Exception as e:
            logger.error(f"Complex cache save error: {e}")

    if found:
        return lat, lng
    return None, None

def call_kakao_api(origin_lng, origin_lat, dest_lng, dest_lat, d_time):
    """카카오 모빌리티 미래 경로 탐색 API 단일 호출 유틸리티"""
    if not KAKAO_REST_API_KEY or _is_javascript_key(KAKAO_REST_API_KEY):
        return None

    url = "https://apis-navi.kakaomobility.com/v1/future/directions"
    headers = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY.strip()}"}
    params = {
        "origin": f"{origin_lng},{origin_lat}",
        "destination": f"{dest_lng},{dest_lat}",
        "departure_time": d_time,
        "priority": "RECOMMEND"
    }
    try:
        res = _http_get(url, headers, params)
        if res.status_code == 200:
            data = res.json()
            if data.get('routes') and data['routes'][0]['result_code'] == 0:
                route = data['routes'][0]['summary']
                return int(route['duration'] / 60), route['distance'] / 1000
            else:
                logger.error(f"[Kakao API] API Error: {data}")
        elif res.status_code == 401:
            logger.error("[Kakao API] 401 Unauthorized: REST API Key is invalid.")
        else:
            # 429·5xx를 조용히 버리면 추정치로 대체된 원인을 운영 중에 알 수 없다
            logger.warning(f"[Kakao API] Directions request failed: HTTP {res.status_code}")
    except Exception as e:
        logger.error(f"API Call failed: {e}")
    return None

def estimate_commute(from_lat, from_lng, to_lat, to_lng, transport_mode='car', hour=8):
    """경로 API 없이 거리·시간대만으로 통근 시간(분)과 거리(km)를 추정한다.

    실제 경로 API 호출은 비싸므로 후보를 좁히는 1차 스크리닝과
    API 실패 시 대체값으로 모두 이 함수를 사용한다.
    """
    R = 6371
    d_lat = math.radians(to_lat - from_lat)
    d_lng = math.radians(to_lng - from_lng)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(from_lat)) * math.cos(math.radians(to_lat)) * math.sin(d_lng / 2) ** 2)
    distance = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    speed = 25 if transport_mode == 'public' else 35
    base_duration = (distance / speed) * 60
    traffic_multiplier = 1.0
    if 7 <= hour <= 8:
        traffic_multiplier = 1.35
    elif 17 <= hour <= 18:
        traffic_multiplier = 1.20
    duration = int(base_duration * traffic_multiplier) + (15 if transport_mode == 'public' else 5)
    return duration, distance


def get_kakao_commute(db_path, from_lat, from_lng, to_lat, to_lng, transport_mode='car', departure_time=None, goal_arrive_time=None):
    """
    카카오 모빌리티 API를 통해 정밀 통근 시간을 반환 (시뮬레이션 포함).
    """
    f_lat, f_lng = round(from_lat, 4), round(from_lng, 4)
    t_lat, t_lng = round(to_lat, 4), round(to_lng, 4)
    
    # 1. 캐시 확인
    cache_key = departure_time if departure_time else f"arrive_{goal_arrive_time}"
    try:
        cache = _run_cache_query(db_path, '''
            SELECT duration_min, distance_km FROM commute_cache_v3
            WHERE from_lat = ? AND from_lng = ? AND to_lat = ? AND to_lng = ?
            AND transport_mode = ? AND cache_key = ?
            AND updated_at IS NOT NULL AND updated_at >= ?
        ''', (f_lat, f_lng, t_lat, t_lng, transport_mode, cache_key,
              datetime.now().timestamp() - CACHE_TTL_SECONDS))
        if cache:
            return cache[0], cache[1]
    except Exception as e:
        logger.error(f"Cache lookup error: {e}")

    # 2. 시간 설정 및 시뮬레이션
    duration, distance = 0, 0
    now = datetime.now()
    days_ahead = 0 - now.weekday()
    if days_ahead <= 0: days_ahead += 7
    target_date = (now + timedelta(days=days_ahead))

    current_hour = 0
    if goal_arrive_time:
        current_hour = int(goal_arrive_time[:2])
        goal_h, goal_m = int(goal_arrive_time[:2]), int(goal_arrive_time[2:])
        test_departure = target_date.replace(hour=goal_h, minute=goal_m) - timedelta(minutes=45)
        
        res1 = call_kakao_api(from_lng, from_lat, to_lng, to_lat, test_departure.strftime("%Y%m%d%H%M")) if transport_mode == 'car' else None
        if res1:
            dur1, dist1 = res1
            actual_arrive = test_departure + timedelta(minutes=dur1)
            target_arrive = target_date.replace(hour=goal_h, minute=goal_m)
            diff_min = (actual_arrive - target_arrive).total_seconds() / 60
            if abs(diff_min) > 5:
                refined_departure = test_departure - timedelta(minutes=int(diff_min))
                res2 = call_kakao_api(from_lng, from_lat, to_lng, to_lat, refined_departure.strftime("%Y%m%d%H%M")) if transport_mode == 'car' else None
                if res2: duration, distance = res2
                else: duration, distance = dur1, dist1
            else:
                duration, distance = dur1, dist1
    
    elif departure_time:
        current_hour = int(departure_time[8:10])
        res = call_kakao_api(from_lng, from_lat, to_lng, to_lat, departure_time) if transport_mode == 'car' else None
        if res: duration, distance = res

    # 3. Fallback (API 실패 혹은 대중교통)
    if not duration:
        duration, distance = estimate_commute(from_lat, from_lng, to_lat, to_lng, transport_mode, current_hour)

    # 4. 결과 캐싱 (TTL 만료된 기존 행은 새 값으로 갱신해야 하므로 REPLACE 사용)
    try:
        _run_cache_query(db_path, '''
            INSERT OR REPLACE INTO commute_cache_v3
            (from_lat, from_lng, to_lat, to_lng, transport_mode, cache_key, duration_min, distance_km, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (f_lat, f_lng, t_lat, t_lng, transport_mode, cache_key, duration, distance, datetime.now().timestamp()),
            write=True)
    except Exception as e:
        logger.error(f"Cache save error: {e}")

    return duration, distance
