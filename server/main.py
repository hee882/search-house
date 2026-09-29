from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from typing import Literal, Optional
import math
import json
import os
import logging
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from lib.kakao_api import (get_kakao_commute, get_precise_coordinates,
                           is_realtime_routing_available, estimate_commute)

# --- Logging Setup ---
# 장기간 띄워 두는 서버라 로그 파일이 무한히 커지지 않도록 5MB 단위로 회전하고 백업은 3개만 남긴다.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            os.path.join(os.path.dirname(__file__), "server.log"),
            maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)

app = FastAPI()

# Lightweight per-process protection for the expensive optimization endpoint.
# Deployments with multiple workers should enforce the same limit at the edge too.
OPTIMIZE_RATE_WINDOW_SECONDS = max(1, int(os.getenv("OPTIMIZE_RATE_WINDOW_SECONDS", "60")))
OPTIMIZE_RATE_MAX_REQUESTS = max(1, int(os.getenv("OPTIMIZE_RATE_MAX_REQUESTS", "12")))
_optimize_rate: dict[str, list[float]] = {}
_optimize_rate_lock = threading.Lock()

def _check_optimize_rate_limit(client_key: str) -> bool:
    now = time.monotonic()
    cutoff = now - OPTIMIZE_RATE_WINDOW_SECONDS
    with _optimize_rate_lock:
        recent = [stamp for stamp in _optimize_rate.get(client_key, []) if stamp > cutoff]
        if len(recent) >= OPTIMIZE_RATE_MAX_REQUESTS:
            _optimize_rate[client_key] = recent
            return False
        recent.append(now)
        _optimize_rate[client_key] = recent
        # Prevent abandoned client keys from growing without bound.
        if len(_optimize_rate) > 10_000:
            for key, stamps in list(_optimize_rate.items()):
                if not stamps or stamps[-1] <= cutoff:
                    _optimize_rate.pop(key, None)
        return True

# Render 같은 프록시 뒤에서는 소켓 주소가 프록시 주소라 모든 사용자가 한도를 같이 쓴다.
# 앞단에 있는 신뢰할 수 있는 프록시 수를 알려주면 X-Forwarded-For에서 실제 클라이언트를 고른다.
TRUSTED_PROXY_HOPS = max(0, int(os.getenv("TRUSTED_PROXY_HOPS", "0")))

def _rate_limit_client_key(http_request: Request) -> str:
    """레이트리밋에 쓸 클라이언트 식별자.

    X-Forwarded-For의 왼쪽 값은 클라이언트가 마음대로 채워 보낼 수 있으므로,
    신뢰하는 프록시가 덧붙인 오른쪽에서 N번째 값만 쓴다.
    """
    socket_host = http_request.client.host if http_request.client else "unknown"
    if TRUSTED_PROXY_HOPS <= 0:
        return socket_host
    # 헤더가 여러 줄로 오면 이어 붙인 하나의 목록과 같다. 첫 줄만 읽으면 위조한 줄이 선택될 수 있다.
    forwarded = ",".join(http_request.headers.getlist("x-forwarded-for"))
    hops = [hop.strip() for hop in forwarded.split(",")]
    if len(hops) < TRUSTED_PROXY_HOPS or not hops[-TRUSTED_PROXY_HOPS]:
        return socket_host
    return hops[-TRUSTED_PROXY_HOPS]

