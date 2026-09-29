"""국토부 실거래가 API(XML) 응답 해석.

이 API는 쿼터 초과나 키 오류 때도 HTTP 200 을 돌려준다. 상태 코드만 보면
실패가 '거래 없음'으로 보이므로 본문의 결과 코드를 직접 확인한다.
"""
import re

import xmltodict

SUCCESS_CODES = ("00", "000")
# 공공데이터포털 표준 코드 03(NODATA_ERROR). 조회는 끝났고 그 지역·달에 거래가 없다는 뜻이다.
# 실패로 집계하면 월초처럼 거래 0건인 지역이 있는 날마다 워크플로가 실패로 표시된다.
NO_DATA_CODE = "03"

_SERVICE_KEY_PATTERN = re.compile(r"(serviceKey=)[^&\s'\")]+", re.IGNORECASE)


class MolitApiError(Exception):
    def __init__(self, code, message):
        self.code = str(code)
        self.message = str(message)
        super().__init__(f"[{self.code}] {self.message}")


def mask_service_key(text):
    """requests 예외 메시지에는 요청 URL이 통째로 들어 있어 그대로 찍으면 키가 로그에 남는다."""
    return _SERVICE_KEY_PATTERN.sub(r"\1***", str(text))


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def parse_molit_response(xml_text):
    """정상 응답이면 (item 목록, totalCount) 를 돌려주고, 오류 응답이면 MolitApiError 를 던진다."""
    try:
        data = xmltodict.parse(xml_text)
    except Exception as e:
        raise MolitApiError("INVALID_XML", f"response is not valid XML: {e}") from None

    data = _as_dict(data)

    # 인증·쿼터 단계에서 막힌 요청은 서비스 응답과 다른 최상위 요소로 돌아온다.
    if "OpenAPI_ServiceResponse" in data:
        header = _as_dict(_as_dict(data["OpenAPI_ServiceResponse"]).get("cmmMsgHeader"))
        code = header.get("returnReasonCode") or "UNKNOWN"
        reasons = [header.get("returnAuthMsg"), header.get("errMsg")]
        message = " / ".join(str(reason) for reason in reasons if reason)
        raise MolitApiError(code, message or "no error message in response")

    if "response" not in data:
        raise MolitApiError("UNEXPECTED_FORMAT", "response element is missing")

    response = _as_dict(data["response"])
    header = _as_dict(response.get("header"))
    code = str(header.get("resultCode") or "").strip()
    # 여기까지 온 03 은 서비스가 조회를 마치고 돌려준 '거래 없음'이다.
    # 위의 OpenAPI_ServiceResponse 는 서비스에 닿기 전 인증 단계의 응답이라,
    # 거기서 온 코드는 값이 03 이어도 조회 결과가 아니므로 오류로 둔다.
    if code == NO_DATA_CODE:
        return [], 0
    if code not in SUCCESS_CODES:
        raise MolitApiError(code or "UNKNOWN", header.get("resultMsg") or "resultCode is missing")

    body = _as_dict(response.get("body"))
    try:
        total_count = int(body.get("totalCount") or 0)
    except (TypeError, ValueError):
        raise MolitApiError("INVALID_BODY", "totalCount is not a number") from None

    # 거래가 없는 달은 items 가 빈 요소로 오고, 1건이면 목록이 아니라 단일 항목으로 온다.
    item_list = _as_dict(body.get("items")).get("item") or []
    if isinstance(item_list, dict):
        item_list = [item_list]
    return item_list, total_count
