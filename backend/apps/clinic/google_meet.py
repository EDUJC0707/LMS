"""구글 미트 어댑터 — 업체 지식은 전부 이 파일 안에 있다.

모델도 배정 서비스도 "구글"을 모른다. 업체를 갈아 끼우는 일은 이 파일을 하나 더
쓰고 `CLINIC_CONFERENCE_BACKEND` 를 바꾸는 것이 전부다(스키마 불변 —
`conferencing.py` 계약).

## 왜 서비스 계정이 아니라 갱신 토큰인가

구글 문서: **Meet REST API 는 사용자 인증만 받는다**(service account 는 워크스페이스
도메인 전체 위임을 걸어 사용자를 가장할 때만 성립한다). 우리는 계정 1개로 운영하고
(key_considerations §4 "구글 미트 API 계정 1개") 그 계정이 개인 계정일 수도 있으므로,
**한 번 동의받아 받은 갱신 토큰**을 서버가 들고 매번 액세스 토큰으로 바꿔 쓴다.
동의는 사람이 브라우저에서 한 번 해야 하고, 그 절차는
`manage.py meet_authorize` 가 대신한다.

액세스 토큰을 캐시하지 않는다. 클리닉 배정은 하루에 많아야 수십 건이라 요청
1건당 토큰 요청 1건이 붙어도 비용이 없고, 캐시를 두면 프로세스마다 다른 만료를
들고 도는 문제(gunicorn 워커 다중)를 공짜로 얻는다.

## 왜 accessType 을 OPEN 으로 만드나

스페이스를 만든 계정은 **회의에 들어가지 않는다**. 기본값(`ACCESS_TYPE_UNSPECIFIED`
= 계정 관리자 설정 따름)이면 링크로 들어온 학생·조교가 입장 승인을 기다리는데,
승인해 줄 사람이 회의에 없다 — 클리닉이 통째로 성립하지 않는다. 링크는 시작 5분
전부터 그 학생에게만 내려가고(booking.request_block) 클리닉 1건마다 새 스페이스라
(§4 링크 재사용 금지), 노출 범위는 이미 그쪽에서 좁혀져 있다.

## HTTP 는 표준 라이브러리로 한다

요청이 둘(토큰·스페이스)뿐이고 둘 다 단순 POST 라 의존성을 하나 더 들일 값어치가
없다. 대신 전송을 주입할 수 있게 열어 두어(`transport`) 테스트가 실제 구글을
부르지 않는다.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

from .conferencing import (
    Conference,
    ConferenceAdapter,
    PermanentConferenceError,
    TemporaryConferenceError,
)

#: OAuth2 동의 화면 — 사람이 브라우저에서 한 번 들르는 곳(`meet_authorize`).
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"

#: OAuth2 토큰 교환(갱신 토큰 → 액세스 토큰, 인가 코드 → 갱신 토큰).
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

#: 스페이스 생성. 본문은 비어도 되지만 우리는 accessType 을 실어 보낸다(위 머리말).
SPACES_ENDPOINT = "https://meet.googleapis.com/v2/spaces"

#: 스페이스 생성에 필요한 유일한 스코프. 동의 화면과 여기가 같은 값을 써야 한다.
SCOPE = "https://www.googleapis.com/auth/meetings.space.created"

#: 관리자가 배정 버튼을 누른 채 기다리는 시간 — 동기 호출이라 짧게 잡는다.
TIMEOUT_SECONDS = 10

#: 다시 걸어볼 값어치가 있는 상태 코드(그 외 4xx 는 영구).
_RETRYABLE_STATUSES = frozenset({408, 429})


def urllib_transport(url, body, headers, timeout):
    """기본 전송 — (status, body bytes). 4xx·5xx 도 예외가 아니라 값으로 돌린다.

    해석은 어댑터의 일이라(`conferencing.py` 계약) 전송은 상태 코드를 그대로
    넘기고 판단하지 않는다.
    """
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


class GoogleMeetAdapter(ConferenceAdapter):
    """클리닉 1건마다 새 미팅 스페이스를 만든다."""

    def __init__(self, transport=None):
        self.transport = transport or urllib_transport

    def create_space(self) -> Conference:
        access_token = self._access_token()
        status, body = self._post(
            SPACES_ENDPOINT,
            json.dumps({"config": {"accessType": "OPEN"}}).encode(),
            {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
        if status != 200:
            raise self._translate(status, body, "화상 스페이스를 만들지 못했습니다")
        payload = self._json(body)
        ref = payload.get("name")
        url = payload.get("meetingUri")
        if not ref or not url:
            # 200 인데 쓸 값이 없다 = 계약 위반. 빈 링크를 저장하면 학생에게
            # 빈 안내가 나간다(조용한 성공 금지 — key_considerations §5).
            raise PermanentConferenceError(
                "화상 응답에 스페이스 이름 또는 참가 링크가 없습니다."
            )
        return Conference(
            provider="google_meet",
            ref=ref,
            url=url,
        )

    # -- OAuth -------------------------------------------------------------

    def _access_token(self):
        client_id = (getattr(settings, "GOOGLE_MEET_CLIENT_ID", "") or "").strip()
        client_secret = (getattr(settings, "GOOGLE_MEET_CLIENT_SECRET", "") or "").strip()
        refresh_token = (getattr(settings, "GOOGLE_MEET_REFRESH_TOKEN", "") or "").strip()
        if not (client_id and client_secret and refresh_token):
            raise PermanentConferenceError(
                "구글 미트 자격증명이 설정되지 않았습니다"
                "(GOOGLE_MEET_CLIENT_ID·CLIENT_SECRET·REFRESH_TOKEN)."
            )
        status, body = self._post(
            TOKEN_ENDPOINT,
            urllib.parse.urlencode(
                {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                }
            ).encode(),
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        if status != 200:
            # invalid_grant = 갱신 토큰이 철회·만료됐다. 사람이 다시 동의해야
            # 하므로 재시도로는 절대 풀리지 않는다(meet_authorize 재실행).
            raise self._translate(status, body, "구글 액세스 토큰을 받지 못했습니다")
        token = self._json(body).get("access_token")
        if not token:
            raise PermanentConferenceError("구글 토큰 응답에 access_token 이 없습니다.")
        return token

    # -- 공통 --------------------------------------------------------------

    def _post(self, url, body, headers):
        try:
            return self.transport(url, body, headers, TIMEOUT_SECONDS)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise TemporaryConferenceError(f"구글에 닿지 못했습니다: {error}") from error

    def _json(self, body):
        try:
            payload = json.loads(body.decode())
        except (ValueError, UnicodeDecodeError) as error:
            raise PermanentConferenceError(f"구글 응답을 읽을 수 없습니다: {error}") from error
        if not isinstance(payload, dict):
            raise PermanentConferenceError("구글 응답 형식이 올바르지 않습니다.")
        return payload

    def _translate(self, status, body, prefix):
        """상태 코드 → 예외 종류. 재시도 정책이 갈리는 유일한 지점이다."""
        detail = body.decode(errors="replace")[:200]
        message = f"{prefix}({status}): {detail}"
        if status in _RETRYABLE_STATUSES or status >= 500:
            return TemporaryConferenceError(message)
        return PermanentConferenceError(message)


# --- 1회성 동의(갱신 토큰 발급) -------------------------------------------
# 여기부터는 운영 중에 돌지 않는다. `manage.py meet_authorize` 가 한 번 부르고,
# 그 결과(갱신 토큰)를 사람이 시크릿에 넣으면 끝이다. 그래도 이 파일에 두는
# 이유는 구글 지식이 두 파일로 갈리지 않게 하기 위해서다(머리말 계약).


def build_consent_url(client_id, redirect_uri):
    """동의 화면 URL. 사람이 이 주소를 열어 계정을 고르고 승인한다.

    `access_type=offline` 이 없으면 갱신 토큰이 아예 오지 않고, `prompt=consent`
    가 없으면 **이미 동의한 계정에서는 두 번째부터** 오지 않는다 — 둘 다 빠뜨리기
    쉬운 자리라 값으로 못 박는다.
    """
    return f"{AUTH_ENDPOINT}?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }
    )


def exchange_code(client_id, client_secret, code, redirect_uri, transport=None):
    """인가 코드 → **갱신 토큰**. 액세스 토큰은 버린다(수명이 한 시간이라 쓸모없다)."""
    post = transport or urllib_transport
    try:
        status, body = post(
            TOKEN_ENDPOINT,
            urllib.parse.urlencode(
                {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                }
            ).encode(),
            {"Content-Type": "application/x-www-form-urlencoded"},
            TIMEOUT_SECONDS,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise TemporaryConferenceError(f"구글에 닿지 못했습니다: {error}") from error
    if status != 200:
        raise PermanentConferenceError(
            f"인가 코드를 토큰으로 바꾸지 못했습니다({status}): "
            f"{body.decode(errors='replace')[:200]}"
        )
    try:
        payload = json.loads(body.decode())
    except (ValueError, UnicodeDecodeError) as error:
        raise PermanentConferenceError(f"구글 응답을 읽을 수 없습니다: {error}") from error
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise PermanentConferenceError(
            "응답에 갱신 토큰이 없습니다 — 이미 동의한 계정입니다. "
            "https://myaccount.google.com/permissions 에서 이 앱의 접근을 지우고 다시 실행하세요."
        )
    return refresh_token
