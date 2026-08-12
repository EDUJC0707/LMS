"""Sentry 초기화 — 에러 추적의 on/off 와 개인정보 차단을 한 곳에 모은다.

**왜 붙였나**: 2026-07-28 qbank 500 을 사후 추적하지 못했다. 오래 "`fly logs` 가
30분치만 남아서" 라고 적어 뒀는데 **틀렸다**(2026-08-05 확인) — Fly 는 약 7일 보관하고,
`fly logs --no-tail` 이 마지막 100줄만 보여 준 것이었다(실측: 100줄 정확히).
막힌 것은 보관 기간이 아니라 도구였다. 그래도 Sentry 가 하는 일은 로그와 다르다 —
같은 예외를 이슈 하나로 묶고, 어느 배포에서 났는지 태그하고, 묻지 않아도 알려준다.
"어제 왜 500 났지"를 사후에
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


def init_sentry(dsn: str, *, release: str = "") -> bool:
    """DSN 이 있을 때만 Sentry 를 켠다. 켰으면 True.

    DSN 이 비면 아무것도 하지 않는다(로컬·테스트에서 켜지지 않는 이유).
    형식이 잘못된 DSN 에는 부팅을 세우지 않는다 — 관측 도구 시크릿 오타 하나로
    서비스가 내려가면 안 된다. 대신 경고를 남긴다("켠 줄 알았는데 안 켜짐"이 최악).

    `release` 는 이 에러가 **어느 배포**에서 났는지다. 빌드가 넣어 준다
    (`infra/Dockerfile` 의 `GIT_SHA` 빌드 인자 → `SENTRY_RELEASE`).

    비어 있으면 SDK 가 **현재 폴더의 git 에서 추론**한다(2026-08-04 실측: 생략과
    None 은 동작이 같고, 억제하려면 빈 문자열을 넘겨야 하는데 그러면 이벤트에 빈
    release 가 붙는다). 운영 이미지에는 `.git` 이 없어 추론이 실패하므로 결과적으로
    release 없이 뜬다 — 그래서 빌드 인자를 안 넘기면 조용히 태그가 사라진다.
    """
    if not dsn:
        return False

    try:
        sentry_sdk.init(
            dsn=dsn,
            release=release or None,
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
