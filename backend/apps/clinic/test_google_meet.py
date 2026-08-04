"""구글 미트 어댑터 검증 — HTTP 는 주입한 전송으로 갈음한다.

실제 구글을 부르지 않는다. 대신 **무엇을 어디로 보내는가**(토큰 갱신 요청,
스페이스 생성 요청의 URL·헤더·본문)와 **응답을 어떻게 번역하는가**
(Temporary / Permanent)를 고정한다 — 어댑터의 일이 그 둘이기 때문이다.
"""
import json
import urllib.error

from django.test import SimpleTestCase, override_settings

from .conferencing import PermanentConferenceError, TemporaryConferenceError
from .google_meet import (
    AUTH_ENDPOINT,
    SCOPES,
    SPACES_ENDPOINT,
    TOKEN_ENDPOINT,
    GoogleMeetAdapter,
    build_consent_url,
    exchange_code,
)

CREDENTIALS = {
    "GOOGLE_MEET_CLIENT_ID": "cid.apps.googleusercontent.com",
    "GOOGLE_MEET_CLIENT_SECRET": "secret",
    "GOOGLE_MEET_REFRESH_TOKEN": "1//refresh",
}

TOKEN_OK = (200, json.dumps({"access_token": "ya29.token", "expires_in": 3599}).encode())
SPACE_OK = (
    200,
    json.dumps(
        {
            "name": "spaces/jQCFfuBOdN5z",
            "meetingUri": "https://meet.google.com/abc-mnop-xyz",
            "meetingCode": "abc-mnop-xyz",
        }
    ).encode(),
)


