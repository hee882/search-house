import os
import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

import requests


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from lib import kakao_api


REST_KEY = "0123456789abcdef0123456789abcdef"
JAVASCRIPT_KEY = "feb433" + "0" * 26
APARTMENT = ("테스트단지", "중앙동", "11680")
COMMUTE_TABLE_SQL = """
    CREATE TABLE commute_cache_v3 (
        from_lat REAL, from_lng REAL, to_lat REAL, to_lng REAL,
        transport_mode TEXT, cache_key TEXT,
        duration_min INTEGER, distance_km REAL{extra_columns},
        PRIMARY KEY (from_lat, from_lng, to_lat, to_lng, transport_mode, cache_key)
    )
"""


def _response(status_code=200, payload=None):
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = {} if payload is None else payload
    return response


def _found(lat, lng):
    return _response(payload={"documents": [
        {"y": str(lat), "x": str(lng), "category_name": "부동산 > 주거시설 > 아파트", "place_name": "테스트단지"}
    ]})


class CacheTestCase(TestCase):
    """실제 DB를 건드리지 않도록 테스트마다 임시 디렉터리의 DB를 쓴다."""

    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = str(Path(tmp.name) / "cache.db")

    def _execute(self, sql, params=()):
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(sql, params).fetchall()
            conn.commit()
            return rows
        finally:
            conn.close()

    def _commute(self, from_lat=37.5, cache_key="202601010800"):
        # 대중교통은 경로 API를 부르지 않으므로 HTTP 없이 캐시 계층만 검증할 수 있다
        return kakao_api.get_kakao_commute(
            self.db_path, from_lat, 127.0, 37.6, 127.1,
            transport_mode="public", departure_time=cache_key,
        )


class SchemaInitializationTests(CacheTestCase):
    def _spy_on_initialization(self):
        patcher = mock.patch.object(
            kakao_api, "_initialize_schema", wraps=kakao_api._initialize_schema
        )
        spy = patcher.start()
        self.addCleanup(patcher.stop)
        return spy

    def test_schema_is_initialized_once_per_db_path(self):
        init = self._spy_on_initialization()
        with mock.patch.object(kakao_api, "KAKAO_REST_API_KEY", None):
            for _ in range(3):
                self._commute()
                kakao_api.get_precise_coordinates(self.db_path, *APARTMENT)
        self.assertEqual(init.call_count, 1)

    def test_parallel_first_calls_initialize_once(self):
        init = self._spy_on_initialization()
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda i: self._commute(from_lat=37.0 + i / 100), range(12)))
        self.assertEqual(init.call_count, 1)
        self.assertEqual(len(results), 12)
        self.assertEqual(len(self._execute("SELECT * FROM commute_cache_v3")), 12)

    def test_each_db_path_is_initialized_separately(self):
        init = self._spy_on_initialization()
        other_path = str(Path(self.db_path).with_name("other.db"))
        self._commute()
        kakao_api.get_kakao_commute(
            other_path, 37.5, 127.0, 37.6, 127.1,
            transport_mode="public", departure_time="202601010800",
        )
        self.assertEqual(init.call_count, 2)

    def test_expired_commute_rows_are_purged_on_initialization(self):
        now = datetime.now().timestamp()
        expired = now - (kakao_api.CACHE_TTL_SECONDS + 60)
        self._execute(COMMUTE_TABLE_SQL.format(extra_columns=", updated_at REAL"))
        for cache_key, updated_at in (("expired", expired), ("never_stamped", None), ("fresh", now)):
            self._execute(
                "INSERT INTO commute_cache_v3 VALUES (37.5, 127.0, 37.6, 127.1, 'public', ?, 10, 1.0, ?)",
                (cache_key, updated_at),
            )

        # 기존 행과 겹치지 않는 경로를 조회해, REPLACE가 아니라 정리 로직이 지웠음을 확인한다
        self._commute(from_lat=37.1, cache_key="202601010800")

        keys = {row[0] for row in self._execute("SELECT cache_key FROM commute_cache_v3")}
        self.assertEqual(keys, {"fresh", "202601010800"})

    def test_legacy_commute_table_is_migrated_without_losing_rows(self):
        self._execute(COMMUTE_TABLE_SQL.format(extra_columns=""))
        self._execute(
            "INSERT INTO commute_cache_v3 VALUES (37.5, 127.0, 37.6, 127.1, 'public', 'legacy', 10, 1.0)"
        )

        self._commute(from_lat=37.1)

        columns = {row[1] for row in self._execute("PRAGMA table_info(commute_cache_v3)")}
        self.assertIn("updated_at", columns)
        legacy = self._execute("SELECT updated_at FROM commute_cache_v3 WHERE cache_key = 'legacy'")
        self.assertEqual(len(legacy), 1)
        self.assertIsNotNone(legacy[0][0])

    def test_recreated_db_file_is_reinitialized_once(self):
        self._commute()
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(self.db_path + suffix):
                os.remove(self.db_path + suffix)

        init = self._spy_on_initialization()
        with self.assertNoLogs(kakao_api.logger, level="ERROR"):
            duration, _ = self._commute()
            self._commute()

        self.assertEqual(init.call_count, 1)
        rows = self._execute("SELECT duration_min FROM commute_cache_v3")
        self.assertEqual(rows, [(duration,)])


