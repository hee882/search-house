import hashlib
import inspect
import logging
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from fastapi.testclient import TestClient
from starlette.requests import Request


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import main
from lib import kakao_api


CITY_CODE = "11680"
DONG_COORDS = {f"{CITY_CODE}_역삼동": {"lat": 37.5, "lng": 127.03}}
DISTRICT_CENTERS = {CITY_CODE: {"lat": 37.49, "lng": 127.06}}

_module_patchers = []
# 키를 가려도 호출이 새는 경우를 놓치지 않도록, 카카오 HTTP 호출 시도를 모듈 단위로 기록한다
kakao_http_calls = mock.Mock(side_effect=AssertionError("테스트 중에는 카카오 API 를 호출하면 안 된다"))


def setUpModule():
    """이 모듈이 실행되는 동안 카카오 REST 키를 가린다.

    개발자 PC 에는 server/.env 에 실제 키가 있어, 가리지 않으면 /api/optimize 테스트가
    카카오 지오코딩을 실제로 호출한다. 테스트 안에서 키를 따로 패치하는 것은 그대로 동작한다.
    """
    _module_patchers.append(mock.patch.object(kakao_api, "KAKAO_REST_API_KEY", None))
    if hasattr(kakao_api, "_http_get"):
        _module_patchers.append(mock.patch.object(kakao_api, "_http_get", kakao_http_calls))
    for patcher in _module_patchers:
        patcher.start()


def tearDownModule():
    while _module_patchers:
        _module_patchers.pop().stop()
    if kakao_http_calls.call_count:
        # 헤더에는 인증 키가 들어 있으므로 주소만 남긴다
        urls = sorted({call.args[0] for call in kakao_http_calls.call_args_list if call.args})
        raise AssertionError(f"카카오 API 호출이 {kakao_http_calls.call_count}번 시도됐다: {urls}")


def recent_month_index():
    """optimize 가 집계 하한으로 쓰는 값 (최근 12개월)."""
    now = datetime.now()
    return now.year * 12 + now.month - 12


def rent_rows(apt_name, dong_name, deposits, area=59.0, monthly_rent=0, contract_type=None):
    """이번 달 거래로 넣어 최근 12개월 조건에 항상 걸리게 한다."""
    now = datetime.now()
    return [
        (CITY_CODE, dong_name, apt_name, area, now.year, now.month, day,
         deposit, monthly_rent, 5, 2015, contract_type)
        for day, deposit in enumerate(deposits, start=1)
    ]


def create_rent_db(db_path, rows):
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rent_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, city_code TEXT, dong_name TEXT, apt_name TEXT,
            exclusive_area REAL, deal_year INTEGER, deal_month INTEGER, deal_day INTEGER,
            deposit INTEGER, monthly_rent INTEGER, floor INTEGER, build_year INTEGER,
            contract_type TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO rent_transactions (city_code, dong_name, apt_name, exclusive_area, deal_year,"
        " deal_month, deal_day, deposit, monthly_rent, floor, build_year, contract_type)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


def create_transactions_db(db_path, rows):
    """rows: (id, city_code, apt_name, dong_name, area, amount, year, month, day, cancel, is_new_high[, apt_seq])

    apt_seq 를 생략하면 NULL 로 들어가 단지명 기준으로 묶이는 행이 된다.
    """
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY, city_code TEXT, apt_name TEXT, dong_name TEXT,
            exclusive_area REAL, deal_amount INTEGER, deal_year INTEGER, deal_month INTEGER,
            deal_day INTEGER, cancel_deal_day TEXT, is_new_high_price INTEGER DEFAULT 0,
            apt_seq TEXT,
            floor INTEGER DEFAULT 5, build_year INTEGER DEFAULT 2015, buyer_type TEXT
        )
        """
    )
    # 실제 DB 와 같은 인덱스를 둬 조회가 같은 경로로 실행되게 한다
    conn.execute("CREATE INDEX idx_new_high ON transactions(apt_seq, exclusive_area, deal_amount)")
    conn.executemany(
        "INSERT INTO transactions (id, city_code, apt_name, dong_name, exclusive_area, deal_amount,"
        " deal_year, deal_month, deal_day, cancel_deal_day, is_new_high_price, apt_seq)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [tuple(row) + (None,) * (12 - len(row)) for row in rows],
    )
    conn.commit()
    conn.close()


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reset_runtime_state():
    """테스트끼리 집계 캐시와 요청 제한 기록을 공유하지 않게 한다."""
    with main._aggregate_cache_lock:
        main._aggregate_cache.clear()
    with main._optimize_rate_lock:
        main._optimize_rate.clear()


class FakeClock:
    """main 이 참조하는 time 모듈 자리에 끼워 TTL 경과를 흉내 낸다."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now