class FakeTransport:
    """호출 순서대로 준비된 응답을 내준다. 예외를 넣으면 그 자리에서 던진다."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, body, headers, timeout):
        self.calls.append(
            {"method": method, "url": url, "body": body, "headers": headers, "timeout": timeout}
        )
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def form_fields(body):
    """form-encoded 본문을 dict 로 — 토큰 요청 검증용."""
    from urllib.parse import parse_qs

    return {k: v[0] for k, v in parse_qs(body.decode()).items()}


@override_settings(**CREDENTIALS)
class CreateSpaceTests(SimpleTestCase):
    def test_returns_neutral_conference(self):
        transport = FakeTransport(TOKEN_OK, SPACE_OK)
        conference = GoogleMeetAdapter(transport=transport).create_space()
        self.assertEqual(conference.provider, "google_meet")
        # 오래 가는 식별자는 스페이스 이름이다(미팅 코드가 아니라)
        self.assertEqual(conference.ref, "spaces/jQCFfuBOdN5z")
        self.assertEqual(conference.url, "https://meet.google.com/abc-mnop-xyz")

    def test_token_call_uses_refresh_grant(self):
        transport = FakeTransport(TOKEN_OK, SPACE_OK)
        GoogleMeetAdapter(transport=transport).create_space()
        token_call = transport.calls[0]
        self.assertEqual(token_call["url"], TOKEN_ENDPOINT)
        self.assertEqual(
            form_fields(token_call["body"]),
            {
                "client_id": "cid.apps.googleusercontent.com",
                "client_secret": "secret",
                "refresh_token": "1//refresh",
                "grant_type": "refresh_token",
            },
        )

    def test_space_call_carries_bearer_token(self):
        transport = FakeTransport(TOKEN_OK, SPACE_OK)
        GoogleMeetAdapter(transport=transport).create_space()
        space_call = transport.calls[1]
        self.assertEqual(space_call["url"], SPACES_ENDPOINT)
        self.assertEqual(space_call["headers"]["Authorization"], "Bearer ya29.token")

    def test_students_have_to_knock(self):
        # PRD 6-3 '입장 통제' — 링크만 가진 사람은 못 들어온다. 조교가 조직
        # 계정으로 먼저 들어가 호스트가 되고 학생을 수락한다(조사 문서 §3·§4).
        # OPEN 이면 링크가 새는 순간 아무나 클리닉에 앉아 있게 된다.
        transport = FakeTransport(TOKEN_OK, SPACE_OK)
        GoogleMeetAdapter(transport=transport).create_space()
        body = json.loads(transport.calls[1]["body"].decode())
        self.assertEqual(body["config"]["accessType"], "TRUSTED")

    def test_transcript_and_summary_are_on_recording_is_off(self):
        # PRD 8-5 확정(2026-07-17): 오디오 전용 녹음이 미트에 없어서 **전사 +
        # Gemini 요약**으로 감독 목적을 달성한다. 녹화는 하지 않는다.
        # 회의별 강제 지점이 여기(artifactConfig)라 스페이스를 만들 때 건다 —
        # 조교가 매번 버튼을 누르는 것에 기대면 안 눌린 회차가 반드시 나온다.
        transport = FakeTransport(TOKEN_OK, SPACE_OK)
        GoogleMeetAdapter(transport=transport).create_space()
        artifacts = json.loads(transport.calls[1]["body"].decode())["config"]["artifactConfig"]
        self.assertEqual(artifacts["transcriptionConfig"]["autoTranscriptionGeneration"], "ON")
        self.assertEqual(artifacts["smartNotesConfig"]["autoSmartNotesGeneration"], "ON")
        self.assertEqual(artifacts["recordingConfig"]["autoRecordingGeneration"], "OFF")

    def test_each_call_makes_a_new_space(self):
        # 클리닉 1건 = 새 스페이스 1개(링크 재사용 금지 — §4)
        transport = FakeTransport(TOKEN_OK, SPACE_OK, TOKEN_OK, SPACE_OK)
        adapter = GoogleMeetAdapter(transport=transport)
        adapter.create_space()
        adapter.create_space()
        self.assertEqual([c["url"] for c in transport.calls].count(SPACES_ENDPOINT), 2)


class CredentialTests(SimpleTestCase):
    @override_settings(
        GOOGLE_MEET_CLIENT_ID="", GOOGLE_MEET_CLIENT_SECRET="", GOOGLE_MEET_REFRESH_TOKEN=""
    )
    def test_missing_credentials_never_touches_the_network(self):
        transport = FakeTransport(TOKEN_OK, SPACE_OK)
        with self.assertRaises(PermanentConferenceError):
            GoogleMeetAdapter(transport=transport).create_space()
        self.assertEqual(transport.calls, [])

    @override_settings(**{**CREDENTIALS, "GOOGLE_MEET_REFRESH_TOKEN": ""})
    def test_partial_credentials_are_permanent(self):
        transport = FakeTransport(TOKEN_OK, SPACE_OK)
        with self.assertRaises(PermanentConferenceError):
            GoogleMeetAdapter(transport=transport).create_space()


@override_settings(**CREDENTIALS)
class FailureTranslationTests(SimpleTestCase):
    def create(self, *responses):
        return GoogleMeetAdapter(transport=FakeTransport(*responses)).create_space()

    def test_revoked_refresh_token_is_permanent(self):
        # invalid_grant = 사람이 다시 동의해야 한다. 재시도로는 절대 안 풀린다.
        with self.assertRaises(PermanentConferenceError):
            self.create((400, b'{"error":"invalid_grant"}'))

    def test_server_error_is_temporary(self):
        with self.assertRaises(TemporaryConferenceError):
            self.create(TOKEN_OK, (500, b"{}"))

    def test_rate_limit_is_temporary(self):
        with self.assertRaises(TemporaryConferenceError):
            self.create(TOKEN_OK, (429, b"{}"))

    def test_forbidden_is_permanent(self):
        # 스코프 미승인·API 미활성 — 몇 번을 걸어도 같다
        with self.assertRaises(PermanentConferenceError):
            self.create(TOKEN_OK, (403, b'{"error":{"message":"insufficient scope"}}'))

    def test_network_failure_is_temporary(self):
        with self.assertRaises(TemporaryConferenceError):
            self.create(urllib.error.URLError("connection refused"))

    def test_timeout_is_temporary(self):
        with self.assertRaises(TemporaryConferenceError):
            self.create(TOKEN_OK, TimeoutError("timed out"))

    def test_response_without_join_url_is_permanent(self):
        # 200 인데 우리가 쓸 값이 없다 = 계약 위반. 빈 링크를 저장하면
        # 학생에게 빈 안내가 나간다(조용한 성공 금지).
        with self.assertRaises(PermanentConferenceError):
            self.create(TOKEN_OK, (200, json.dumps({"name": "spaces/x"}).encode()))

    def test_unparseable_response_is_permanent(self):
        with self.assertRaises(PermanentConferenceError):
            self.create(TOKEN_OK, (200, b"<html>oops</html>"))


class ConsentFlowTests(SimpleTestCase):
    """갱신 토큰을 받아 오는 1회성 동의 절차(`manage.py meet_authorize`)."""

    def query(self, url):
        from urllib.parse import parse_qs, urlsplit

        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}{parts.path}", {
            k: v[0] for k, v in parse_qs(parts.query).items()
        }

    def test_consent_url_asks_for_every_scope_we_use(self):
        base, params = self.query(build_consent_url("cid", "http://localhost:8765/"))
        self.assertEqual(base, AUTH_ENDPOINT)
        self.assertEqual(params["scope"], " ".join(SCOPES))
        self.assertEqual(params["client_id"], "cid")
        self.assertEqual(params["redirect_uri"], "http://localhost:8765/")
        self.assertEqual(params["response_type"], "code")

    def test_scopes_are_the_two_we_need_and_no_more(self):
        # 스페이스 생성 + 감독 문서 읽기·정리.
        # 좁은 권한을 두 번 시도했다가 두 번 다 막혔다(2026-08-04 실측):
        # `drive.meet.readonly` 는 파일 존재까지만 보이고 본문이 404 였고,
        # 파일을 우리 폴더 구조로 옮기는 것은 **쓰기**라 읽기 권한으로 안 된다.
        # 구글에 "미트가 만든 파일만 읽고 쓰기" 는 없다.
        self.assertEqual(
            list(SCOPES),
            [
                "https://www.googleapis.com/auth/meetings.space.created",
                "https://www.googleapis.com/auth/drive",
            ],
        )

    def test_consent_url_forces_a_refresh_token(self):
        # access_type=offline 없이는 갱신 토큰이 아예 안 오고, prompt=consent
        # 없이는 **두 번째 동의부터** 안 온다(이미 동의한 계정).
        _, params = self.query(build_consent_url("cid", "http://localhost:8765/"))
        self.assertEqual(params["access_type"], "offline")
        self.assertEqual(params["prompt"], "consent")

    def test_exchange_returns_the_refresh_token(self):
        transport = FakeTransport(
            (200, json.dumps({"refresh_token": "1//new", "access_token": "ya29.x"}).encode())
        )
        token = exchange_code(
            "cid", "secret", "4/code", "http://localhost:8765/", transport=transport
        )
        self.assertEqual(token, "1//new")
        self.assertEqual(transport.calls[0]["url"], TOKEN_ENDPOINT)
        self.assertEqual(
            form_fields(transport.calls[0]["body"])["grant_type"], "authorization_code"
        )

    def test_response_without_refresh_token_is_permanent(self):
        # 이미 동의한 계정이라 access_token 만 왔다 = 우리가 쓸 것이 없다
        transport = FakeTransport((200, json.dumps({"access_token": "ya29.x"}).encode()))
        with self.assertRaises(PermanentConferenceError):
            exchange_code(
                "cid", "secret", "4/code", "http://localhost:8765/", transport=transport
            )

    def test_rejected_code_is_permanent(self):
        transport = FakeTransport((400, b'{"error":"invalid_grant"}'))
        with self.assertRaises(PermanentConferenceError):
            exchange_code(
                "cid", "secret", "4/bad", "http://localhost:8765/", transport=transport
            )