class GeocodeNegativeCacheTests(CacheTestCase):
    def setUp(self):
        super().setUp()
        key = mock.patch.object(kakao_api, "KAKAO_REST_API_KEY", REST_KEY)
        key.start()
        self.addCleanup(key.stop)
        http = mock.patch.object(kakao_api, "_http_get", return_value=_response(payload={"documents": []}))
        self.http = http.start()
        self.addCleanup(http.stop)

    def _geocode(self):
        return kakao_api.get_precise_coordinates(self.db_path, *APARTMENT)

    def _cached(self):
        return self._execute("SELECT lat, lng FROM complex_coords_v2")

    def _age_cache(self, seconds):
        self._execute(
            "UPDATE complex_coords_v2 SET updated_at = ?",
            (datetime.now().timestamp() - seconds,),
        )

    def test_no_result_is_cached_and_second_call_skips_http(self):
        first = self._geocode()
        second = self._geocode()

        self.assertEqual(first, (None, None))
        self.assertEqual(second, (None, None))
        self.assertEqual(self.http.call_count, 1)
        self.assertEqual(self._cached(), [(None, None)])

    def test_network_error_is_not_cached(self):
        self.http.side_effect = requests.ConnectionError("connection refused")

        first = self._geocode()
        second = self._geocode()

        self.assertEqual(first, (None, None))
        self.assertEqual(second, (None, None))
        self.assertEqual(self.http.call_count, 2)
        self.assertEqual(self._cached(), [])

    def test_non_200_response_is_not_cached_and_status_is_logged(self):
        self.http.return_value = _response(429)

        with self.assertLogs(kakao_api.logger, level="WARNING") as logs:
            self._geocode()
            self._geocode()

        self.assertEqual(self.http.call_count, 2)
        self.assertEqual(self._cached(), [])
        output = "\n".join(logs.output)
        self.assertIn("429", output)
        self.assertNotIn(REST_KEY, output)

    def test_negative_entry_is_retried_after_ttl(self):
        self._geocode()
        self._age_cache(kakao_api.GEOCODE_NEGATIVE_TTL_SECONDS + 60)
        self.http.return_value = _found(37.5012, 127.0396)

        retried = self._geocode()
        reused = self._geocode()

        self.assertEqual(retried, (37.5012, 127.0396))
        self.assertEqual(reused, (37.5012, 127.0396))
        self.assertEqual(self.http.call_count, 2)
        self.assertEqual(self._cached(), [(37.5012, 127.0396)])

    def test_negative_entry_within_ttl_is_not_retried(self):
        self._geocode()
        self._age_cache(kakao_api.GEOCODE_NEGATIVE_TTL_SECONDS - 60)

        self.assertEqual(self._geocode(), (None, None))
        self.assertEqual(self.http.call_count, 1)

    def test_negative_ttl_is_read_at_call_time(self):
        self._geocode()
        self._age_cache(120)

        with mock.patch.object(kakao_api, "GEOCODE_NEGATIVE_TTL_SECONDS", 60):
            self._geocode()

        self.assertEqual(self.http.call_count, 2)

    def test_found_coordinates_are_reused_without_expiry(self):
        self.http.return_value = _found(37.5012, 127.0396)
        self._geocode()
        self._age_cache(kakao_api.GEOCODE_NEGATIVE_TTL_SECONDS * 10)

        self.assertEqual(self._geocode(), (37.5012, 127.0396))
        self.assertEqual(self.http.call_count, 1)

    def test_missing_rest_key_skips_http_and_cache(self):
        with mock.patch.object(kakao_api, "KAKAO_REST_API_KEY", None):
            result = self._geocode()

        self.assertEqual(result, (None, None))
        self.http.assert_not_called()
        self.assertEqual(self._cached(), [])

    def test_javascript_key_skips_http_and_cache(self):
        with mock.patch.object(kakao_api, "KAKAO_REST_API_KEY", JAVASCRIPT_KEY):
            result = self._geocode()

        self.assertEqual(result, (None, None))
        self.http.assert_not_called()
        self.assertEqual(self._cached(), [])