class RateLimitClientKeyTests(TestCase):
    SOCKET = "10.0.0.9"

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app, raise_server_exceptions=False)

    def setUp(self):
        reset_runtime_state()

    def _request(self, forwarded_lines=()):
        return Request({
            "type": "http", "method": "POST", "path": "/api/optimize", "query_string": b"",
            "headers": [(b"x-forwarded-for", line.encode()) for line in forwarded_lines],
            "client": (self.SOCKET, 50000),
        })

    def _key(self, hops, forwarded_lines=()):
        with mock.patch.object(main, "TRUSTED_PROXY_HOPS", hops):
            return main._rate_limit_client_key(self._request(forwarded_lines))

    def test_zero_hops_ignores_forwarded_header(self):
        self.assertEqual(self._key(0, ["1.2.3.4, 203.0.113.7"]), self.SOCKET)

    def test_one_hop_uses_rightmost_entry(self):
        self.assertEqual(self._key(1, ["1.2.3.4, 198.51.100.2, 203.0.113.7"]), "203.0.113.7")

    def test_two_hops_uses_second_entry_from_right(self):
        self.assertEqual(self._key(2, ["1.2.3.4, 198.51.100.2, 203.0.113.7"]), "198.51.100.2")

    def test_missing_header_falls_back_to_socket_address(self):
        self.assertEqual(self._key(0), self.SOCKET)
        self.assertEqual(self._key(1), self.SOCKET)
        self.assertEqual(self._key(2), self.SOCKET)

    def test_too_few_entries_fall_back_to_socket_address(self):
        self.assertEqual(self._key(2, ["203.0.113.7"]), self.SOCKET)
        self.assertEqual(self._key(1, ["  "]), self.SOCKET)

    def test_client_supplied_left_values_cannot_change_key(self):
        honest = self._key(1, ["203.0.113.7"])
        spoofed = self._key(1, ["9.9.9.9, 8.8.8.8, 203.0.113.7"])
        self.assertEqual(honest, spoofed)

    def test_separate_header_lines_are_read_as_one_list(self):
        # 클라이언트가 보낸 줄 뒤에 프록시가 새 줄을 덧붙이는 경우
        self.assertEqual(self._key(1, ["9.9.9.9", "203.0.113.7"]), "203.0.113.7")

    def test_missing_socket_address_is_reported_as_unknown(self):
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": [], "client": None})
        with mock.patch.object(main, "TRUSTED_PROXY_HOPS", 0):
            self.assertEqual(main._rate_limit_client_key(request), "unknown")

    def _post(self, forwarded):
        payload = {
            "user1": {
                "workplace": {"lat": 37.5, "lng": 127.0, "name": "Office"},
                "salary": 5000,
                "transport": "public",
            },
        }
        return self.client.post("/api/optimize", json=payload, headers={"X-Forwarded-For": forwarded})

    def test_clients_behind_proxy_get_separate_limits(self):
        with mock.patch.object(main, "TRUSTED_PROXY_HOPS", 1), \
                mock.patch.object(main, "OPTIMIZE_RATE_MAX_REQUESTS", 1), \
                mock.patch.object(main, "get_complex_aggregates", return_value=()):
            self.assertEqual(self._post("203.0.113.7").status_code, 200)
            self.assertEqual(self._post("203.0.113.7").status_code, 429)
            self.assertEqual(self._post("203.0.113.8").status_code, 200)

    def test_without_trusted_proxy_all_requests_share_socket_limit(self):
        with mock.patch.object(main, "TRUSTED_PROXY_HOPS", 0), \
                mock.patch.object(main, "OPTIMIZE_RATE_MAX_REQUESTS", 1), \
                mock.patch.object(main, "get_complex_aggregates", return_value=()):
            self.assertEqual(self._post("203.0.113.7").status_code, 200)
            self.assertEqual(self._post("203.0.113.8").status_code, 429)


class NewHighStatsTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app, raise_server_exceptions=False)

    def _new_highs(self, rows):
        with TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "stats.db")
            create_transactions_db(db_path, rows)
            with mock.patch.object(main, "DB_PATH", db_path):
                response = self.client.get("/api/stats/new-highs", params={"city_code": CITY_CODE})
        self.assertEqual(response.status_code, 200)
        return response.json()["items"]

    def test_prev_high_follows_deal_date_not_collection_order(self):
        items = self._new_highs([
            # 먼저 수집됐지만(id 가 작지만) 거래일은 더 늦은 거래 → 이전 거래가 아니다
            (2, CITY_CODE, "A", "D", 84, 59000, 2025, 8, 1, None, 0),
            (5, CITY_CODE, "A", "D", 84, 60000, 2025, 6, 15, None, 1),
            # 과거 월을 재수집해 나중 id 가 붙었지만 거래일은 더 이른 거래 → 이전 거래다
            (9, CITY_CODE, "A", "D", 84, 55000, 2025, 3, 10, None, 0),
        ])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["deal_date"], "2025-06-15")
        self.assertEqual(items[0]["prev_high"], 55000)
        self.assertEqual(items[0]["increase_rate"], 9.09)

    def test_prev_high_ignores_other_districts_and_cancelled_deals(self):
        items = self._new_highs([
            (1, CITY_CODE, "A", "D", 84, 55000, 2025, 3, 10, None, 0),
            # 단지명·동명·면적이 같은 다른 구의 거래
            (2, "11650", "A", "D", 84, 99000, 2025, 1, 5, None, 0),
            # 해제된 거래는 시세가 아니다
            (3, CITY_CODE, "A", "D", 84, 58000, 2025, 4, 1, "25.04.20", 0),
            (4, CITY_CODE, "A", "D", 84, 60000, 2025, 6, 15, None, 1),
        ])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["prev_high"], 55000)

    def test_same_day_deal_is_not_a_previous_deal(self):
        items = self._new_highs([
            (1, CITY_CODE, "A", "D", 84, 58000, 2025, 6, 15, None, 0),
            (2, CITY_CODE, "A", "D", 84, 60000, 2025, 6, 15, None, 1),
        ])
        self.assertEqual(items[0]["prev_high"], 0)
        self.assertEqual(items[0]["increase_rate"], 0)

    def test_prev_high_follows_apt_seq_when_complex_name_differs(self):
        items = self._new_highs([
            # 같은 단지(apt_seq)인데 단지명 표기만 다른 이전 거래
            (1, CITY_CODE, "래미안", "D", 84, 55000, 2025, 3, 10, None, 0, "11680-100"),
            # 단지명 표기는 같지만 apt_seq 가 다른 단지
            (2, CITY_CODE, "래미안(101동)", "D", 84, 58000, 2025, 4, 1, None, 0, "11680-999"),
            # 단지명 표기는 같지만 apt_seq 가 없는 거래 (수집기에서도 다른 묶음이다)
            (3, CITY_CODE, "래미안(101동)", "D", 84, 57000, 2025, 4, 2, None, 0),
            (4, CITY_CODE, "래미안(101동)", "D", 84, 60000, 2025, 6, 15, None, 1, "11680-100"),
        ])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["apt_name"], "래미안(101동)")
        self.assertEqual(items[0]["prev_high"], 55000)
        self.assertEqual(items[0]["increase_rate"], 9.09)

    def test_prev_high_with_apt_seq_keeps_area_date_and_cancel_rules(self):
        items = self._new_highs([
            (1, CITY_CODE, "A", "D", 84, 55000, 2025, 3, 10, None, 0, "11680-100"),
            (2, CITY_CODE, "A", "D", 59, 59000, 2025, 3, 11, None, 0, "11680-100"),       # 다른 면적
            (3, CITY_CODE, "A", "D", 84, 58000, 2025, 4, 1, "25.04.20", 0, "11680-100"),  # 해제
            (4, CITY_CODE, "A", "D", 84, 57000, 2025, 6, 15, None, 0, "11680-100"),       # 같은 날
            (5, CITY_CODE, "A", "D", 84, 59500, 2025, 8, 1, None, 0, "11680-100"),        # 더 늦은 거래
            (6, CITY_CODE, "A", "D", 84, 60000, 2025, 6, 15, None, 1, "11680-100"),
        ])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["prev_high"], 55000)

    def test_prev_high_without_apt_seq_matches_city_dong_and_name(self):
        items = self._new_highs([
            # apt_seq 가 빈 문자열인 행과 NULL 인 행은 같은 묶음이다
            (1, CITY_CODE, "A", "D", 84, 55000, 2025, 3, 10, None, 0, ""),
            # 이름은 같지만 apt_seq 가 붙은 거래는 apt_seq 기준 묶음에 속한다
            (2, CITY_CODE, "A", "D", 84, 58000, 2025, 4, 1, None, 0, "11680-100"),
            # 구·동·단지명 중 하나라도 다르면 다른 단지다
            (3, "11650", "A", "D", 84, 99000, 2025, 1, 5, None, 0),
            (4, CITY_CODE, "A", "E", 84, 98000, 2025, 1, 6, None, 0),
            (5, CITY_CODE, "B", "D", 84, 97000, 2025, 1, 7, None, 0),
            (6, CITY_CODE, "A", "D", 84, 60000, 2025, 6, 15, None, 1),
        ])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["prev_high"], 55000)

    def test_prev_high_agrees_with_collector_new_high_definition(self):
        import collector
        if not hasattr(collector, "recompute_new_high_flags"):
            self.skipTest("수집기에 신고가 재계산 함수가 없는 버전")

        rows = [
            # apt_seq 기준 단지: 표기가 다른 이름이 섞여 있다
            (1, CITY_CODE, "래미안", "D", 84, 50000, 2025, 1, 10, None, 0, "11680-100"),
            (2, CITY_CODE, "래미안(101동)", "D", 84, 52000, 2025, 2, 10, None, 0, "11680-100"),
            (3, CITY_CODE, "래미안", "D", 84, 51000, 2025, 3, 10, None, 0, "11680-100"),
            (4, CITY_CODE, "래미안(101동)", "D", 84, 56000, 2025, 4, 10, "25.04.30", 0, "11680-100"),
            (5, CITY_CODE, "래미안", "D", 84, 54000, 2025, 5, 10, None, 0, "11680-100"),
            # 단지명 기준 단지: 같은 이름에 apt_seq 가 붙은 거래가 끼어 있다
            (6, CITY_CODE, "은마", "D", 76, 30000, 2025, 1, 5, None, 0),
            (7, CITY_CODE, "은마", "D", 76, 40000, 2025, 2, 5, None, 0, "11680-200"),
            # 같은 날 거래는 서로 비교하지 않으므로 둘 다 직전 최고가(30000)를 넘긴 신고가다
            (8, CITY_CODE, "은마", "D", 76, 33000, 2025, 3, 5, None, 0, ""),
            (9, CITY_CODE, "은마", "D", 76, 32000, 2025, 3, 5, None, 0),
            (10, CITY_CODE, "은마", "D", 76, 35000, 2025, 4, 5, None, 0),
        ]
        with TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "stats.db")
            create_transactions_db(db_path, rows)
            conn = sqlite3.connect(db_path)
            collector.recompute_new_high_flags(conn)
            conn.commit()
            flagged = {row[0] for row in conn.execute(
                "SELECT deal_amount FROM transactions WHERE is_new_high_price = 1")}
            conn.close()
            with mock.patch.object(main, "DB_PATH", db_path):
                response = self.client.get("/api/stats/new-highs", params={"city_code": CITY_CODE})

        items = {item["deal_amount"]: item["prev_high"] for item in response.json()["items"]}
        self.assertEqual(set(items), flagged)
        # 수집기가 신고가로 판정했다면 같은 묶음에 더 싼 이전 거래가 반드시 있다
        self.assertEqual(
            items, {52000: 50000, 54000: 52000, 33000: 30000, 32000: 30000, 35000: 33000})

    def test_new_high_count_excludes_cancelled_deals(self):
        with TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "stats.db")
            create_transactions_db(db_path, [
                (1, CITY_CODE, "A", "D", 84, 60000, 2026, 5, 3, None, 1),
                (2, CITY_CODE, "B", "D", 84, 70000, 2026, 5, 7, "26.05.20", 1),
                (3, CITY_CODE, "C", "D", 84, 50000, 2026, 5, 9, "", 0),
            ])
            with mock.patch.object(main, "DB_PATH", db_path):
                response = self.client.get(
                    "/api/stats/transactions",
                    params={"city_code": CITY_CODE, "year": 2026, "month": 5},
                )
        self.assertEqual(response.status_code, 200)
        summary = response.json()["summary"]
        self.assertEqual(summary["new_high_count"], 1)
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["cancel_count"], 1)
        # 일별 합계와 같은 기준이어야 한다
        self.assertEqual(sum(day["new_high"] for day in response.json()["daily"]), 1)

    def test_stats_endpoints_run_in_threadpool(self):
        # 동기 sqlite3 호출이 이벤트 루프를 막지 않으려면 코루틴이 아니어야 한다
        self.assertFalse(inspect.iscoroutinefunction(main.get_transaction_stats))
        self.assertFalse(inspect.iscoroutinefunction(main.get_new_highs))


