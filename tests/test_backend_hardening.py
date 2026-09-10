import importlib
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import collector
import collector_rent
import debug_api_results
import main
from lib import kakao_api


class ConfigurationHardeningTests(TestCase):
    def test_debug_api_uses_environment_key_and_clear_missing_key_message(self):
        source = (SERVER_DIR / "debug_api_results.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"KAKAO_REST_API_KEY\s*=\s*['\"][0-9a-f]{32}['\"]")

        with mock.patch.object(debug_api_results, "KAKAO_REST_API_KEY", None):
            result = debug_api_results.call_kakao_api("a", "b", "202601010800")

        self.assertIn("KAKAO_REST_API_KEY", result)
        self.assertIn("environment", result)

    def test_public_transport_uses_fallback_without_car_api_call(self):
        with TemporaryDirectory() as tmp, mock.patch.object(kakao_api, "call_kakao_api") as call:
            duration, distance = kakao_api.get_kakao_commute(
                str(Path(tmp) / "cache.db"), 37.5, 127.0, 37.6, 127.1,
                transport_mode="public", departure_time="202601010800"
            )
        self.assertGreater(duration, 0)
        self.assertGreater(distance, 0)
        call.assert_not_called()

    def test_precise_coordinate_cache_isolated_by_city_code(self):
        with TemporaryDirectory() as tmp, mock.patch.object(kakao_api, "KAKAO_REST_API_KEY", None):
            db_path = str(Path(tmp) / "cache.db")
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE complex_coords_v2 (city_code TEXT, apt_name TEXT, dong_name TEXT, lat REAL, lng REAL, updated_at REAL, PRIMARY KEY (city_code, apt_name, dong_name))")
            conn.execute("INSERT INTO complex_coords_v2 VALUES ('11111', '같은단지', '중앙동', 37.5, 127.0, 0)")
            conn.commit()
            conn.close()
            first = kakao_api.get_precise_coordinates(db_path, "같은단지", "중앙동", "11111")
            second = kakao_api.get_precise_coordinates(db_path, "같은단지", "중앙동", "22222")
        self.assertEqual(first, (37.5, 127.0))
        self.assertEqual(second, (None, None))

    def test_debug_api_reads_key_from_environment(self):
        with mock.patch.dict(os.environ, {"KAKAO_REST_API_KEY": "from-env"}):
            reloaded = importlib.reload(debug_api_results)
        self.assertEqual(reloaded.KAKAO_REST_API_KEY, "from-env")
        importlib.reload(debug_api_results)

    def test_rent_collector_uses_https(self):
        self.assertTrue(collector_rent.API_URL.startswith("https://"))


class CommuteCacheTests(TestCase):
    def _stale_row(self, db_path, duration, updated_at):
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS commute_cache_v3 (
                from_lat REAL, from_lng REAL, to_lat REAL, to_lng REAL,
                transport_mode TEXT, cache_key TEXT,
                duration_min INTEGER, distance_km REAL, updated_at REAL,
                PRIMARY KEY (from_lat, from_lng, to_lat, to_lng, transport_mode, cache_key)
            )
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO commute_cache_v3 VALUES (37.5, 127.0, 37.6, 127.1, 'public', '202601010800', ?, 1.0, ?)",
            (duration, updated_at),
        )
        conn.commit()
        conn.close()

    def test_fresh_cache_entry_is_reused(self):
        with TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "cache.db")
            self._stale_row(db_path, 999, datetime.now().timestamp())
            duration, distance = kakao_api.get_kakao_commute(
                db_path, 37.5, 127.0, 37.6, 127.1,
                transport_mode="public", departure_time="202601010800",
            )
        self.assertEqual((duration, distance), (999, 1.0))

    def test_expired_cache_entry_is_replaced_not_ignored(self):
        with TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "cache.db")
            expired = datetime.now().timestamp() - (kakao_api.CACHE_TTL_SECONDS + 60)
            self._stale_row(db_path, 999, expired)
            duration, _ = kakao_api.get_kakao_commute(
                db_path, 37.5, 127.0, 37.6, 127.1,
                transport_mode="public", departure_time="202601010800",
            )
            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT duration_min, updated_at FROM commute_cache_v3"
            ).fetchall()
            conn.close()

        self.assertNotEqual(duration, 999)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], duration)
        self.assertGreater(rows[0][1], expired)