class HttpLayerTests(TestCase):
    def _call_directions(self, response):
        with mock.patch.object(kakao_api, "KAKAO_REST_API_KEY", REST_KEY), \
                mock.patch.object(kakao_api, "_http_get", return_value=response) as http:
            result = kakao_api.call_kakao_api(127.0, 37.5, 127.1, 37.6, "202601010800")
        return result, http

    def test_directions_success_is_parsed(self):
        payload = {"routes": [{"result_code": 0, "summary": {"duration": 1800, "distance": 12500}}]}
        result, http = self._call_directions(_response(payload=payload))
        self.assertEqual(result, (30, 12.5))
        self.assertEqual(http.call_count, 1)

    def test_directions_failure_logs_status_without_key(self):
        for status_code in (429, 503):
            with self.subTest(status_code=status_code), \
                    self.assertLogs(kakao_api.logger, level="WARNING") as logs:
                result, _ = self._call_directions(_response(status_code))
            self.assertIsNone(result)
            output = "\n".join(logs.output)
            self.assertIn(str(status_code), output)
            self.assertNotIn(REST_KEY, output)

    def test_directions_without_usable_key_skips_http(self):
        for key in (None, JAVASCRIPT_KEY):
            with self.subTest(key=key), \
                    mock.patch.object(kakao_api, "KAKAO_REST_API_KEY", key), \
                    mock.patch.object(kakao_api, "_http_get") as http:
                self.assertIsNone(kakao_api.call_kakao_api(127.0, 37.5, 127.1, 37.6, "202601010800"))
                http.assert_not_called()

    def test_session_is_reused_within_thread_and_separate_across_threads(self):
        url, headers, params = "https://kakao.invalid/search", {"Authorization": "KakaoAK x"}, {"query": "q"}
        with mock.patch.object(kakao_api, "_thread_local", threading.local()), \
                mock.patch.object(kakao_api.requests, "Session", side_effect=lambda: mock.Mock()) as session_cls:
            kakao_api._http_get(url, headers, params)
            kakao_api._http_get(url, headers, params)
            session = kakao_api._thread_local.session
            worker = threading.Thread(target=kakao_api._http_get, args=(url, headers, params))
            worker.start()
            worker.join()

        self.assertEqual(session_cls.call_count, 2)
        self.assertEqual(session.get.call_count, 2)
        session.get.assert_called_with(url, headers=headers, params=params, timeout=5)


if __name__ == "__main__":
    import unittest

    unittest.main()
