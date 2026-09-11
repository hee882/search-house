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


class CollectorScheduleTests(TestCase):
    def test_recent_months_walks_back_across_year_boundary(self):
        class FrozenDatetime:
            @staticmethod
            def now():
                return datetime(2026, 2, 5)

        with mock.patch.object(collector, "datetime", FrozenDatetime):
            self.assertEqual(collector.recent_months(4), ["202602", "202601", "202512", "202511"])

    def test_recent_months_returns_at_least_one_month(self):
        self.assertEqual(len(collector_rent.recent_months(0)), 1)

    def test_rent_collector_declares_contract_columns(self):
        for column in ("contract_type", "use_rr_right", "apt_seq", "road_name"):
            self.assertIn(column, collector_rent.EXTRA_COLUMNS)

    def test_ensure_table_adds_missing_columns_to_legacy_schema(self):
        with TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "legacy.db")
            conn = sqlite3.connect(db_path)
            conn.execute(
                """
                CREATE TABLE rent_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    city_code TEXT, dong_name TEXT, apt_name TEXT, exclusive_area REAL,
                    deal_year INTEGER, deal_month INTEGER, deal_day INTEGER,
                    deposit INTEGER, monthly_rent INTEGER, floor INTEGER, build_year INTEGER,
                    UNIQUE(city_code, apt_name, dong_name, deal_year, deal_month, deal_day,
                           deposit, monthly_rent, floor)
                )
                """
            )
            conn.commit()
            conn.close()

            with mock.patch.object(collector_rent, "DB_PATH", db_path):
                collector_rent.ensure_table()

            conn = sqlite3.connect(db_path)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(rent_transactions)")}
            conn.close()

        self.assertTrue(set(collector_rent.EXTRA_COLUMNS).issubset(columns))


class ContractTypeDetectionTests(TestCase):
    def test_detects_contract_type_column(self):
        with TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "rent.db")
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE rent_transactions (id INTEGER, contract_type TEXT)")
            conn.commit()
            conn.close()
            with mock.patch.object(main, "DB_PATH", db_path):
                self.assertTrue(main._rent_table_has_contract_type())

    def test_missing_column_or_table_is_reported_as_unavailable(self):
        with TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "empty.db")
            sqlite3.connect(db_path).close()
            with mock.patch.object(main, "DB_PATH", db_path):
                self.assertFalse(main._rent_table_has_contract_type())


class CandidateSelectionTests(TestCase):
    GANGNAM = (37.4979, 127.0276)
    KINTEX = (37.6686, 126.7472)

    def test_balanced_location_beats_one_sided_location_for_couples(self):
        workplaces = [self.GANGNAM, self.KINTEX]
        balanced, _ = main.candidate_distance_score(37.5665, 126.8895, workplaces)   # 상암동
        one_sided, _ = main.candidate_distance_score(*self.GANGNAM, workplaces)      # 강남역 바로 옆
        self.assertLess(balanced, one_sided)

    def test_single_mode_score_is_monotonic_in_distance(self):
        workplaces = [self.GANGNAM]
        near, _ = main.candidate_distance_score(37.5000, 127.0300, workplaces)
        far, _ = main.candidate_distance_score(37.6686, 126.7472, workplaces)
        self.assertLess(near, far)

    def test_score_returns_distance_per_workplace(self):
        _, distances = main.candidate_distance_score(37.5665, 126.9780, [self.GANGNAM, self.KINTEX])
        self.assertEqual(len(distances), 2)
        self.assertTrue(all(d > 0 for d in distances))


