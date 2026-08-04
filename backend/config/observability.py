"""Sentry 초기화 — 에러 추적의 on/off 와 개인정보 차단을 한 곳에 모은다.

**왜 붙였나**: `fly logs` 는 약 30분치만 남는다. "어제 왜 500 났지"를 사후에
추적할 수단이 없어 2026-07-28 qbank 500 조사에서 실제로 막혔다.

**무엇을 보내나**: 예외와 그 예외가 난 위치(스택·엔드포인트)뿐이다.
학생 이름·전화번호가 담기는 것들은 전부 막는다 —

  - 요청 본문      `max_request_body_size="never"` + before_send 에서 제거
  - 쿼리 값        before_send 에서 마스킹(키는 남긴다)
  - 스택 지역변수  `include_local_variables=False`
  - 쿠키·세션·IP·로그인 계정  `send_default_pii=False`

send_default_pii 하나로는 앞의 셋이 막히지 않는다(각각 다른 옵션 소관이고,
기본 스크러버의 denylist 는 password·token 류만 잡는다 — 이름·전화번호는
그대로 통과한다). 이름과 휴대폰 번호는 미성년 학생의 개인정보이고 Sentry 는
국외 서비스라, 기본값은 **보내지 않는 것**이다.
"""
import logging
from urllib.parse import parse_qsl

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.utils import BadDsn

logger = logging.getLogger(__name__)

FILTERED = "[Filtered]"


def scrub_event(event, _hint):
    """이벤트에서 요청 본문을 버리고 쿼리 값을 마스킹한다(before_send 훅)."""
    request = event.get("request")
    if not request:
        return event

    request.pop("data", None)

    query_string = request.get("query_string")
    if query_string:
        # 키는 남긴다 — 어떤 파라미터가 왔는지는 재현에 필요하고, PII 는 값 쪽에 있다.
        request["query_string"] = "&".join(
            f"{key}={FILTERED}"
            for key, _ in parse_qsl(query_string, keep_blank_values=True)
        )

    return event


def init_sentry(dsn: str) -> bool:
    """DSN 이 있을 때만 Sentry 를 켠다. 켰으면 True.

    DSN 이 비면 아무것도 하지 않는다(로컬·테스트에서 켜지지 않는 이유).
    형식이 잘못된 DSN 에는 부팅을 세우지 않는다 — 관측 도구 시크릿 오타 하나로
    서비스가 내려가면 안 된다. 대신 경고를 남긴다("켠 줄 알았는데 안 켜짐"이 최악).
    """
    if not dsn:
        return False

    try:
        sentry_sdk.init(
            dsn=dsn,
            integrations=[DjangoIntegration()],
            traces_sample_rate=0.1,
            send_default_pii=False,
            max_request_body_size="never",
            include_local_variables=False,
            before_send=scrub_event,
        )
    except BadDsn:
        logger.warning("SENTRY_DSN 형식이 올바르지 않아 Sentry 를 켜지 못했다", exc_info=True)
        return False

    return True
