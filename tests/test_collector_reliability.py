import contextlib
import io
import json
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock

import requests


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import collector
import collector_rent
from lib.molit_response import MolitApiError, mask_service_key, parse_molit_response


SERVICE_KEY = "test-service-key-do-not-print"

def gateway_error(code, auth_msg):
    return (
        "<OpenAPI_ServiceResponse><cmmMsgHeader>"
        "<errMsg>SERVICE ERROR</errMsg>"
        f"<returnAuthMsg>{auth_msg}</returnAuthMsg>"
        f"<returnReasonCode>{code}</returnReasonCode>"
        "</cmmMsgHeader></OpenAPI_ServiceResponse>"
    )


QUOTA_EXCEEDED_XML = gateway_error("22", "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR")

NO_DATA_XML = (
    "<response><header><resultCode>03</resultCode>"
    "<resultMsg>NODATA_ERROR</resultMsg></header></response>"
)


def xml_item(fields):
    return "<item>" + "".join(
        f"<{key}>{value}</{key}>" for key, value in fields.items() if value is not None
    ) + "</item>"


def trade_item(month, day, amount, *, year=2026, apt_seq="11680-100", apt="테스트아파트",
               dong="역삼동", area="84.97", floor=5, cancel_day=None):
    return xml_item({
        "aptNm": apt, "aptSeq": apt_seq, "umdNm": dong, "excluUseAr": area,
        "dealAmount": amount, "dealYear": year, "dealMonth": month, "dealDay": day,
        "floor": floor, "buildYear": 2005, "dealingGbn": "중개거래", "cdealDay": cancel_day,
    })


def rent_item(month, day, deposit, monthly_rent=0):
    return xml_item({
        "aptNm": "테스트아파트", "aptSeq": "11680-100", "umdNm": "역삼동", "excluUseAr": "59.9",
        "deposit": deposit, "monthlyRent": monthly_rent,
        "dealYear": 2026, "dealMonth": month, "dealDay": day, "floor": 3, "buildYear": 2005,
    })


def ok_response(items, *, result_code="000", total_count=None):
    count = len(items) if total_count is None else total_count
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<response><header><resultCode>{result_code}</resultCode><resultMsg>OK</resultMsg></header>"
        f"<body><items>{''.join(items)}</items><numOfRows>1000</numOfRows><pageNo>1</pageNo>"
        f"<totalCount>{count}</totalCount></body></response>"
    )


class FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            # requests 는 오류 메시지에 요청 URL 을 그대로 넣는다.
            raise requests.exceptions.HTTPError(
                f"{self.status_code} Server Error for url: "
                f"https://apis.data.go.kr/x?serviceKey={SERVICE_KEY}&LAWD_CD=11680"
            )