class CommuteEstimationTests(TestCase):
    def test_longer_distance_takes_longer(self):
        near, near_km = kakao_api.estimate_commute(37.50, 127.00, 37.52, 127.02, "public", 8)
        far, far_km = kakao_api.estimate_commute(37.50, 127.00, 37.70, 127.30, "public", 8)
        self.assertLess(near, far)
        self.assertLess(near_km, far_km)

    def test_rush_hour_is_slower_than_midday(self):
        rush, _ = kakao_api.estimate_commute(37.50, 127.00, 37.60, 127.10, "car", 8)
        midday, _ = kakao_api.estimate_commute(37.50, 127.00, 37.60, 127.10, "car", 13)
        self.assertGreater(rush, midday)

    def test_public_transport_is_slower_than_car(self):
        public, _ = kakao_api.estimate_commute(37.50, 127.00, 37.60, 127.10, "public", 8)
        car, _ = kakao_api.estimate_commute(37.50, 127.00, 37.60, 127.10, "car", 8)
        self.assertGreater(public, car)


class PreciseAnalysisBudgetTests(TestCase):
    """정밀 분석(외부 API 호출) 대상이 상한 안에서만 이뤄지는지 확인."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app, raise_server_exceptions=False)

    def test_geocoding_is_limited_to_finalists(self):
        if not os.path.exists(main.DB_PATH):
            self.skipTest("실거래 DB가 없는 환경")

        payload = {
            "user1": {
                "workplace": {"lat": 37.5665, "lng": 126.9780, "name": "Office"},
                "salary": 6000,
                "transport": "public",
            },
            "mode": "single",
            "resident_type": "rent",
            "housing_ratio": 0.3,
            "min_area": 40,
            "max_area": 85,
            "preference": "balance",
        }

        with mock.patch.object(main, "get_precise_coordinates", return_value=(None, None)) as geocode:
            response = self.client.post("/api/optimize", json=payload)

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(geocode.call_count, main.PRECISE_ANALYSIS_LIMIT)

    def test_precise_limit_is_at_least_result_count(self):
        self.assertGreaterEqual(main.PRECISE_ANALYSIS_LIMIT, main.MAX_RESULTS)


class StatsCoverageTests(TestCase):
    def _db_with_rows(self, directory, months):
        db_path = str(Path(directory) / "stats.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY, city_code TEXT, deal_year INTEGER, deal_month INTEGER,
                deal_day INTEGER, deal_amount INTEGER, apt_name TEXT, dong_name TEXT,
                exclusive_area REAL, cancel_deal_day TEXT, is_new_high_price INTEGER DEFAULT 0,
                buyer_type TEXT
            )
            """
        )
        for index, (year, month) in enumerate(months, start=1):
            conn.execute(
                "INSERT INTO transactions (id, city_code, deal_year, deal_month, deal_day, deal_amount,"
                " apt_name, dong_name, exclusive_area) VALUES (?, '11680', ?, ?, 1, 50000, 'A', 'D', 84)",
                (index, year, month),
            )
        conn.commit()
        conn.close()
        return db_path

    def test_collected_period_reports_first_and_last_month(self):
        with TemporaryDirectory() as tmp:
            db_path = self._db_with_rows(tmp, [(2025, 2), (2026, 3), (2026, 9)])
            with mock.patch.object(main, "DB_PATH", db_path):
                period = main.get_collected_period("transactions", "11680")
        self.assertEqual(period["first_month"], "202502")
        self.assertEqual(period["last_month"], "202609")
        self.assertEqual(period["collected_months"], 3)

    def test_uncollected_month_is_distinguishable_from_zero_deals(self):
        with TemporaryDirectory() as tmp:
            db_path = self._db_with_rows(tmp, [(2026, 9)])
            with mock.patch.object(main, "DB_PATH", db_path):
                self.assertTrue(main.is_month_collected("transactions", "11680", 2026, 9))
                self.assertFalse(main.is_month_collected("transactions", "11680", 2025, 7))

    def test_stats_response_includes_coverage(self):
        with TemporaryDirectory() as tmp:
            db_path = self._db_with_rows(tmp, [(2026, 9)])
            with mock.patch.object(main, "DB_PATH", db_path):
                response = self.__class__.client.get(
                    "/api/stats/transactions", params={"city_code": "11680", "year": 2025, "month": 7}
                )
        payload = response.json()
        self.assertEqual(payload["summary"]["total"], 0)
        self.assertFalse(payload["coverage"]["requested_month_collected"])
        self.assertEqual(payload["coverage"]["last_month"], "202609")

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app, raise_server_exceptions=False)