class ComplexAggregateCacheTests(TestCase):
    def setUp(self):
        reset_runtime_state()
        self.addCleanup(reset_runtime_state)
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = str(Path(self._tmp.name) / "deals.db")
        self.clock = FakeClock()
        for target, value in (
            ("DB_PATH", self.db_path),
            ("time", self.clock),
            ("OPTIMIZE_AGGREGATE_TTL_SECONDS", 600),
            # 실제 DB 의 컬럼 상태와 무관하게 동작을 고정한다
            ("RENT_HAS_CONTRACT_TYPE", False),
        ):
            patcher = mock.patch.object(main, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _aggregate(self, min_area=40, resident_type="jeonse"):
        return main.get_complex_aggregates(resident_type, min_area, 85, 0, recent_month_index())

    def _count_db_queries(self):
        return mock.patch.object(main.sqlite3, "connect", wraps=sqlite3.connect)

    def test_second_call_with_same_conditions_skips_database(self):
        create_rent_db(self.db_path, rent_rows("단지A", "역삼동", [30000, 30000, 30000]))
        with self._count_db_queries() as connect:
            first = self._aggregate()
            self.assertEqual(connect.call_count, 1)
            second = self._aggregate()
            self.assertEqual(connect.call_count, 1)
        self.assertIs(first, second)
        self.assertEqual([row[:4] for row in first], [("단지A", "역삼동", CITY_CODE, 30000)])

    def test_expired_entry_is_queried_again(self):
        create_rent_db(self.db_path, rent_rows("단지A", "역삼동", [30000, 30000, 30000]))
        with self._count_db_queries() as connect:
            self._aggregate()
            self.clock.now += 599
            self._aggregate()
            self.assertEqual(connect.call_count, 1)
            self.clock.now += 2
            self._aggregate()
            self.assertEqual(connect.call_count, 2)
            # 다시 채운 항목은 그 시점부터 TTL 을 새로 센다
            self.clock.now += 599
            self._aggregate()
            self.assertEqual(connect.call_count, 2)

    def test_new_deals_appear_only_after_ttl(self):
        create_rent_db(self.db_path, rent_rows("단지A", "역삼동", [30000, 30000, 30000]))
        self.assertEqual(self._aggregate()[0][3], 30000)

        create_rent_db(self.db_path, rent_rows("단지A", "역삼동", [36000, 36000, 36000]))
        self.assertEqual(self._aggregate()[0][3], 30000)

        self.clock.now += 601
        self.assertEqual(self._aggregate()[0][3], 33000)

    def test_conditions_are_cached_separately(self):
        create_rent_db(
            self.db_path,
            rent_rows("전세단지", "역삼동", [30000, 30000, 30000])
            + rent_rows("월세단지", "역삼동", [5000, 5000, 5000], monthly_rent=80)
            + rent_rows("소형단지", "역삼동", [20000, 20000, 20000], area=33.0),
        )
        with self._count_db_queries() as connect:
            jeonse = self._aggregate()
            wolse = self._aggregate(resident_type="wolse")
            small = self._aggregate(min_area=30)
            self.assertEqual(connect.call_count, 3)
        self.assertEqual({row[0] for row in jeonse}, {"전세단지"})
        self.assertEqual({row[0] for row in wolse}, {"월세단지"})
        self.assertEqual({row[0] for row in small}, {"전세단지", "소형단지"})

    def test_cache_is_isolated_by_database_path(self):
        create_rent_db(self.db_path, rent_rows("단지A", "역삼동", [30000, 30000, 30000]))
        other_db = str(Path(self._tmp.name) / "other.db")
        create_rent_db(other_db, rent_rows("단지B", "역삼동", [40000, 40000, 40000]))

        first = self._aggregate()
        with mock.patch.object(main, "DB_PATH", other_db):
            second = self._aggregate()
        self.assertEqual(first[0][0], "단지A")
        self.assertEqual(second[0][0], "단지B")

    def test_cache_is_isolated_by_contract_type_support(self):
        create_rent_db(
            self.db_path,
            rent_rows("단지A", "역삼동", [30000, 30000, 30000], contract_type="신규")
            + rent_rows("단지A", "역삼동", [20000, 20000, 20000], contract_type="갱신"),
        )
        self.assertEqual(self._aggregate()[0][3], 25000)
        with mock.patch.object(main, "RENT_HAS_CONTRACT_TYPE", True):
            self.assertEqual(self._aggregate()[0][3], 30000)
        self.assertEqual(self._aggregate()[0][3], 25000)

    def test_cached_result_cannot_be_modified_by_caller(self):
        create_rent_db(self.db_path, rent_rows("단지A", "역삼동", [30000, 30000, 30000]))
        result = self._aggregate()
        self.assertIsInstance(result, tuple)
        self.assertTrue(all(isinstance(row, tuple) for row in result))

    def test_relaxed_sample_retry_is_kept(self):
        # 대표 면적대(59㎡) 거래가 2건뿐이라 min_samples=3 으로는 결과가 비는 경우
        create_rent_db(
            self.db_path,
            rent_rows("단지A", "역삼동", [30000, 32000]) + rent_rows("단지A", "역삼동", [50000], area=84.0),
        )
        self.assertEqual(main._filter_complexes_by_iqr(
            main._query_complex_rows("jeonse", 40, 85, 0, recent_month_index()), min_samples=3), [])
        result = self._aggregate()
        self.assertEqual([row[:4] for row in result], [("단지A", "역삼동", CITY_CODE, 31000)])

    def _limit_loaded_with_env(self, value):
        """상한은 모듈을 불러올 때 한 번 읽으므로 새 프로세스에서 확인한다."""
        result = subprocess.run(
            [sys.executable, "-c", "import main; print(main.OPTIMIZE_AGGREGATE_MAX_ENTRIES)"],
            cwd=str(SERVER_DIR),
            env=dict(os.environ, OPTIMIZE_AGGREGATE_MAX_ENTRIES=value,
                     PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8"),
            capture_output=True, encoding="utf-8", errors="replace", timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return int(result.stdout.split()[-1])

    def test_default_entry_limit_is_sixteen(self):
        if "OPTIMIZE_AGGREGATE_MAX_ENTRIES" in os.environ:
            self.skipTest("환경변수나 .env 로 상한을 직접 지정한 환경")
        self.assertEqual(main.OPTIMIZE_AGGREGATE_MAX_ENTRIES, 16)

    def test_entry_count_is_bounded(self):
        limit = main.OPTIMIZE_AGGREGATE_MAX_ENTRIES
        create_rent_db(self.db_path, rent_rows("단지A", "역삼동", [30000, 30000, 30000]))
        for min_area in range(1, limit + 7):
            self._aggregate(min_area=min_area)
        self.assertEqual(len(main._aggregate_cache), limit)

        with self._count_db_queries() as connect:
            self._aggregate(min_area=limit + 6)   # 가장 최근 항목은 남아 있다
            self.assertEqual(connect.call_count, 0)
            self._aggregate(min_area=1)           # 가장 오래된 항목은 밀려났다
            self.assertEqual(connect.call_count, 1)
        self.assertEqual(len(main._aggregate_cache), limit)

    def test_entry_limit_follows_environment_and_evicts_oldest(self):
        limit = self._limit_loaded_with_env("3")
        self.assertEqual(limit, 3)

        create_rent_db(self.db_path, rent_rows("단지A", "역삼동", [30000, 30000, 30000]))
        with mock.patch.object(main, "OPTIMIZE_AGGREGATE_MAX_ENTRIES", limit):
            for min_area in range(1, 6):
                self._aggregate(min_area=min_area)
            self.assertEqual(len(main._aggregate_cache), 3)

            with self._count_db_queries() as connect:
                for min_area in (3, 4, 5):       # 나중에 넣은 항목은 남아 있다
                    self._aggregate(min_area=min_area)
                self.assertEqual(connect.call_count, 0)
                for min_area in (1, 2):          # 먼저 넣은 항목부터 밀려났다
                    self._aggregate(min_area=min_area)
                self.assertEqual(connect.call_count, 2)
            self.assertEqual(len(main._aggregate_cache), 3)

    def test_entry_limit_is_at_least_one(self):
        self.assertEqual(self._limit_loaded_with_env("0"), 1)

    def test_expired_entries_are_dropped_before_fresh_ones(self):
        create_rent_db(self.db_path, rent_rows("단지A", "역삼동", [30000, 30000, 30000]))
        with mock.patch.object(main, "OPTIMIZE_AGGREGATE_MAX_ENTRIES", 3):
            self._aggregate(min_area=1)
            self.clock.now += 601
            for min_area in (2, 3, 4):
                self._aggregate(min_area=min_area)
            # 만료된 1번만 버리면 상한 안에 들어오므로 나머지는 모두 남는다
            with self._count_db_queries() as connect:
                for min_area in (2, 3, 4):
                    self._aggregate(min_area=min_area)
                self.assertEqual(connect.call_count, 0)

    def test_zero_ttl_disables_cache(self):
        create_rent_db(self.db_path, rent_rows("단지A", "역삼동", [30000, 30000, 30000]))
        with mock.patch.object(main, "OPTIMIZE_AGGREGATE_TTL_SECONDS", 0), \
                self._count_db_queries() as connect:
            self._aggregate()
            self._aggregate()
            self.assertEqual(connect.call_count, 2)
        self.assertEqual(len(main._aggregate_cache), 0)


class KakaoIsolationTests(TestCase):
    REST_LIKE_KEY = "0123456789abcdef0123456789abcdef"

    def test_rest_key_is_hidden_while_module_runs(self):
        self.assertIsNone(kakao_api.KAKAO_REST_API_KEY)
        self.assertFalse(kakao_api.is_realtime_routing_available())

    def test_key_patched_inside_a_test_still_applies(self):
        with mock.patch.object(kakao_api, "KAKAO_REST_API_KEY", self.REST_LIKE_KEY):
            self.assertTrue(kakao_api.is_realtime_routing_available())
        self.assertIsNone(kakao_api.KAKAO_REST_API_KEY)

    def test_geocoding_and_routing_skip_http_without_key(self):
        before = kakao_http_calls.call_count
        with TemporaryDirectory() as tmp:
            cache_path = str(Path(tmp) / "cache.db")
            coords = kakao_api.get_precise_coordinates(cache_path, "단지A", "역삼동", CITY_CODE)
            duration, _ = kakao_api.get_kakao_commute(
                cache_path, 37.5, 127.03, 37.5665, 126.978,
                transport_mode="car", goal_arrive_time="0800",
            )
        self.assertEqual(coords, (None, None))
        self.assertGreater(duration, 0)
        self.assertEqual(kakao_http_calls.call_count, before)


class OptimizeRuntimeTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app, raise_server_exceptions=False)

    def setUp(self):
        reset_runtime_state()
        self.addCleanup(reset_runtime_state)
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_path = str(Path(self._tmp.name) / "deals.db")
        self.cache_path = str(Path(self._tmp.name) / "cache.db")
        create_rent_db(
            self.db_path,
            rent_rows("정밀단지", "역삼동", [30000, 30000, 30000])
            + rent_rows("동좌표단지", "역삼동", [31000, 31000, 31000])
            # 법정동 좌표 사전에 없는 동 → 구 중심 좌표로 대체된다
            + rent_rows("구중심단지", "없는동", [32000, 32000, 32000]),
        )
        for target, value in (
            ("DB_PATH", self.db_path),
            ("CACHE_DB_PATH", self.cache_path),
            ("DONG_COORDS", DONG_COORDS),
            ("DISTRICT_CENTERS", DISTRICT_CENTERS),
            ("RENT_HAS_CONTRACT_TYPE", False),
        ):
            patcher = mock.patch.object(main, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _optimize(self, transport="public"):
        payload = {
            "user1": {
                "workplace": {"lat": 37.5665, "lng": 126.9780, "name": "Office"},
                "salary": 6000,
                "transport": transport,
            },
            "mode": "single",
            "resident_type": "jeonse",
            "housing_ratio": 0.3,
            "min_area": 40,
            "max_area": 85,
            "preference": "balance",
        }
        response = self.client.post("/api/optimize", json=payload)
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_cache_functions_receive_cache_db_path(self):
        with mock.patch.object(main, "get_precise_coordinates", return_value=(None, None)) as geocode, \
                mock.patch.object(main, "get_kakao_commute", return_value=(30, 10.0)) as commute:
            payload = self._optimize()

        self.assertEqual(len(payload["results"]), 3)
        self.assertEqual(geocode.call_count, 3)
        self.assertEqual(commute.call_count, 6)
        for call in geocode.call_args_list + commute.call_args_list:
            self.assertEqual(call.args[0], self.cache_path)
            self.assertNotEqual(call.args[0], main.DB_PATH)

    def test_deal_database_file_is_untouched_by_optimize(self):
        # 캐시 함수를 가짜로 바꾸지 않고 실제 구현을 그대로 태운다 (카카오 키는 모듈 수준에서 가려져 있다)
        before = file_digest(self.db_path)
        payload = self._optimize()

        self.assertEqual(len(payload["results"]), 3)
        self.assertEqual(file_digest(self.db_path), before)

        conn = sqlite3.connect(self.db_path)
        deal_tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        conn.close()
        self.assertNotIn("commute_cache_v3", deal_tables)
        self.assertNotIn("complex_coords_v2", deal_tables)

        conn = sqlite3.connect(self.cache_path)
        cached_routes = conn.execute("SELECT COUNT(*) FROM commute_cache_v3").fetchone()[0]
        conn.close()
        self.assertGreater(cached_routes, 0)

    def test_optimize_without_mocks_makes_no_kakao_request(self):
        # 자동차 모드는 키가 있으면 경로 API 까지 부르므로 가장 넓은 호출 경로다
        before = kakao_http_calls.call_count
        payload = self._optimize(transport="car")

        self.assertEqual(len(payload["results"]), 3)
        self.assertFalse(payload["meta"]["realtime_routing"])
        self.assertTrue(all(item["coord_precise"] is False for item in payload["results"]))
        self.assertEqual(kakao_http_calls.call_count, before)

    def test_results_report_whether_coordinates_are_precise(self):
        def geocode(db_path, apt_name, dong_name, city_code=None):
            return (37.5012, 127.0396) if apt_name == "정밀단지" else (None, None)

        with mock.patch.object(main, "get_precise_coordinates", side_effect=geocode), \
                mock.patch.object(main, "get_kakao_commute", return_value=(30, 10.0)):
            payload = self._optimize()

        results = {item["name"]: item for item in payload["results"]}
        self.assertEqual(set(results), {"정밀단지", "동좌표단지", "구중심단지"})

        self.assertIs(results["정밀단지"]["coord_precise"], True)
        self.assertEqual((results["정밀단지"]["lat"], results["정밀단지"]["lng"]), (37.5012, 127.0396))

        self.assertIs(results["동좌표단지"]["coord_precise"], False)
        self.assertEqual((results["동좌표단지"]["lat"], results["동좌표단지"]["lng"]), (37.5, 127.03))

        self.assertIs(results["구중심단지"]["coord_precise"], False)
        self.assertEqual((results["구중심단지"]["lat"], results["구중심단지"]["lng"]), (37.49, 127.06))

    def test_existing_response_fields_are_kept(self):
        with mock.patch.object(main, "get_precise_coordinates", return_value=(None, None)), \
                mock.patch.object(main, "get_kakao_commute", return_value=(30, 10.0)):
            payload = self._optimize()

        self.assertEqual(set(payload["meta"]), {"realtime_routing", "resident_type"})
        for item in payload["results"]:
            self.assertTrue({
                "name", "lat", "lng", "nearest_stations", "dong", "total_cost",
                "commute_time_1", "commute_morning_1", "commute_evening_1",
                "commute_time_2", "commute_morning_2", "commute_evening_2",
                "complexes", "score",
            }.issubset(item))
            self.assertEqual(item["complexes"][0]["display_price_label"], "전세")

    def test_repeated_request_reuses_aggregate(self):
        with mock.patch.object(main, "get_precise_coordinates", return_value=(None, None)), \
                mock.patch.object(main, "get_kakao_commute", return_value=(30, 10.0)), \
                mock.patch.object(main, "_query_complex_rows", wraps=main._query_complex_rows) as query:
            first = self._optimize()
            second = self._optimize()

        self.assertEqual(query.call_count, 1)
        self.assertEqual(first["results"], second["results"])


class CorsAndLoggingTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app, raise_server_exceptions=False)

    def _preflight(self, origin, method):
        return self.client.options(
            "/api/optimize",
            headers={"Origin": origin, "Access-Control-Request-Method": method},
        )

    def test_registered_origins_have_no_path(self):
        # Origin 헤더는 scheme://host[:port] 만 담으므로 경로가 붙은 값은 절대 일치하지 않는다
        for origin in main.origins:
            self.assertRegex(origin, r"^https?://[^/]+$")

    def test_deployed_frontend_origin_is_allowed(self):
        response = self._preflight("https://hee882.github.io", "POST")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "https://hee882.github.io")

    def test_unused_methods_are_not_allowed(self):
        allowed = self._preflight("https://hee882.github.io", "POST").headers["access-control-allow-methods"]
        self.assertEqual({m.strip() for m in allowed.split(",")}, {"GET", "POST", "OPTIONS"})
        self.assertEqual(self._preflight("https://hee882.github.io", "DELETE").status_code, 400)

    def test_server_log_file_is_rotated(self):
        handlers = [
            handler for handler in logging.getLogger().handlers
            if isinstance(handler, logging.FileHandler)
            and Path(handler.baseFilename).name == "server.log"
        ]
        if not handlers:
            self.skipTest("다른 모듈이 먼저 로깅을 설정해 파일 핸들러가 붙지 않은 환경")
        for handler in handlers:
            self.assertIsInstance(handler, RotatingFileHandler)
            self.assertEqual(handler.maxBytes, 5 * 1024 * 1024)
            self.assertEqual(handler.backupCount, 3)


if __name__ == "__main__":
    import unittest

    unittest.main()