class CollectorHarness(TestCase):
    """임시 DB 와 가짜 HTTP 응답으로 수집기를 돌린다. 실제 DB 와 국토부 API 는 건드리지 않는다."""

    module = collector
    REGIONS = {"서울": {"강남구": "11680", "서초구": "11650"}}

    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_path = str(Path(tmp.name) / "collector_test.db")
        regions_path = Path(tmp.name) / "regions.json"
        regions_path.write_text(json.dumps(self.REGIONS, ensure_ascii=False), encoding="utf-8")

        overrides = {"DB_PATH": self.db_path, "REGIONS_PATH": str(regions_path), "API_KEY": SERVICE_KEY}
        for name, value in overrides.items():
            patcher = mock.patch.object(self.module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.requests_made = []

    def collect(self, responder, argv=None, **kwargs):
        """responder(params) 가 돌려준 응답으로 수집을 실행하고 (종료 코드, 출력) 을 돌려준다."""
        def fake_get(url, params=None, timeout=None):
            self.requests_made.append(dict(params))
            return responder(params)

        output = io.StringIO()
        with mock.patch.object(requests.Session, "get", side_effect=fake_get), \
                contextlib.redirect_stdout(output):
            if argv is not None:
                code = self.module.main(argv)
            else:
                code = self.module.run_collector(**kwargs)
        return code, output.getvalue()

    def query(self, sql):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def flags(self):
        return self.query(
            "SELECT deal_year * 10000 + deal_month * 100 + deal_day, deal_amount, is_new_high_price"
            " FROM transactions ORDER BY 1, 2"
        )


def only_gangnam(items_by_month):
    """강남구에만 거래가 있고 나머지 지역은 정상 0건인 응답기."""
    def responder(params):
        if params["LAWD_CD"] != "11680":
            return FakeResponse(ok_response([]))
        return FakeResponse(ok_response(items_by_month.get(params["DEAL_YMD"], [])))
    return responder


class NewHighFlagCollectionTests(CollectorHarness):
    def test_flags_survive_recollecting_the_same_response(self):
        responder = only_gangnam({
            "202607": [trade_item(7, 1, "50,000")],
            "202608": [trade_item(8, 1, "60,000")],
        })

        with mock.patch.object(collector, "recent_months", return_value=["202608", "202607"]):
            first_code, _ = self.collect(responder)
            after_first = self.flags()
            second_code, second_output = self.collect(responder)

        self.assertEqual(after_first, [(20260701, 50000, 0), (20260801, 60000, 1)])
        self.assertEqual(self.flags(), after_first)
        self.assertEqual((first_code, second_code), (0, 0))
        self.assertIn("0 rows changed", second_output)

    def test_first_deal_without_earlier_deal_is_not_new_high(self):
        code, _ = self.collect(only_gangnam({"202608": [trade_item(8, 1, "60,000")]}),
                               target_month="202608")

        self.assertEqual(code, 0)
        self.assertEqual(self.flags(), [(20260801, 60000, 0)])

    def test_late_reported_deal_corrects_later_flags(self):
        months = {
            "202607": [trade_item(7, 1, "50,000")],
            "202608": [trade_item(8, 1, "60,000")],
        }
        with mock.patch.object(collector, "recent_months", return_value=["202608", "202607"]):
            self.collect(only_gangnam(months))
            self.assertEqual(self.flags(), [(20260701, 50000, 0), (20260801, 60000, 1)])

            # 7월 15일 계약이 8월 거래보다 늦게 신고되어 들어온다.
            months["202607"].append(trade_item(7, 15, "70,000", floor=9))
            self.collect(only_gangnam(months))

        self.assertEqual(
            self.flags(),
            [(20260701, 50000, 0), (20260715, 70000, 1), (20260801, 60000, 0)],
        )

    def test_cancelled_deal_is_neither_flagged_nor_compared(self):
        responder = only_gangnam({
            "202607": [
                trade_item(7, 1, "50,000"),
                trade_item(7, 10, "90,000", floor=9, cancel_day="26.07.20"),
            ],
            "202608": [trade_item(8, 1, "60,000")],
        })
        with mock.patch.object(collector, "recent_months", return_value=["202608", "202607"]):
            self.collect(responder)

        self.assertEqual(
            self.flags(),
            [(20260701, 50000, 0), (20260710, 90000, 0), (20260801, 60000, 1)],
        )

    def test_deal_cancelled_after_collection_loses_flag_and_frees_next_deal(self):
        months = {
            "202607": [trade_item(7, 1, "50,000"), trade_item(7, 10, "90,000", floor=9)],
            "202608": [trade_item(8, 1, "60,000")],
        }
        with mock.patch.object(collector, "recent_months", return_value=["202608", "202607"]):
            self.collect(only_gangnam(months))
            self.assertEqual(
                self.flags(),
                [(20260701, 50000, 0), (20260710, 90000, 1), (20260801, 60000, 0)],
            )

            months["202607"][1] = trade_item(7, 10, "90,000", floor=9, cancel_day="26.08.05")
            self.collect(only_gangnam(months))

        self.assertEqual(
            self.flags(),
            [(20260701, 50000, 0), (20260710, 90000, 0), (20260801, 60000, 1)],
        )


class RecomputeNewHighFlagsTests(CollectorHarness):
    def setUp(self):
        super().setUp()
        collector.init_db()

    def insert(self, deals):
        """deals: (apt_seq, city_code, apt_name, area, 거래일 YYYYMMDD, 금액, 해제일) 목록"""
        conn = sqlite3.connect(self.db_path)
        for index, (apt_seq, city_code, apt_name, area, date, amount, cancel_day) in enumerate(deals):
            conn.execute(
                "INSERT INTO transactions (city_code, dong_name, apt_name, apt_seq, exclusive_area,"
                " deal_amount, deal_year, deal_month, deal_day, floor, cancel_deal_day)"
                " VALUES (?, '역삼동', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (city_code, apt_name, apt_seq, area, amount,
                 date // 10000, date // 100 % 100, date % 100, index + 1, cancel_day),
            )
        conn.commit()
        conn.close()

    def recompute(self):
        conn = sqlite3.connect(self.db_path)
        try:
            changed = collector.recompute_new_high_flags(conn)
            conn.commit()
            return changed
        finally:
            conn.close()

    def test_second_recompute_updates_no_rows(self):
        self.insert([
            ("S1", "11680", "A", 84.97, 20260701, 50000, None),
            ("S1", "11680", "A", 84.97, 20260801, 60000, None),
            ("S1", "11680", "A", 84.97, 20260901, 55000, None),
        ])

        self.assertEqual(self.recompute(), 1)
        self.assertEqual(self.recompute(), 0)
        self.assertEqual(
            self.flags(),
            [(20260701, 50000, 0), (20260801, 60000, 1), (20260901, 55000, 0)],
        )

    def test_wrong_existing_flags_are_corrected(self):
        self.insert([
            ("S1", "11680", "A", 84.97, 20260701, 50000, None),
            ("S1", "11680", "A", 84.97, 20260801, 60000, None),
        ])
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE transactions SET is_new_high_price = 1 - (deal_month = 8)")
        conn.commit()
        conn.close()

        self.assertEqual(self.recompute(), 2)
        self.assertEqual(self.flags(), [(20260701, 50000, 0), (20260801, 60000, 1)])

    def test_same_day_deals_are_not_compared_with_each_other(self):
        self.insert([
            ("S1", "11680", "A", 84.97, 20260701, 50000, None),
            ("S1", "11680", "A", 84.97, 20260801, 60000, None),
            ("S1", "11680", "A", 84.97, 20260801, 65000, None),
        ])
        self.recompute()

        self.assertEqual(
            self.flags(),
            [(20260701, 50000, 0), (20260801, 60000, 1), (20260801, 65000, 1)],
        )

    def test_equal_price_is_not_new_high(self):
        self.insert([
            ("S1", "11680", "A", 84.97, 20260701, 50000, None),
            ("S1", "11680", "A", 84.97, 20260801, 50000, None),
        ])
        self.recompute()

        self.assertEqual(self.flags(), [(20260701, 50000, 0), (20260801, 50000, 0)])

    def test_complexes_without_apt_seq_are_separated_by_city(self):
        self.insert([
            (None, "11680", "A", 84.97, 20260701, 90000, None),
            (None, "11650", "A", 84.97, 20260801, 60000, None),
            (None, "11680", "A", 84.97, 20260901, 95000, None),
        ])
        self.recompute()

        self.assertEqual(
            self.flags(),
            [(20260701, 90000, 0), (20260801, 60000, 0), (20260901, 95000, 1)],
        )

    def test_different_area_is_compared_separately(self):
        self.insert([
            ("S1", "11680", "A", 59.9, 20260701, 40000, None),
            ("S1", "11680", "A", 84.97, 20260801, 60000, None),
            ("S1", "11680", "A", 59.9, 20260901, 45000, None),
        ])
        self.recompute()

        self.assertEqual(
            self.flags(),
            [(20260701, 40000, 0), (20260801, 60000, 0), (20260901, 45000, 1)],
        )


class MolitResponseTests(TestCase):
    def test_result_code_error_raises(self):
        xml = (
            "<response><header><resultCode>30</resultCode>"
            "<resultMsg>SERVICE KEY IS NOT REGISTERED ERROR.</resultMsg></header></response>"
        )
        with self.assertRaises(MolitApiError) as raised:
            parse_molit_response(xml)

        self.assertEqual(raised.exception.code, "30")
        self.assertIn("NOT REGISTERED", raised.exception.message)

    def test_gateway_error_format_raises(self):
        with self.assertRaises(MolitApiError) as raised:
            parse_molit_response(QUOTA_EXCEEDED_XML)

        self.assertEqual(raised.exception.code, "22")
        self.assertIn("LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR", raised.exception.message)
        self.assertIn("SERVICE ERROR", raised.exception.message)

    def test_unparsable_body_raises(self):
        for body in ("", "<response><header>", "Service Temporarily Unavailable", None):
            with self.subTest(body=body):
                with self.assertRaises(MolitApiError) as raised:
                    parse_molit_response(body)
                self.assertEqual(raised.exception.code, "INVALID_XML")

    def test_unknown_root_or_missing_result_code_raises(self):
        for xml in ("<html><body>gateway</body></html>", "<response><body><totalCount>0</totalCount></body></response>"):
            with self.subTest(xml=xml):
                with self.assertRaises(MolitApiError):
                    parse_molit_response(xml)

    def test_successful_empty_response_is_not_an_error(self):
        for code in ("00", "000"):
            with self.subTest(code=code):
                self.assertEqual(parse_molit_response(ok_response([], result_code=code)), ([], 0))

    def test_no_data_result_code_is_an_empty_result(self):
        with_body = ok_response([], result_code="03")
        for xml in (NO_DATA_XML, with_body):
            with self.subTest(xml=xml):
                self.assertEqual(parse_molit_response(xml), ([], 0))

    def test_gateway_format_is_an_error_whatever_the_code(self):
        # 인증 단계 응답의 03 은 조회 결과가 아니므로 '거래 없음'으로 넘기면 안 된다.
        for code in ("03", "00", "000", "22", "30", ""):
            with self.subTest(code=code):
                with self.assertRaises(MolitApiError) as raised:
                    parse_molit_response(gateway_error(code, "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"))
                self.assertEqual(raised.exception.code, code or "UNKNOWN")

    def test_single_item_is_returned_as_list(self):
        items, total = parse_molit_response(ok_response([trade_item(8, 1, "60,000")]))

        self.assertEqual(total, 1)
        self.assertEqual([item["dealAmount"] for item in items], ["60,000"])

    def test_multiple_items_keep_order(self):
        items, total = parse_molit_response(
            ok_response([trade_item(8, 1, "60,000"), trade_item(8, 2, "61,000")], total_count=1500)
        )

        self.assertEqual(total, 1500)
        self.assertEqual([item["dealDay"] for item in items], ["1", "2"])

    def test_service_key_is_masked_in_messages(self):
        message = f"500 Server Error for url: https://x/y?serviceKey={SERVICE_KEY}&LAWD_CD=11680"
        masked = mask_service_key(message)

        self.assertNotIn(SERVICE_KEY, masked)
        self.assertIn("LAWD_CD=11680", masked)


class CollectorFailureReportingTests(CollectorHarness):
    def quota_error_for_seocho(self, params):
        if params["LAWD_CD"] == "11650":
            return FakeResponse(QUOTA_EXCEEDED_XML)
        return FakeResponse(ok_response([trade_item(8, 1, "60,000")]))

    def test_api_error_makes_exit_code_nonzero_but_other_regions_are_saved(self):
        code, output = self.collect(self.quota_error_for_seocho, target_month="202608")

        self.assertEqual(code, 1)
        self.assertEqual(self.query("SELECT city_code FROM transactions"), [("11680",)])
        self.assertIn("[22] LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR", output)
        self.assertIn("Summary: 1 region-months succeeded, 1 failed, 0 rows skipped.", output)
        self.assertNotIn(SERVICE_KEY, output)

    def test_error_in_first_region_does_not_stop_later_regions(self):
        def responder(params):
            if params["LAWD_CD"] == "11680":
                return FakeResponse(QUOTA_EXCEEDED_XML)
            return FakeResponse(ok_response([trade_item(8, 1, "60,000", apt_seq="11650-7")]))

        code, _ = self.collect(responder, target_month="202608")

        self.assertEqual(code, 1)
        self.assertEqual([request["LAWD_CD"] for request in self.requests_made], ["11680", "11650"])
        self.assertEqual(self.query("SELECT city_code FROM transactions"), [("11650",)])

    def test_cli_entry_point_returns_nonzero_on_error(self):
        code, _ = self.collect(self.quota_error_for_seocho, argv=["--month", "202608"])

        self.assertEqual(code, 1)
        self.assertEqual({request["DEAL_YMD"] for request in self.requests_made}, {"202608"})

    def test_successful_run_exits_zero(self):
        code, output = self.collect(
            lambda params: FakeResponse(ok_response([])), argv=["--month", "202608"]
        )

        self.assertEqual(code, 0)
        self.assertIn("Summary: 2 region-months succeeded, 0 failed, 0 rows skipped.", output)

    def test_run_with_only_no_data_responses_exits_zero(self):
        code, output = self.collect(lambda params: FakeResponse(NO_DATA_XML),
                                    argv=["--month", "202608"])

        self.assertEqual(code, 0)
        self.assertEqual(len(self.requests_made), 2)
        self.assertEqual(self.query("SELECT COUNT(*) FROM transactions"), [(0,)])
        self.assertIn("Summary: 2 region-months succeeded, 0 failed, 0 rows skipped.", output)

    def test_gateway_error_with_code_03_still_fails_the_run(self):
        code, output = self.collect(
            lambda params: FakeResponse(gateway_error("03", "SERVICE_KEY_IS_NOT_REGISTERED_ERROR")),
            target_month="202608",
        )

        self.assertEqual(code, 1)
        self.assertIn("0 region-months succeeded, 2 failed", output)

    def test_http_error_is_counted_and_does_not_print_service_key(self):
        code, output = self.collect(lambda params: FakeResponse("", status_code=500),
                                    target_month="202608")

        self.assertEqual(code, 1)
        self.assertIn("2 failed", output)
        self.assertIn("serviceKey=***", output)
        self.assertNotIn(SERVICE_KEY, output)

    def test_error_on_later_page_is_counted_as_failure(self):
        def responder(params):
            if params["pageNo"] == 1:
                return FakeResponse(ok_response([trade_item(8, 1, "60,000")], total_count=1001))
            return FakeResponse(QUOTA_EXCEEDED_XML)

        code, output = self.collect(responder, target_month="202608")

        self.assertEqual(code, 1)
        self.assertIn("0 region-months succeeded, 2 failed", output)

    def test_missing_api_key_exits_nonzero_without_calling_api(self):
        with mock.patch.object(self.module, "API_KEY", None):
            code, output = self.collect(lambda params: FakeResponse(ok_response([])),
                                        target_month="202608")

        self.assertEqual(code, 1)
        self.assertEqual(self.requests_made, [])
        self.assertIn("DATA_API_KEY", output)

    def test_unparsable_rows_are_skipped_and_counted(self):
        responder = only_gangnam({"202608": [
            trade_item(8, 1, "60,000"),
            trade_item(8, 2, "61,000", area="면적없음"),
        ]})

        code, output = self.collect(responder, target_month="202608")

        self.assertEqual(code, 0)
        self.assertEqual(self.flags(), [(20260801, 60000, 0)])
        self.assertIn("Summary: 2 region-months succeeded, 0 failed, 1 rows skipped.", output)

    def test_wal_checkpoint_runs_even_when_regions_fail(self):
        statements = []
        real_connect = sqlite3.connect

        def tracing_connect(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            conn.set_trace_callback(statements.append)
            return conn

        with mock.patch.object(sqlite3, "connect", side_effect=tracing_connect):
            code, _ = self.collect(lambda params: FakeResponse(QUOTA_EXCEEDED_XML),
                                   target_month="202608")

        self.assertEqual(code, 1)
        self.assertTrue(any("wal_checkpoint" in statement for statement in statements))


class RentCollectorFailureReportingTests(CollectorHarness):
    module = collector_rent

    def test_api_error_makes_exit_code_nonzero_but_other_regions_are_saved(self):
        def responder(params):
            if params["LAWD_CD"] == "11650":
                return FakeResponse(QUOTA_EXCEEDED_XML)
            return FakeResponse(ok_response([rent_item(8, 1, "30,000"), rent_item(8, 2, "5,000", 80)]))

        code, output = self.collect(responder, argv=["--month", "202608"])

        self.assertEqual(code, 1)
        self.assertEqual(
            self.query("SELECT city_code, deposit, monthly_rent FROM rent_transactions ORDER BY deal_day"),
            [("11680", 30000, 0), ("11680", 5000, 80)],
        )
        self.assertIn("[22] LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR", output)
        self.assertIn("Summary: 1 region-months succeeded, 1 failed, 0 rows skipped.", output)
        self.assertNotIn(SERVICE_KEY, output)

    def test_successful_empty_month_exits_zero(self):
        code, output = self.collect(lambda params: FakeResponse(ok_response([])),
                                    target_month="202608")

        self.assertEqual(code, 0)
        self.assertIn("Summary: 2 region-months succeeded, 0 failed, 0 rows skipped.", output)

    def test_run_with_only_no_data_responses_exits_zero(self):
        code, output = self.collect(lambda params: FakeResponse(NO_DATA_XML),
                                    argv=["--month", "202608"])

        self.assertEqual(code, 0)
        self.assertEqual(self.query("SELECT COUNT(*) FROM rent_transactions"), [(0,)])
        self.assertIn("Summary: 2 region-months succeeded, 0 failed, 0 rows skipped.", output)

    def test_missing_api_key_exits_nonzero_without_calling_api(self):
        with mock.patch.object(self.module, "API_KEY", ""):
            code, _ = self.collect(lambda params: FakeResponse(ok_response([])),
                                   target_month="202608")

        self.assertEqual(code, 1)
        self.assertEqual(self.requests_made, [])

    def test_unparsable_rows_are_skipped_and_counted(self):
        broken = rent_item(8, 2, "5,000", 80).replace("59.9", "면적없음")
        responder = only_gangnam({"202608": [rent_item(8, 1, "30,000"), broken]})

        code, output = self.collect(responder, target_month="202608")

        self.assertEqual(code, 0)
        self.assertIn("Summary: 2 region-months succeeded, 0 failed, 1 rows skipped.", output)


if __name__ == "__main__":
    import unittest

    unittest.main()