class ResultDiversityTests(TestCase):
    def _spot(self, name, dong):
        return {"name": name, "dong": dong}

    def test_single_dong_cannot_occupy_every_slot(self):
        results = [self._spot(f"상암월드컵파크{i}단지", "상암동") for i in range(1, 6)]
        results += [
            self._spot("망원한강", "망원동"),
            self._spot("가양9단지", "가양동"),
            self._spot("화곡대림", "화곡동"),
        ]
        picked = main.diversify_results(results)
        self.assertEqual(len(picked), 5)
        self.assertEqual(sum(1 for p in picked if p["dong"] == "상암동"), 2)
        self.assertEqual(len({p["dong"] for p in picked}), 4)

    def test_order_is_preserved_within_limit(self):
        results = [self._spot("A", "1동"), self._spot("B", "2동"), self._spot("C", "3동")]
        self.assertEqual([p["name"] for p in main.diversify_results(results)], ["A", "B", "C"])

    def test_falls_back_to_score_order_when_not_enough_dongs(self):
        results = [self._spot(f"단지{i}", "상암동") for i in range(1, 8)]
        picked = main.diversify_results(results)
        self.assertEqual(len(picked), 5)
        self.assertEqual([p["name"] for p in picked[:2]], ["단지1", "단지2"])


class PriceAggregationTests(TestCase):
    def test_dominant_area_bucket_is_used_instead_of_mixed_average(self):
        rows = [("단지A", "역삼동", "11680", "10000:0:59,10500:0:59,11000:0:59,30000:0:130", 2000)]
        (_, _, _, avg_deposit, _, avg_area, _), = main._filter_complexes_by_iqr(rows)
        self.assertEqual(avg_deposit, 10500)
        self.assertEqual(avg_area, 59.0)

    def test_high_price_outlier_is_removed(self):
        rows = [("단지B", "역삼동", "11680", "10000:0:59,10200:0:59,10400:0:59,10600:0:59,90000:0:59", 2000)]
        (_, _, _, avg_deposit, _, _, _), = main._filter_complexes_by_iqr(rows)
        self.assertEqual(avg_deposit, 10300)

    def test_jeonse_and_wolse_are_not_averaged_together(self):
        rows = [("단지C", "역삼동", "11680", "30000:0:59,31000:0:59,5000:80:59,5200:85:59,5400:90:59", 2000)]
        (_, _, _, avg_deposit, avg_rent, _, _), = main._filter_complexes_by_iqr(rows)
        self.assertLess(avg_deposit, 10000)
        self.assertGreater(avg_rent, 0)


class HousingCostModelTests(TestCase):
    def test_sale_uses_mortgage_rate_and_rent_uses_jeonse_rate(self):
        sale = main.calculate_monthly_housing_cost(60000, 0, available_cash=30000, resident_type="buy")
        rent = main.calculate_monthly_housing_cost(60000, 0, available_cash=30000, resident_type="rent")
        self.assertGreater(sale, rent)
        expected_sale = round(30000 * main.CASH_OPPORTUNITY_RATE / 12) + round(30000 * main.MORTGAGE_RATE / 12)
        self.assertEqual(sale, expected_sale)

    def test_without_cash_only_opportunity_cost_applies(self):
        cost = main.calculate_monthly_housing_cost(50000, 30, available_cash=0, resident_type="buy")
        self.assertEqual(cost, 30 + round(50000 * main.CASH_OPPORTUNITY_RATE / 12))

    def test_price_format_uses_korean_units(self):
        self.assertEqual(main.format_price_kr(9800), "9,800만")
        self.assertEqual(main.format_price_kr(50000), "5억")
        self.assertEqual(main.format_price_kr(53166), "5억 3,166만")


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
