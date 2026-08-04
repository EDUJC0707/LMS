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

## 스페이스에 거는 두 가지 — 입장 통제와 감독 자료

**`accessType: TRUSTED`** — 링크만 가진 사람은 못 들어오고 노크해야 한다.
조교가 조직 계정으로 먼저 들어가 호스트가 되고 학생을 수락하는 것이 운영
전제다(클리닉은 한 타임 1명뿐이라 계정 1개로 성립 — decisions.md §4).
LMS 가 링크를 시작 5분 전에 그 학생에게만 내리는 것(booking.request_block)과
합쳐 이중 통제가 된다(PRD 6-3 '입장 통제'). `OPEN` 이면 링크가 새는 순간
아무나 1:1 과외 자리에 앉는다.

**`artifactConfig`: 전사 ON · Gemini 요약 ON · 녹화 OFF** — PRD 8-5 확정
(2026-07-17). 미트에는 오디오 전용 녹음이 없어서 전사와 AI 요약이 조교 감독
자료를 대신한다(`ClinicEvaluation.transcript_ref`·`ai_summary` 가 받을 자리).
전사와 요약은 **문서 한 개**에 함께 담긴다(실측: 둘의 document ID 가 같다).
**스페이스를 만들 때 걸어 둔다** — 조교가 회의 중에 버튼을 누르는 것에 기대면
안 눌린 회차가 반드시 나오고, 그 회차는 평가할 근거가 통째로 없다.

**"자동"에 갈래가 셋이라 헷갈리기 쉽다**(2026-08-04 재조사, PRD 8-5):
전사 기능 자체와 **회의별 사전 설정(우리가 쓰는 것)** 은 Business Standard 에서
지원되고, **관리자 콘솔의 조직 전체 자동 설정**만 Business Plus 이상이다.
현 테넌트 `hjcedu.com` 은 Standard 이고 API 는 200 + 되읽기 `ON` 으로 받는다.

발동 조건은 "**전사 권한이 있는 사람이 회의에 입장할 때**"다. 그래서 조교가
**웹 브라우저로, 호스트 계정으로** 들어가야 한다 — 모바일 앱 입장으로는 자동
전사가 시작되지 않는다. 실제 회의로 확인한 적은 아직 없다(미결 8-20).

전사는 회의 종료 후 **30일만** API 로 조회된다(`conferenceRecords.transcripts`).
수집 배치는 아직 없다 — 그때까지는 주최자 드라이브에 남는 문서가 원본이다.

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

#: 스페이스 생성. 본문은 비어도 되지만 우리는 설정을 실어 보낸다(위 머리말).
SPACES_ENDPOINT = "https://meet.googleapis.com/v2/spaces"

#: 새 스페이스에 거는 설정 — 왜 이 값들인지는 머리말 참조. 바꾸려면 PRD 6-3·8-5
#: 를 먼저 보고 바꿔라(둘 다 여기로 착지하는 결정이다).
SPACE_CONFIG = {
    "accessType": "TRUSTED",
    "artifactConfig": {
        "recordingConfig": {"autoRecordingGeneration": "OFF"},
        "transcriptionConfig": {"autoTranscriptionGeneration": "ON"},
        "smartNotesConfig": {"autoSmartNotesGeneration": "ON"},
    },
}

#: 동의받는 권한 전부. 하나라도 빠지면 그 기능이 조용히 403 이 되므로 여기가
#: 유일한 목록이고 동의 화면도 이 값을 그대로 쓴다.
#:
#: **`drive` 는 넓다** — 그 계정 드라이브 전부를 읽고 쓴다. 좁히려고 두 번
#: 시도했고 두 번 다 막혔다(2026-08-04 실측):
#:   - `drive.meet.readonly` → 파일 존재·이름은 보이는데 본문이 404
#:   - `drive.readonly`      → 본문은 읽히지만 파일을 옮기고 이름을 바꿀 수 없다
#: 구글에 "미트가 만든 파일만 읽고 쓰기" 라는 권한은 없다(2026-08-04 사용자 결정).
#: 그래서 이 계정 드라이브에 **클리닉 감독 자료 말고 다른 것을 두지 않는 것**이
#: 실질적인 방어선이다 — 권한으로는 더 좁힐 수 없다.
SCOPES = (
    "https://www.googleapis.com/auth/meetings.space.created",
    "https://www.googleapis.com/auth/drive",
)

#: 관리자가 배정 버튼을 누른 채 기다리는 시간 — 동기 호출이라 짧게 잡는다.
TIMEOUT_SECONDS = 10

#: 다시 걸어볼 값어치가 있는 상태 코드(그 외 4xx 는 영구).
_RETRYABLE_STATUSES = frozenset({408, 429})


def urllib_transport(method, url, body, headers, timeout):
    """기본 전송 — (status, body bytes). 4xx·5xx 도 예외가 아니라 값으로 돌린다.

    해석은 어댑터의 일이라(`conferencing.py` 계약) 전송은 상태 코드를 그대로
    넘기고 판단하지 않는다.
    """
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
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
            json.dumps({"config": SPACE_CONFIG}).encode(),
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
        return self._send("POST", url, body, headers)

    def _get(self, url, token):
        """토큰만 붙는 조회. 감독 자료 수집이 전부 이 경로를 쓴다."""
        return self._send("GET", url, None, {"Authorization": f"Bearer {token}"})

    def _send(self, method, url, body, headers):
        try:
            return self.transport(method, url, body, headers, TIMEOUT_SECONDS)
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
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }
    )


def exchange_code(client_id, client_secret, code, redirect_uri, transport=None):
    """인가 코드 → **갱신 토큰**. 액세스 토큰은 버린다(수명이 한 시간이라 쓸모없다)."""
    post = transport or urllib_transport
    try:
        status, body = post(
            "POST",
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