# --- CORS Configuration ---
# GitHub Pages와 로컬 개발 환경 모두에서 안정적으로 작동하도록 설정
# (Origin 헤더에는 경로가 붙지 않으므로 scheme://host[:port] 형태만 등록한다)
origins = [
    "http://localhost:5173",      # 로컬 Vite 환경
    "http://127.0.0.1:5173",      # 로컬 Vite 환경 (IP)
    "https://hee882.github.io",   # 배포된 프론트엔드 환경
    "https://search-house.onrender.com"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True, # 명시적인 origin 목록을 사용할 경우 credential 허용 가능
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# --- Models ---
class Location(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    name: str = Field(default="Unknown", min_length=1, max_length=200)

class UserProfile(BaseModel):
    workplace: Location
    salary: int = Field(ge=0, le=1_000_000)
    transport: Literal["public", "car"]

class OptimizeRequest(BaseModel):
    user1: UserProfile
    user2: Optional[UserProfile] = None
    mode: Literal["single", "couple"] = "single"
    # rent = 전월세 전체(거래가 많은 유형으로 자동), jeonse/wolse = 사용자가 직접 선택
    resident_type: Literal["buy", "rent", "jeonse", "wolse"] = "buy"
    housing_ratio: float = Field(default=0.25, gt=0, le=1)
    min_area: float = Field(default=40, gt=0, le=1_000)
    max_area: float = Field(default=200, gt=0, le=1_000)
    max_building_age: int = Field(default=0, ge=0, le=200)
    preference: Literal["money", "balance", "time"] = "balance"
    available_cash: int = Field(default=0, ge=0, le=100_000_000)

    @model_validator(mode="after")
    def validate_request_consistency(self):
        if self.min_area > self.max_area:
            raise ValueError("min_area must be less than or equal to max_area")
        if self.mode == "couple" and self.user2 is None:
            raise ValueError("user2 is required when mode is couple")
        return self

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "server", "data", "search_house.db")
# 좌표·통근 캐시는 실거래 DB와 다른 파일에 쓴다. 실거래 DB는 CI가 매일 자동 커밋하는 추적 파일이라
# 서버를 띄우거나 테스트만 돌려도 내용이 바뀌면 곧바로 충돌 원인이 된다.
CACHE_DB_PATH = os.getenv("CACHE_DB_PATH") or os.path.join(BASE_DIR, "server", "data", "runtime_cache.db")
STATIONS_PATH = os.path.join(BASE_DIR, "server", "data", "stations.json")
DONG_COORDS_PATH = os.path.join(BASE_DIR, "server", "data", "dong_coordinates.json")
FRONTEND_DIST = os.path.join(BASE_DIR, "client", "dist")

# --- Global Data ---
STATIONS_DATA = []
DONG_COORDS = {}
DISTRICT_CENTERS = {}  # city_code -> 구 내 동 좌표의 평균(대표 좌표)
RENT_HAS_CONTRACT_TYPE = False  # 수집기가 계약구분(신규/갱신)을 저장하기 시작했는지

def _build_district_centers(dong_coords):
    """구(city_code)별 동 좌표 평균을 대표 좌표로 계산.

    동 좌표가 없는 단지의 대체 좌표로 사용한다. 예전에는 사전순 첫 동의 좌표를
    그대로 썼기 때문에 같은 구 안에서도 한쪽 끝으로 크게 치우쳤다.
    """
    buckets = {}
    for key, value in dong_coords.items():
        code = key.split("_")[0]
        buckets.setdefault(code, []).append((value["lat"], value["lng"]))
    return {
        code: {
            "lat": round(sum(p[0] for p in points) / len(points), 6),
            "lng": round(sum(p[1] for p in points) / len(points), 6),
        }
        for code, points in buckets.items()
    }

def _rent_table_has_contract_type():
    """rent_transactions에 계약구분 컬럼이 있는지 확인.

    수집기 스키마 확장 이전에 만들어진 DB에서도 동작해야 하므로 런타임에 확인한다.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(rent_transactions)")}
        finally:
            conn.close()
        return "contract_type" in columns
    except Exception:
        return False


def load_global_data():
    global STATIONS_DATA, DONG_COORDS, DISTRICT_CENTERS, RENT_HAS_CONTRACT_TYPE
    try:
        if os.path.exists(STATIONS_PATH):
            with open(STATIONS_PATH, "r", encoding="utf-8") as f:
                STATIONS_DATA = json.load(f)
            logger.info(f"Loaded {len(STATIONS_DATA)} stations")

        if os.path.exists(DONG_COORDS_PATH):
            with open(DONG_COORDS_PATH, "r", encoding="utf-8") as f:
                DONG_COORDS = json.load(f)
            logger.info(f"Loaded {len(DONG_COORDS)} dong coordinates")
        DISTRICT_CENTERS = _build_district_centers(DONG_COORDS)
        logger.info(f"Built {len(DISTRICT_CENTERS)} district centers")

        RENT_HAS_CONTRACT_TYPE = _rent_table_has_contract_type()
        logger.info(f"Rent contract_type column available: {RENT_HAS_CONTRACT_TYPE}")
    except Exception as e:
        logger.error(f"Failed to load global data: {e}")

# Initial load
load_global_data()

@app.get("/api/health")
async def health():
    return {"status": "ok", "stations": len(STATIONS_DATA)}

# --- Database & Helper Functions ---

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371
    dLat, dLon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dLat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dLon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def _filter_complexes_by_iqr(raw_rows, min_samples=3):
    """
    단지별 GROUP_CONCAT 거래 데이터에 IQR 아웃라이어 제거 적용.
    price_pairs 포맷: "deposit:rent:area,..."
    반환: [(apt_name, dong_name, city_code, avg_deposit, avg_rent, avg_area, build_year), ...]
    """
    result = []
    for row in raw_rows:
        apt_name, dong_name, city_code = row[0], row[1], row[2]
        price_pairs_str = row[3]  # "5000:240:59,10000:200:59,25000:140:84,..."
        build_year = row[4]

        if not price_pairs_str:
            continue

        pairs = []
        for p in price_pairs_str.split(','):
            try:
                parts = p.split(':')
                d, r, a = int(parts[0]), int(parts[1]), float(parts[2])
                pairs.append((d, r, a))
            except Exception:
                continue

        # 전세(월세 0)와 월세를 섞어 평균 내면 보증금·월세가 모두 왜곡되므로
        # 거래가 더 많은 유형만 대표 시세로 사용
        jeonse = [p for p in pairs if p[1] == 0]
        wolse = [p for p in pairs if p[1] > 0]
        pairs = jeonse if len(jeonse) >= len(wolse) else wolse

        # 같은 단지라도 전용 40㎡와 84㎡는 다른 매물이다. 면적대를 섞어 평균 내면
        # 가격과 평균 면적이 모두 실제로는 존재하지 않는 값이 되므로,
        # 전용 10㎡ 단위로 묶어 거래가 가장 많은 면적대만 대표 시세로 사용한다.
        # (거래 수가 같으면 예산 관점에서 보수적인 작은 면적대를 택한다)
        area_buckets = {}
        for pair in pairs:
            area_buckets.setdefault(int(pair[2] // 10), []).append(pair)
        pairs = max(area_buckets.items(), key=lambda item: (len(item[1]), -item[0]))[1]

        if len(pairs) < min_samples:
            continue

        deposits = [d for d, _, _ in pairs]

        # IQR 계산 (가격 기준). 상한도 함께 적용해야 대형 평형·고층 프리미엄 거래가
        # 대표 시세를 끌어올리는 것을 막을 수 있다.
        if len(deposits) >= 4:
            sd = sorted(deposits)
            n = len(sd)
            q1 = sd[n // 4]
            q3 = sd[(3 * n) // 4]
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr
            clean_pairs = [(d, r, a) for d, r, a in pairs if lower_bound <= d <= upper_bound]
        else:
            clean_pairs = pairs

        if len(clean_pairs) < min_samples:
            continue

        avg_d = int(sum(d for d, _, _ in clean_pairs) / len(clean_pairs))
        avg_r = int(sum(r for _, r, _ in clean_pairs) / len(clean_pairs))
        avg_a = round(sum(a for _, _, a in clean_pairs) / len(clean_pairs), 1)

        result.append((apt_name, dong_name, city_code, avg_d, avg_r, avg_a, build_year))

    return result

# 실거래 데이터는 하루 한 번만 바뀌는데 요청마다 최근 12개월 전체를 다시 집계하면
# (실측 전월세 약 0.2초, 매매 약 0.08초 + IQR 처리) 그 시간이 그대로 응답 지연이 된다.
OPTIMIZE_AGGREGATE_TTL_SECONDS = max(0, int(os.getenv("OPTIMIZE_AGGREGATE_TTL_SECONDS", "600")))
# 항목 하나가 1.6~2.5MB라 상한이 곧 메모리 상한이다. Render 인스턴스(512MB)에서
# 다른 용도의 메모리를 밀어내지 않도록 기본값을 16개(최대 약 40MB)로 둔다.
OPTIMIZE_AGGREGATE_MAX_ENTRIES = max(1, int(os.getenv("OPTIMIZE_AGGREGATE_MAX_ENTRIES", "16")))
_aggregate_cache: dict[tuple, tuple[float, tuple]] = {}
_aggregate_cache_lock = threading.Lock()


def _query_complex_rows(resident_type, min_area, max_area, min_build_year, min_month_index):
    """조건에 맞는 거래를 단지별 GROUP_CONCAT으로 묶어 조회한다 (IQR 처리 전 원본)."""
    # 단지별 전체 거래를 GROUP_CONCAT으로 가져와 Python에서 IQR 아웃라이어 제거
    # 공공임대는 단지명으로 걸러낸다. 보증금 하한은 전세에만 적용한다.
    # (예전에는 보증금 3000만 하한을 월세에도 걸어 '보증금 1000/월 70' 같은
    #  일반 월세 거래 2만여 건, 전체의 13%가 통째로 빠졌다)
    RENTAL_FILTER = """
        AND (
            (monthly_rent = 0 AND deposit >= 3000)
            OR (monthly_rent >= 10)
        )
        AND apt_name NOT LIKE '%임대%'
        AND apt_name NOT LIKE '%행복주택%'
        AND apt_name NOT LIKE '%LH%'
        AND apt_name NOT LIKE '%SH%'
        AND apt_name NOT LIKE '%공공임대%'
        AND apt_name NOT LIKE '%국민임대%'
        AND apt_name NOT LIKE '%영구임대%'
        AND apt_name NOT LIKE '%장기전세%'
        AND apt_name NOT LIKE '%시프트%'
        AND apt_name NOT LIKE '%뉴스테이%'
        AND apt_name NOT LIKE '%기업형임대%'
        AND apt_name NOT LIKE '%도시형%'
        AND apt_name NOT LIKE '%오피스텔%'
    """
    area_filter = "AND exclusive_area >= ? AND exclusive_area <= ?"
    # 갱신계약은 2년 전 보증금에 상한이 걸린 값이라 지금 들어갈 수 있는 시세보다 낮다.
    # 실측 기준 같은 단지·면적대에서 신규계약 대비 중앙값 -9.2% 수준이어서 제외한다.
    contract_filter = " AND (contract_type IS NULL OR contract_type != '갱신')" if RENT_HAS_CONTRACT_TYPE else ""
    year_filter = " AND build_year >= ?" if min_build_year > 0 else ""

    # 전세/월세를 직접 고른 경우 해당 유형만 집계한다.
    # (선택하지 않으면 거래가 많은 유형이 대표 시세가 되어, 전세를 찾는 사용자에게
    #  월세 단지가 섞여 나왔다)
    if resident_type == 'jeonse':
        rent_type_filter = " AND monthly_rent = 0"
    elif resident_type == 'wolse':
        rent_type_filter = " AND monthly_rent > 0"
    else:
        rent_type_filter = ""

    if resident_type == 'buy':
        # 매매: 실거래가(deal_amount, 만원)를 보증금 자리에 넣어 동일한 집계 파이프라인을 사용한다.
        # 해제된 거래(cancel_deal_day)는 시세로 볼 수 없으므로 제외한다.
        raw_query = f"""
            SELECT apt_name, dong_name, city_code,
                   GROUP_CONCAT(deal_amount || ':0:' || exclusive_area) as price_pairs,
                   build_year
            FROM transactions
            WHERE (deal_year * 12 + deal_month) >= ?
            AND (cancel_deal_day IS NULL OR cancel_deal_day = '')
            AND deal_amount > 0
            {area_filter}
            {year_filter}
            GROUP BY apt_name, dong_name, city_code
            HAVING COUNT(*) >= 3
        """
    else:
        raw_query = f"""
            SELECT apt_name, dong_name, city_code,
                   GROUP_CONCAT(deposit || ':' || monthly_rent || ':' || exclusive_area) as price_pairs,
                   build_year
            FROM rent_transactions
            WHERE (deal_year * 12 + deal_month) >= ?
            {RENTAL_FILTER}
            {contract_filter}
            {rent_type_filter}
            {area_filter}
            {year_filter}
            GROUP BY apt_name, dong_name, city_code
            HAVING COUNT(*) >= 3
        """
    params = [min_month_index, min_area, max_area]
    if min_build_year > 0:
        params.append(min_build_year)

    conn = sqlite3.connect(DB_PATH)
    try:
        return conn.execute(raw_query, params).fetchall()
    finally:
        conn.close()


def get_complex_aggregates(resident_type, min_area, max_area, min_build_year, min_month_index):
    """IQR 필터까지 끝낸 단지별 대표 시세를 반환한다 (조건별 TTL 캐시).

    반환값은 여러 요청이 함께 쓰는 캐시 항목이라, 호출자가 바꿀 수 없도록 튜플로 돌려준다.
    """
    # 테스트가 DB_PATH를 바꿔 끼우고 계약구분 컬럼 유무에 따라 쿼리가 달라지므로 둘 다 키에 넣는다.
    key = (DB_PATH, resident_type, min_area, max_area, min_build_year, min_month_index,
           RENT_HAS_CONTRACT_TYPE)
    ttl = OPTIMIZE_AGGREGATE_TTL_SECONDS
    with _aggregate_cache_lock:
        cached = _aggregate_cache.get(key)
        if cached and time.monotonic() - cached[0] < ttl:
            return cached[1]

    # 조회와 IQR 처리는 락 밖에서 한다. 락을 쥔 채 집계하면 조건이 다른 요청까지 줄을 서게 된다.
    raw_rows = _query_complex_rows(resident_type, min_area, max_area, min_build_year, min_month_index)

    # IQR 기반 아웃라이어 제거 후 클린 평균 산출
    complexes = _filter_complexes_by_iqr(raw_rows, min_samples=3)

    # 결과 없으면 IQR min_samples 완화해서 재시도 (거래량이 적은 지역 대응)
    if not complexes:
        logger.info("IQR 필터 후 결과 없음 → min_samples=2로 완화 재시도")
        complexes = _filter_complexes_by_iqr(raw_rows, min_samples=2)
    complexes = tuple(complexes)

    if ttl <= 0:
        return complexes

    with _aggregate_cache_lock:
        now = time.monotonic()
        _aggregate_cache.pop(key, None)  # 다시 넣어 삽입 순서상 가장 최신 항목이 되게 한다
        _aggregate_cache[key] = (now, complexes)
        if len(_aggregate_cache) > OPTIMIZE_AGGREGATE_MAX_ENTRIES:
            # 면적 조건을 조금씩 바꾼 요청이 이어져도 메모리가 계속 늘지 않도록
            # 만료된 항목부터, 그래도 넘치면 오래된 순으로 버린다.
            for stale_key in [k for k, (stamp, _) in _aggregate_cache.items() if now - stamp >= ttl]:
                _aggregate_cache.pop(stale_key, None)
            while len(_aggregate_cache) > OPTIMIZE_AGGREGATE_MAX_ENTRIES:
                _aggregate_cache.pop(next(iter(_aggregate_cache)))
    return complexes

MAX_RESULTS = 5
MAX_RESULTS_PER_DONG = 2
# 거리 기준으로 훑을 후보 수와, 그중 실제 경로 API로 정밀 분석할 수.
# 후보 전부를 정밀 분석하면 요청 한 번에 경로·지오코딩 API를 200회 가까이 호출하게 된다.
CANDIDATE_SCAN_LIMIT = 50
PRECISE_ANALYSIS_LIMIT = max(MAX_RESULTS, int(os.getenv("OPTIMIZE_PRECISE_LIMIT", "12")))
# 정밀 분석은 후보마다 독립적인 외부 API 호출이라 병렬로 처리한다.
# (순차 처리 시 캐시가 비어 있으면 요청 하나가 10초를 넘긴다)
PRECISE_ANALYSIS_WORKERS = max(1, int(os.getenv("OPTIMIZE_PRECISE_WORKERS", "6")))


def diversify_results(results, limit=MAX_RESULTS, per_dong=MAX_RESULTS_PER_DONG):
    """같은 동의 단지가 결과를 독점하지 않도록 추려낸다.

    점수만으로 자르면 한 단지의 1·8·9·10·11단지처럼 사실상 같은 선택지가
    상위를 모두 차지해 비교할 대안이 사라진다. 동별 상한을 두되,
    상한 때문에 개수를 못 채우면 남은 자리는 점수 순으로 채운다.
    """
    picked, counts = [], {}
    for item in results:
        dong = item.get("dong") or ""
        if counts.get(dong, 0) >= per_dong:
            continue
        counts[dong] = counts.get(dong, 0) + 1
        picked.append(item)
        if len(picked) >= limit:
            return picked

    chosen = {id(item) for item in picked}
    for item in results:
        if len(picked) >= limit:
            break
        if id(item) not in chosen:
            picked.append(item)
    return picked


def get_collected_period(table, city_code=None):
    """해당 테이블(지역)에 실제로 수집된 거래월 범위와 수집된 월 수를 반환.

    조회한 달에 데이터가 0건일 때 "거래가 없었던 달"인지 "아직 수집되지 않은 달"인지
    호출자가 구분할 수 있어야 한다.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            where, params = "", []
            if city_code:
                where, params = "WHERE city_code = ?", [city_code]
            row = conn.execute(
                f"""SELECT MIN(deal_year * 100 + deal_month), MAX(deal_year * 100 + deal_month),
                           COUNT(DISTINCT deal_year * 100 + deal_month)
                    FROM {table} {where}""",
                params,
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        logger.exception("Collected period lookup failed")
        return None

    if not row or row[0] is None:
        return {"first_month": None, "last_month": None, "collected_months": 0}
    return {"first_month": str(row[0]), "last_month": str(row[1]), "collected_months": row[2]}


def is_month_collected(table, city_code, year, month):
    """해당 지역·월이 수집된 적 있는지 (0건 응답의 의미를 구분하기 위함)"""
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            row = conn.execute(
                f"SELECT 1 FROM {table} WHERE city_code = ? AND deal_year = ? AND deal_month = ? LIMIT 1",
                (city_code, year, month),
            ).fetchone()
        finally:
            conn.close()
        return row is not None
    except Exception:
        logger.exception("Month coverage lookup failed")
        return False


def candidate_distance_score(lat, lng, workplaces):
    """후보지 선별용 거리 점수 (작을수록 좋음).

    거리 합만 쓰면 두 직장이 일직선일 때 "한 명은 도보, 한 명은 1시간"인 위치가
    최상위로 올라온다. 더 먼 쪽에 가중을 더해 양쪽 모두 감당 가능한 위치를 고른다.
    1인 모드에서는 단순히 거리의 2배라 순서가 바뀌지 않는다.
    반환값: (점수, 각 직장까지의 거리 목록)
    """
    distances = [calculate_distance(lat, lng, w_lat, w_lng) for w_lat, w_lng in workplaces]
    return sum(distances) + max(distances), distances


def get_nearest_stations(lat, lng, n=3, max_distance_km=2.0):
    """좌표 기준 가장 가까운 지하철역 top n 반환 (2km 이내)"""
    with_dist = []
    for s in STATIONS_DATA:
        d = calculate_distance(lat, lng, s['lat'], s['lng'])
        if d <= max_distance_km:
            with_dist.append((d, s['name']))
    with_dist.sort(key=lambda x: x[0])
    return [name for _, name in with_dist[:n]]

JEONSE_LOAN_RATE = 0.035    # 전세대출 금리 연 3.5% 기준
MORTGAGE_RATE = 0.042       # 주택담보대출 금리 연 4.2% 기준
CASH_OPPORTUNITY_RATE = 0.04  # 자기자본을 예치했을 때의 기회수익률 연 4%


def format_price_kr(amount_manwon):
    """만원 단위 금액을 '5억 8,000만' 형태로 표기"""
    amount = int(amount_manwon)
    if amount >= 10000:
        eok, remainder = divmod(amount, 10000)
        return f"{eok}억" if remainder == 0 else f"{eok}억 {remainder:,}만"
    return f"{amount:,}만"

def calculate_monthly_housing_cost(deposit, monthly_rent, available_cash=0, resident_type='rent'):
    """보유 자금을 고려한 월 주거비 계산.

    deposit은 전월세면 보증금, 매매면 매매가(만원)를 뜻한다.
    available_cash > 0: 초과분은 대출 이자(전세 3.5% / 주담대 4.2%), 보유분은 기회비용(4%)
    available_cash == 0: 전액을 묶인 자금으로 보고 기회비용(4%)만 계산
    매매는 취득세·보유세·수선비를 포함하지 않는 자금비용 기준이다.
    """
    loan_rate = MORTGAGE_RATE if resident_type == 'buy' else JEONSE_LOAN_RATE
    if available_cash > 0:
        own_cash = min(deposit, available_cash)
        loan_amount = max(0, deposit - available_cash)
        return monthly_rent + round(own_cash * CASH_OPPORTUNITY_RATE / 12) + round(loan_amount * loan_rate / 12)
    return monthly_rent + round(deposit * CASH_OPPORTUNITY_RATE / 12)

def calculate_hidden_life_cost(salary, commute_minutes):
    hourly_wage = (salary * 10000) / 12 / 209
    base_time_value = (hourly_wage / 60) * commute_minutes * 2 * 20
    multiplier = 1.0
    if commute_minutes >= 60: multiplier = 1.3
    elif commute_minutes >= 45: multiplier = 1.15
    return round((base_time_value * multiplier) / 10000)

# 통계 API는 동기 sqlite3를 호출하므로 async def로 두면 이벤트 루프가 막힌다.
# def로 선언해 FastAPI가 스레드풀에서 실행하게 한다.
@app.get("/api/stats/transactions")
def get_transaction_stats(
    city_code: str = Query(..., pattern=r"^\d{5}$"),
    year: Optional[int] = Query(None, ge=1900, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
):
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=404, detail="DB not found")
    try:
        now = datetime.now()
        year = year or now.year
        month = month or now.month

        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.cursor()

            cursor.execute('''
                SELECT COUNT(*) FROM transactions
                WHERE city_code = ? AND deal_year = ? AND deal_month = ?
                AND (cancel_deal_day IS NULL OR cancel_deal_day = '')
            ''', (city_code, year, month))
            total = cursor.fetchone()[0]

            # 해제된 거래는 total·daily에서 빠지므로 신고가 건수도 같은 기준으로 센다
            cursor.execute('''
                SELECT COUNT(*) FROM transactions
                WHERE city_code = ? AND deal_year = ? AND deal_month = ?
                AND is_new_high_price = 1
                AND (cancel_deal_day IS NULL OR cancel_deal_day = '')
            ''', (city_code, year, month))
            new_high_count = cursor.fetchone()[0]

            cursor.execute('''
                SELECT COUNT(*) FROM transactions
                WHERE city_code = ? AND deal_year = ? AND deal_month = ?
                AND cancel_deal_day IS NOT NULL AND cancel_deal_day != ''
            ''', (city_code, year, month))
            cancel_count = cursor.fetchone()[0]

            cursor.execute('''
                SELECT deal_day, COUNT(*) as cnt,
                       SUM(CASE WHEN is_new_high_price = 1 THEN 1 ELSE 0 END) as new_high
                FROM transactions
                WHERE city_code = ? AND deal_year = ? AND deal_month = ?
                AND (cancel_deal_day IS NULL OR cancel_deal_day = '')
                GROUP BY deal_day ORDER BY deal_day
            ''', (city_code, year, month))
            daily = [{"day": r[0], "count": r[1], "new_high": r[2]} for r in cursor.fetchall()]

            cursor.execute('''
                SELECT buyer_type, COUNT(*) FROM transactions
                WHERE city_code = ? AND deal_year = ? AND deal_month = ?
                AND (cancel_deal_day IS NULL OR cancel_deal_day = '')
                AND buyer_type IS NOT NULL AND buyer_type != ''
                GROUP BY buyer_type
            ''', (city_code, year, month))
            buyer_types = {r[0]: r[1] for r in cursor.fetchall()}
        finally:
            conn.close()

        coverage = get_collected_period("transactions", city_code) or {}
        return {
            "city_code": city_code,
            "period": f"{year}-{month:02d}",
            "summary": {
                "total": total,
                "new_high_count": new_high_count,
                "cancel_count": cancel_count,
                "buyer_types": buyer_types
            },
            "daily": daily,
            # 수집되지 않은 달도 total 0으로 보이므로 수집 여부를 함께 알려준다
            "coverage": {
                "requested_month_collected": is_month_collected("transactions", city_code, year, month),
                **coverage,
            },
        }
    except Exception:
        logger.exception("Stats request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/stats/new-highs")
def get_new_highs(
    city_code: str = Query(..., pattern=r"^\d{5}$"),
    limit: int = Query(20, ge=1, le=100),
):
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=404, detail="DB not found")
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.cursor()
            # 이전 최고가는 거래일이 더 이른 거래에서 찾는다. id는 수집 순서일 뿐이라
            # 과거 월을 재수집하면 더 이른 거래에 나중 id가 붙어 값이 틀어진다.
            # 같은 단지인지는 수집기가 신고가를 판정할 때(recompute_new_high_flags)와 같은 키로 본다.
            # apt_seq가 있으면 apt_seq, 없으면 city_code + dong_name + apt_name이다. 기준이 다르면
            # 단지명 표기가 바뀐 단지에서 신고가로 표시된 거래의 직전 최고가가 비어 버린다.
            # 두 경우를 OR로 묶지 않고 나눠 쓴 것은 각각 idx_new_high와 UNIQUE 인덱스를 타게 하기 위해서다.
            cursor.execute('''
                SELECT t.apt_name, t.dong_name, t.exclusive_area, t.deal_amount,
                       t.deal_year, t.deal_month, t.deal_day, t.floor, t.build_year,
                       CASE WHEN t.apt_seq IS NOT NULL AND t.apt_seq != '' THEN
                           (SELECT MAX(t2.deal_amount) FROM transactions t2
                            WHERE t2.apt_seq = t.apt_seq
                            AND t2.exclusive_area = t.exclusive_area
                            AND (t2.cancel_deal_day IS NULL OR t2.cancel_deal_day = '')
                            AND (t2.deal_year * 10000 + t2.deal_month * 100 + t2.deal_day)
                                < (t.deal_year * 10000 + t.deal_month * 100 + t.deal_day))
                       ELSE
                           (SELECT MAX(t3.deal_amount) FROM transactions t3
                            WHERE t3.city_code = t.city_code
                            AND t3.dong_name = t.dong_name AND t3.apt_name = t.apt_name
                            AND (t3.apt_seq IS NULL OR t3.apt_seq = '')
                            AND t3.exclusive_area = t.exclusive_area
                            AND (t3.cancel_deal_day IS NULL OR t3.cancel_deal_day = '')
                            AND (t3.deal_year * 10000 + t3.deal_month * 100 + t3.deal_day)
                                < (t.deal_year * 10000 + t.deal_month * 100 + t.deal_day))
                       END as prev_high
                FROM transactions t
                WHERE t.city_code = ? AND t.is_new_high_price = 1
                AND (t.cancel_deal_day IS NULL OR t.cancel_deal_day = '')
                ORDER BY t.deal_year DESC, t.deal_month DESC, t.deal_day DESC
                LIMIT ?
            ''', (city_code, limit))
            rows = cursor.fetchall()
        finally:
            conn.close()

        items = []
        for r in rows:
            prev = r[9] or 0
            increase_rate = round((r[3] - prev) / prev * 100, 2) if prev > 0 else 0
            items.append({
                "apt_name": r[0], "dong_name": r[1],
                "exclusive_area": r[2], "deal_amount": r[3],
                "deal_date": f"{r[4]}-{r[5]:02d}-{r[6]:02d}",
                "floor": r[7], "build_year": r[8],
                "prev_high": prev,
                "increase_rate": increase_rate
            })
        # 신고가 판정은 수집된 기간 안에서의 최고가 기준이므로 그 범위를 함께 알려준다
        return {
            "city_code": city_code,
            "items": items,
            "coverage": get_collected_period("transactions", city_code) or {},
        }
    except Exception:
        logger.exception("New-highs request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/stations")
async def get_stations():
    if not STATIONS_DATA:
        # Retry loading once if memory is empty
        load_global_data()
    return STATIONS_DATA

@app.post("/api/optimize")
def optimize_location(request: OptimizeRequest, http_request: Request):
    if not _check_optimize_rate_limit(_rate_limit_client_key(http_request)):
        raise HTTPException(status_code=429, detail="Too many optimization requests. Please retry later.")
    try:
        # 1. 날짜 및 시간 설정 (차주 월요일 기준)
        now = datetime.now()
        days_ahead = 0 - now.weekday()
        if days_ahead <= 0: days_ahead += 7
        next_monday = now + timedelta(days=days_ahead)
        # 08:00 도착을 위해 보통 07:20분경 출발하는 피크 타임 설정
        time_morning = next_monday.replace(hour=7, minute=20, second=0, microsecond=0).strftime("%Y%m%d%H%M")
        # 18:00 정시 퇴근 피크 타임 설정
        time_evening = next_monday.replace(hour=18, minute=0, second=0, microsecond=0).strftime("%Y%m%d%H%M")

        # 2. 월 주거비 예산 계산 (만원 단위)
        total_salary = request.user1.salary
        if request.mode == 'couple' and request.user2:
            total_salary += request.user2.salary
        max_housing_budget = round((total_salary * 10000 / 12) * request.housing_ratio / 10000)
        
        # 2. 전역 스캐닝: 조건에 맞는 모든 단지 로드
        min_build_year = 0
        if request.max_building_age > 0:
            min_build_year = datetime.now().year - request.max_building_age

        # 최근 12개월 거래만 집계 (연/월을 개월 수로 환산해 비교)
        min_month_index = (now.year * 12 + now.month) - 12

        # 집계와 IQR 처리는 조건별로 캐시된 결과를 쓴다 (읽기 전용 튜플)
        all_complexes = get_complex_aggregates(
            request.resident_type, request.min_area, request.max_area,
            min_build_year, min_month_index,
        )

        # 3. 직선거리 기준 후보군 추출 (Fast Scan, 상위 50개 정밀 분석)
        # 커플 모드에서 두 직장의 중간점을 쓰면 중간 지점이 강·산이라 실제로는 양쪽 모두
        # 통근이 나쁜 곳이 상위로 올라온다. 각 직장까지의 실제 거리로 후보를 고른다.
        workplaces = [(request.user1.workplace.lat, request.user1.workplace.lng)]
        if request.mode == 'couple' and request.user2:
            workplaces.append((request.user2.workplace.lat, request.user2.workplace.lng))
        
        candidates = []
        for row in all_complexes:
            apt_name, dong_name, city_code = row[0], row[1], row[2]
            avg_deposit, avg_rent, avg_area = int(row[3]), int(row[4]), row[5]
            
            # 월 주거비용 계산 (보유 자금이 있으면 대출 이자 모델 적용)
            monthly_housing_cost = calculate_monthly_housing_cost(
                avg_deposit, avg_rent, request.available_cash, request.resident_type
            )
            if max_housing_budget > 0 and monthly_housing_cost > max_housing_budget:
                continue

            # 좌표 정보 획득 (동 좌표 기반)
            dong_key = f"{city_code}_{dong_name}"
            lat, lng = None, None
            
            if dong_key in DONG_COORDS:
                coord = DONG_COORDS[dong_key]
                lat, lng = coord['lat'], coord['lng']
            else:
                # 동 좌표가 없으면 구(city_code) 중심 좌표로 대체한다.
                # 사전순 첫 동을 쓰던 방식은 구 경계 쪽으로 크게 치우쳐
                # 통근 시간과 최근접역이 실제와 어긋났다.
                center = DISTRICT_CENTERS.get(city_code)
                if center:
                    lat, lng = center['lat'], center['lng']
            
            if not lat:
                continue # 여전히 좌표 정보 없으면 제외

            dist_score, work_distances = candidate_distance_score(lat, lng, workplaces)
            if max(work_distances) > 80: continue  # 어느 한쪽이라도 너무 멀면 제외 (수도권 광역 80km)

            candidates.append({
                "name": apt_name, "dong": dong_name, "city_code": city_code,
                "lat": lat, "lng": lng, "monthly_housing_cost": monthly_housing_cost,
                "dist_score": dist_score, "avg_deposit": avg_deposit, "avg_rent": avg_rent,
                "avg_area": avg_area
            })

        # 직장에서 가까운 순으로 1차 후보군 선별
        candidates.sort(key=lambda x: x['dist_score'])
        top_candidates = candidates[:CANDIDATE_SCAN_LIMIT]

        results = []
        base_transport_cost = 10 # 기본 교통비

        # 성향 가중치 (1차 스크리닝과 최종 점수에 동일하게 적용)
        w_fixed, w_hidden = 1.0, 1.0
        if request.preference == 'money': w_fixed, w_hidden = 1.6, 0.4
        elif request.preference == 'time': w_fixed, w_hidden = 0.4, 1.6

        profiles = [request.user1]
        if request.mode == 'couple' and request.user2:
            profiles.append(request.user2)

        # 3-1. 1차 스크리닝: 외부 API 없이 거리 기반 추정으로 점수를 매겨 정밀 분석 대상을 좁힌다.
        # 후보 50곳을 모두 정밀 분석하면 지오코딩·경로 API를 요청당 최대 200회 호출하게 되어
        # 응답이 분 단위로 늘고 API 쿼터도 금방 소진된다.
        screened = []
        for spot in top_candidates:
            estimated_times = []
            for (w_lat, w_lng), profile in zip(workplaces, profiles):
                morning, _ = estimate_commute(spot['lat'], spot['lng'], w_lat, w_lng, profile.transport, 8)
                evening, _ = estimate_commute(w_lat, w_lng, spot['lat'], spot['lng'], profile.transport, 18)
                estimated_times.append((morning + evening) // 2)
            estimated_hidden = sum(
                calculate_hidden_life_cost(profile.salary, minutes)
                for profile, minutes in zip(profiles, estimated_times)
            )
            estimated_fixed = spot['monthly_housing_cost'] + base_transport_cost
            screened.append((estimated_fixed * w_fixed + estimated_hidden * w_hidden, spot))

        screened.sort(key=lambda item: item[0])
        finalists = [spot for _, spot in screened[:PRECISE_ANALYSIS_LIMIT]]

        # 3-2. 정밀 분석: 좁혀진 후보만 실제 좌표·경로 API로 계산한다.
        def measure_commute(spot):
            """한 후보의 정밀 좌표와 출퇴근 소요시간을 구한다 (후보 간 독립적이라 병렬 실행)."""
            precise_lat, precise_lng = get_precise_coordinates(CACHE_DB_PATH, spot['name'], spot['dong'], spot['city_code'])
            # 단지 좌표를 못 얻으면 법정동·구 중심 좌표가 그대로 남는다.
            # 클라이언트가 자체 좌표 보정을 할지 판단할 수 있게 구분해 둔다.
            spot['coord_precise'] = bool(precise_lat and precise_lng)
            if spot['coord_precise']:
                spot['lat'], spot['lng'] = precise_lat, precise_lng

            times = []
            for (w_lat, w_lng), profile in zip(workplaces, profiles):
                # 출근: 08:00 도착 시뮬레이션 / 퇴근: 18:00 정시 출발
                morning, _ = get_kakao_commute(CACHE_DB_PATH, spot['lat'], spot['lng'], w_lat, w_lng,
                                               profile.transport, goal_arrive_time="0800")
                evening, _ = get_kakao_commute(CACHE_DB_PATH, w_lat, w_lng, spot['lat'], spot['lng'],
                                               profile.transport, departure_time=time_evening)
                times.append((morning, evening))
            return spot, times

        with ThreadPoolExecutor(max_workers=min(PRECISE_ANALYSIS_WORKERS, max(1, len(finalists)))) as pool:
            measured = list(pool.map(measure_commute, finalists))

        for spot, commute_times in measured:
            morning_time1, evening_time1 = commute_times[0]
            avg_time1 = (morning_time1 + evening_time1) // 2

            morning_time2, evening_time2, avg_time2 = 0, 0, 0
            if len(commute_times) > 1:
                morning_time2, evening_time2 = commute_times[1]
                avg_time2 = (morning_time2 + evening_time2) // 2

            # 기회비용 계산 (평균 시간 기준)
            hidden_cost1 = calculate_hidden_life_cost(request.user1.salary, avg_time1)
            hidden_cost2 = calculate_hidden_life_cost(request.user2.salary, avg_time2) if request.mode == 'couple' and request.user2 else 0
            
            # 성향 가중치 적용
            fixed_monthly_exp = spot['monthly_housing_cost'] + base_transport_cost
            total_hidden_life_cost = hidden_cost1 + hidden_cost2
            
            weighted_score = int(fixed_monthly_exp * w_fixed + total_hidden_life_cost * w_hidden)
            total_opp_cost = fixed_monthly_exp + total_hidden_life_cost

            nearest_stations = get_nearest_stations(spot['lat'], spot['lng'])
            if request.resident_type == 'buy':
                price_label = "매매"
            else:
                price_label = "전세" if spot['avg_rent'] == 0 else "월세"
            results.append({
                "name": spot['name'], "lat": spot['lat'], "lng": spot['lng'],
                "coord_precise": spot['coord_precise'],
                "nearest_stations": nearest_stations,
                "dong": spot['dong'],
                "total_cost": total_opp_cost,
                "commute_time_1": avg_time1,
                "commute_morning_1": morning_time1,
                "commute_evening_1": evening_time1,
                "commute_time_2": avg_time2,
                "commute_morning_2": morning_time2,
                "commute_evening_2": evening_time2,
                "complexes": [{
                    "name": spot['name'], "dong": spot['dong'], "rent_type": price_label,
                    "display_price_label": price_label,
                    "display_price_value": (
                        f"{format_price_kr(spot['avg_deposit'])} / 월 {spot['avg_rent']:,}만"
                        if spot['avg_rent'] > 0 else format_price_kr(spot['avg_deposit'])
                    ),
                    "fixed_monthly_exp": fixed_monthly_exp,
                    "hidden_life_cost": total_hidden_life_cost,
                    "total_opp_cost": total_opp_cost,
                    "avg_area": spot['avg_area'],
                    "loan_amount": max(0, spot['avg_deposit'] - request.available_cash) if request.available_cash > 0 else 0,
                    "loan_monthly": round(
                        max(0, spot['avg_deposit'] - request.available_cash)
                        * (MORTGAGE_RATE if request.resident_type == 'buy' else JEONSE_LOAN_RATE) / 12
                    ) if request.available_cash > 0 else 0,
                }],
                "score": weighted_score
            })

        # 최종 가성비 순으로 정렬 (같은 동이 결과를 독점하지 않도록 추려냄)
        results.sort(key=lambda x: x['score'])
        return {
            "results": diversify_results(results),
            "meta": {
                # 카카오 REST 키가 없으면 소요시간·좌표가 모두 추정값이므로 클라이언트가 그대로 안내한다
                "realtime_routing": is_realtime_routing_available(),
                "resident_type": request.resident_type,
            },
        }
    except Exception:
        logger.exception("Optimize request failed")
        raise HTTPException(status_code=500, detail="Internal server error")

# --- Static Frontend Serving ---
# mount("/")가 API 라우트 이후의 모든 경로를 처리하므로 별도 catchall 라우트는 불필요
if os.path.exists(FRONTEND_DIST):
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