class NewHighBackfillTests(TestCase):
    def test_backfill_applies_high_price_conditions_to_null_cancellation_rows(self):
        connection = sqlite3.connect(":memory:")
        cursor = connection.cursor()
        cursor.execute(
            """
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY,
                apt_name TEXT,
                dong_name TEXT,
                exclusive_area REAL,
                deal_amount INTEGER,
                deal_year INTEGER,
                deal_month INTEGER,
                deal_day INTEGER,
                cancel_deal_day TEXT,
                is_new_high_price INTEGER DEFAULT 0
            )
            """
        )
        cursor.executemany(
            """
            INSERT INTO transactions
            (id, apt_name, dong_name, exclusive_area, deal_amount, deal_year,
             deal_month, deal_day, cancel_deal_day)
            VALUES (?, 'A', 'D', 84, ?, 2025, 1, ?, NULL)
            """,
            [(1, 500, 1), (2, 400, 2)],
        )

        collector._backfill_new_high_prices(cursor)

        rows = cursor.execute(
            "SELECT id, is_new_high_price FROM transactions ORDER BY id"
        ).fetchall()
        self.assertEqual(rows, [(1, 1), (2, 0)])
        connection.close()


class DistrictCenterTests(TestCase):
    def test_district_center_is_average_of_known_dong_coordinates(self):
        centers = main._build_district_centers({
            "11680_역삼동": {"lat": 37.5, "lng": 127.0},
            "11680_자곡동": {"lat": 37.4, "lng": 127.1},
            "11110_사직동": {"lat": 37.6, "lng": 126.9},
        })
        self.assertEqual(centers["11680"], {"lat": 37.45, "lng": 127.05})
        self.assertEqual(centers["11110"], {"lat": 37.6, "lng": 126.9})

    def test_district_center_ignores_unknown_city_code(self):
        centers = main._build_district_centers({"11680_역삼동": {"lat": 37.5, "lng": 127.0}})
        self.assertIsNone(centers.get("99999"))


class RoutingModeTests(TestCase):
    def test_realtime_routing_requires_rest_key(self):
        with mock.patch.object(kakao_api, "KAKAO_REST_API_KEY", None):
            self.assertFalse(kakao_api.is_realtime_routing_available())

    def test_javascript_key_is_not_treated_as_realtime_capable(self):
        with mock.patch.object(kakao_api, "KAKAO_REST_API_KEY", "feb433e26a2ced15800280d98c464a14"):
            self.assertFalse(kakao_api.is_realtime_routing_available())

    def test_valid_rest_key_enables_realtime_routing(self):
        with mock.patch.object(kakao_api, "KAKAO_REST_API_KEY", "0123456789abcdef0123456789abcdef"):
            self.assertTrue(kakao_api.is_realtime_routing_available())


class ApiValidationTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app, raise_server_exceptions=False)

    def valid_optimize_payload(self):
        return {
            "user1": {
                "workplace": {"lat": 37.5, "lng": 127.0, "name": "Office"},
                "salary": 5000,
                "transport": "public",
            },
            "mode": "single",
            "resident_type": "rent",
            "housing_ratio": 0.25,
            "min_area": 40,
            "max_area": 80,
            "preference": "balance",
        }

    def test_query_parameters_are_bounded(self):
        self.assertEqual(
            self.client.get("/api/stats/transactions", params={"city_code": "1234"}).status_code,
            422,
        )
        self.assertEqual(
            self.client.get(
                "/api/stats/transactions",
                params={"city_code": "12345", "month": 13},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.get(
                "/api/stats/new-highs", params={"city_code": "12345", "limit": 101}
            ).status_code,
            422,
        )

    def test_optimize_rejects_invalid_enums_ranges_and_cross_field_values(self):
        payload = self.valid_optimize_payload()
        payload["user1"]["transport"] = "plane"
        self.assertEqual(self.client.post("/api/optimize", json=payload).status_code, 422)

        payload = self.valid_optimize_payload()
        payload["user1"]["workplace"]["lat"] = 91
        self.assertEqual(self.client.post("/api/optimize", json=payload).status_code, 422)

        payload = self.valid_optimize_payload()
        payload["min_area"], payload["max_area"] = 100, 50
        self.assertEqual(self.client.post("/api/optimize", json=payload).status_code, 422)

        payload = self.valid_optimize_payload()
        payload["mode"] = "couple"
        self.assertEqual(self.client.post("/api/optimize", json=payload).status_code, 422)

    def test_internal_database_error_is_not_exposed(self):
        with TemporaryDirectory() as temp_dir:
            temp_db = Path(temp_dir) / "empty.db"
            sqlite3.connect(temp_db).close()
            with mock.patch.object(main, "DB_PATH", str(temp_db)):
                response = self.client.get(
                    "/api/stats/transactions",
                    params={"city_code": "12345", "year": 2025, "month": 1},
                )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": "Internal server error"})
        self.assertNotIn("transactions", response.text)


if __name__ == "__main__":
    import unittest

    unittest.main()
