"""구글 미트 어댑터 검증 — HTTP 는 주입한 전송으로 갈음한다.

실제 구글을 부르지 않는다. 대신 **무엇을 어디로 보내는가**(토큰 갱신 요청,
스페이스 생성 요청의 URL·헤더·본문)와 **응답을 어떻게 번역하는가**
(Temporary / Permanent)를 고정한다 — 어댑터의 일이 그 둘이기 때문이다.
"""
import datetime
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

    def test_nobody_knocks(self):
        # ~~TRUSTED(노크 → 호스트 수락)~~ → **OPEN**(2026-08-13 사용자 확정).
        #
        # 노크는 조교가 매 회차 눌러야 하는 유일한 단계였고, 감독 기록을 남기는
        # 봇까지 같은 로비에 서면서 **조교가 봇을 안 들이면 그 회차 기록이
        # 통째로 없어지는** 구조가 됐다(에러도 안 난다). 사람 손을 0 으로
        # 만드는 것이 감독 체계의 전제라 로비를 없앤다.
        #
        # 통제가 사라지는 게 아니라 **한 겹으로 준다**: 클리닉 1건 = 새 스페이스
        # 1개(재사용 없음) + 링크는 배정된 그 학생에게 시작 5분 전부터만 보인다.
        # 이 상태에서 링크가 새려면 그 학생이 직접 남에게 넘겨야 하고, 그런
        # 경우라면 노크가 있어도 조교가 수락해 준다 — 노크가 실제로 막던 것은
        # "링크를 우연히 주운 외부인" 뿐이었다.
        transport = FakeTransport(TOKEN_OK, SPACE_OK)
        GoogleMeetAdapter(transport=transport).create_space()
        body = json.loads(transport.calls[1]["body"].decode())
        self.assertEqual(body["config"]["accessType"], "OPEN")

    def test_google_records_nothing_now_that_the_bot_does(self):
        # ~~전사·요약 ON~~ → **전부 OFF**(2026-08-12 전면 교체).
        # 감독 자료는 Fireflies 봇이 만든다. 구글까지 같이 켜 두면 ①안 쓰는
        # 회의록이 드라이브에 클리닉마다 하나씩 쌓이고 ②학생에게 녹취 안내가
        # **두 번** 뜬다. 구글을 켜 둘 이유였던 "아이패드에서 안 켜진다"가
        # 그대로 남아 있어서 어차피 조교 기기에 따라 있다 없다 한다.
        # 되돌리는 것은 이 세 줄이다 — 어댑터 토글과는 별개 스위치다.
        transport = FakeTransport(TOKEN_OK, SPACE_OK)
        GoogleMeetAdapter(transport=transport).create_space()
        artifacts = json.loads(transport.calls[1]["body"].decode())["config"]["artifactConfig"]
        self.assertEqual(artifacts["transcriptionConfig"]["autoTranscriptionGeneration"], "OFF")
        self.assertEqual(artifacts["smartNotesConfig"]["autoSmartNotesGeneration"], "OFF")
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

    def test_scopes_are_the_three_we_need_and_no_more(self):
        # 스페이스 생성 + 감독 문서 읽기·정리 + 일정 만들기.
        # 좁은 권한을 두 번 시도했다가 두 번 다 막혔다(2026-08-04 실측):
        # `drive.meet.readonly` 는 파일 존재까지만 보이고 본문이 404 였고,
        # 파일을 우리 폴더 구조로 옮기는 것은 **쓰기**라 읽기 권한으로 안 된다.
        # 구글에 "미트가 만든 파일만 읽고 쓰기" 는 없다.
        #
        # 캘린더는 2026-08-12 에 붙었다. 감독 봇을 우리가 1분마다 밀어 넣는
        # 대신 **일정에 걸어 두면 업체가 시작 시각에 알아서 들어오기** 때문이다.
        # `calendar` 전체가 아니라 `calendar.events` 인 이유: 우리가 하는 일은
        # 클리닉 일정 하나를 만들고 고치고 지우는 것뿐이고, 달력 자체를
        # 만들거나 남의 달력 설정을 건드릴 일이 없다.
        self.assertEqual(
            list(SCOPES),
            [
                "https://www.googleapis.com/auth/meetings.space.created",
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/calendar.events",
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


CALENDAR_OK = (200, json.dumps({"id": "clinic11"}).encode())
#: 토큰 주인이 누구인가 — 드라이브에 묻는다(캘린더 스코프로는 403).
CALENDAR_ME = (200, json.dumps({"user": {"emailAddress": "hjcedu@hjcedu.com"}}).encode())


class CalendarEventTests(SimpleTestCase):
    """캘린더 일정 — 감독 봇이 시작 시각을 아는 유일한 경로."""

    @override_settings(**CREDENTIALS)
    def test_writes_the_meeting_link_where_a_notetaker_can_see_it(self):
        transport = FakeTransport(TOKEN_OK, CALENDAR_ME, CALENDAR_OK)
        GoogleMeetAdapter(transport=transport).upsert_event(
            "clinic11",
            title="clinic/2026-08/2026-08-13_1700_김하늘0001",
            url="https://meet.google.com/a-b-c",
            starts_at="2026-08-13T17:00:00+09:00",
            minutes=60,
        )
        body = json.loads(transport.calls[2]["body"].decode())
        # 제목이 곧 전사 제목이 된다 — 되찾는 열쇠라 그대로 실어야 한다
        self.assertEqual(body["summary"], "clinic/2026-08/2026-08-13_1700_김하늘0001")
        # 구글은 **캘린더가 새로 만든** 미트만 정식 회의 필드에 넣어 준다.
        # 이미 있는 스페이스 링크는 글자로 실어야 봇이 본다 — 두 자리 모두에.
        self.assertEqual(body["location"], "https://meet.google.com/a-b-c")
        self.assertIn("https://meet.google.com/a-b-c", body["description"])
        self.assertEqual(body["start"]["dateTime"], "2026-08-13T17:00:00+09:00")

    @override_settings(**CREDENTIALS)
    def test_computes_the_end_from_the_slot_length(self):
        # 실제로 오는 것은 문자열이 아니라 datetime 이다 — 끝 시각을 여기서
        # 만든다(캘린더는 start 만으론 일정을 못 세운다).
        transport = FakeTransport(TOKEN_OK, CALENDAR_ME, CALENDAR_OK)
        start = datetime.datetime(2026, 8, 13, 17, 0, tzinfo=datetime.UTC)
        GoogleMeetAdapter(transport=transport).upsert_event(
            "clinic11", title="t", url="https://x/a", starts_at=start, minutes=60
        )
        body = json.loads(transport.calls[2]["body"].decode())
        self.assertEqual(body["start"]["dateTime"], "2026-08-13T17:00:00+00:00")
        self.assertEqual(body["end"]["dateTime"], "2026-08-13T18:00:00+00:00")

    @override_settings(**CREDENTIALS)
    def test_puts_the_org_account_on_the_guest_list(self):
        # 회의록 봇의 참석 규칙은 **참석자**를 본다(도메인·내부 회의 여부).
        # 참석자가 비어 있으면 볼 것이 없어 규칙이 걸리지 않는다.
        # 학생은 구글 계정이 아니라 외부 게스트라 여기 넣을 수 없고, 조직
        # 계정 하나만 있으면 "내부 회의"로 읽힌다.
        transport = FakeTransport(TOKEN_OK, CALENDAR_ME, CALENDAR_OK)
        GoogleMeetAdapter(transport=transport).upsert_event(
            "clinic11", title="t", url="https://x/a",
            starts_at="2026-08-13T17:00:00+09:00", minutes=60,
        )
        body = json.loads(transport.calls[2]["body"].decode())
        self.assertEqual(body["attendees"], [{"email": "hjcedu@hjcedu.com"}])

    @override_settings(**CREDENTIALS)
    def test_creates_with_our_own_id(self):
        # **PUT 으로는 못 만든다** — 구글 캘린더에서 PUT 은 이미 있는 일정만
        # 고치고 없으면 404 다(2026-08-12 실측: 배정이 조용히 예약을 못 걸었다).
        # 만들기는 POST 이고 ID 는 본문에 담는다.
        transport = FakeTransport(TOKEN_OK, CALENDAR_ME, CALENDAR_OK)
        GoogleMeetAdapter(transport=transport).upsert_event(
            "clinic11", title="t", url="https://x/a",
            starts_at="2026-08-13T17:00:00+09:00", minutes=60,
        )
        self.assertEqual(transport.calls[2]["method"], "POST")
        self.assertEqual(json.loads(transport.calls[2]["body"].decode())["id"], "clinic11")

    @override_settings(**CREDENTIALS)
    def test_the_same_clinic_overwrites_its_own_event(self):
        # 시간 변경이 예약을 **하나 더** 만들면 봇이 옛 시각에도 들어간다.
        # 일정 ID 를 클리닉에서 정해 두면 이미 있을 때 409 가 오고, 그때
        # 덮어쓴다 — 어느 일정이 그 클리닉 것인지 적어 둘 컬럼이 필요 없다.
        transport = FakeTransport(TOKEN_OK, CALENDAR_ME, (409, b"duplicate"), CALENDAR_OK)
        GoogleMeetAdapter(transport=transport).upsert_event(
            "clinic11", title="t", url="https://x/a",
            starts_at="2026-08-13T17:00:00+09:00", minutes=60,
        )
        self.assertEqual(transport.calls[3]["method"], "PUT")
        self.assertIn("/events/clinic11", transport.calls[3]["url"])

    @override_settings(**CREDENTIALS)
    def test_deleting_an_event_that_is_already_gone_is_fine(self):
        # 취소를 두 번 눌러도, 애초에 예약이 없어도 조용히 끝나야 한다.
        transport = FakeTransport(TOKEN_OK, (404, b"not found"))
        GoogleMeetAdapter(transport=transport).delete_event("clinic11")
        self.assertEqual(transport.calls[1]["method"], "DELETE")

    @override_settings(**CREDENTIALS)
    def test_a_server_error_while_deleting_is_temporary(self):
        transport = FakeTransport(TOKEN_OK, (503, b"upstream"))
        with self.assertRaises(TemporaryConferenceError):
            GoogleMeetAdapter(transport=transport).delete_event("clinic11")


FOLDER_FOUND = (200, json.dumps({"files": [{"id": "folder-1"}]}).encode())
FOLDER_NONE = (200, json.dumps({"files": []}).encode())
FOLDER_MADE = (200, json.dumps({"id": "folder-1"}).encode())
UPLOADED = (
    200,
    json.dumps(
        {"id": "file-1", "webViewLink": "https://docs.google.com/document/d/file-1/edit"}
    ).encode(),
)


@override_settings(**CREDENTIALS)
class DriveArchiveTests(SimpleTestCase):
    """감독 자료를 **우리 드라이브**에 남긴다.

    업체 저장소는 5일 뒤 비워지고, 업체가 주는 다운로드 주소는 서명된 임시
    URL 이라 몇 시간이면 죽는다(2026-08-18 실측 — `Signature`·보안 토큰이
    붙어 있다). 그 주소를 DB 에 넣으면 **곧 죽는 링크를 저장하는 것**이라,
    원본과 전사를 우리 쪽으로 옮기고 DB 에는 안 죽는 링크만 남긴다.
    """

    def test_writes_the_transcript_as_a_google_doc(self):
        # 폴더 둘(clinic·2026-08)을 각각 한 번씩 찾고, 마지막이 업로드다
        transport = FakeTransport(TOKEN_OK, FOLDER_FOUND, FOLDER_FOUND, UPLOADED)
        url = GoogleMeetAdapter(transport=transport).save_document(
            "clinic/2026-08/2026-08-19_1800_김하늘0001", "[1] 오답 원인은…"
        )
        upload = transport.calls[-1]
        self.assertIn("uploadType=multipart", upload["url"])
        body = upload["body"].decode()
        # 구글 문서로 변환시키되 **HTML 로** 올린다 — 제목·표가 살아야 읽힌다
        self.assertIn("application/vnd.google-apps.document", body)
        self.assertIn("text/html", body)
        self.assertIn("[1] 오답 원인은…", body)
        self.assertEqual(url, "https://docs.google.com/document/d/file-1/edit")

    def test_files_it_under_the_path_we_asked_for(self):
        # clinic → 2026-08 → 파일. 폴더는 있으면 쓰고 없으면 만든다.
        transport = FakeTransport(
            TOKEN_OK, FOLDER_NONE, FOLDER_MADE, FOLDER_NONE, FOLDER_MADE, UPLOADED
        )
        GoogleMeetAdapter(transport=transport).save_document(
            "clinic/2026-08/2026-08-19_1800_김하늘0001", "본문"
        )
        # 업로드 본문은 multipart 라 JSON 이 아니다 — 폴더 생성만 골라 읽는다
        folders = [
            json.loads(c["body"].decode())
            for c in transport.calls
            if c["method"] == "POST" and c["url"].endswith("drive/v3/files")
        ]
        self.assertEqual([f["name"] for f in folders], ["clinic", "2026-08"])
        self.assertIn("2026-08-19_1800_김하늘0001", transport.calls[-1]["body"].decode())

    def test_copies_the_recording_next_to_it(self):
        # 오디오 원본도 우리 것으로 만든다 — 업체 보관은 5일이다.
        transport = FakeTransport(TOKEN_OK, FOLDER_FOUND, FOLDER_FOUND, UPLOADED)
        GoogleMeetAdapter(transport=transport).save_bytes(
            "clinic/2026-08/2026-08-19_1800_김하늘0001.mp3", b"ID3audio", "audio/mpeg"
        )
        body = transport.calls[-1]["body"]
        self.assertIn(b"audio/mpeg", body)
        self.assertIn(b"ID3audio", body)

    def test_an_upload_failure_is_loud(self):
        # 조용히 넘어가면 DB 에는 곧 죽을 업체 링크만 남는다
        transport = FakeTransport(TOKEN_OK, FOLDER_FOUND, FOLDER_FOUND, (500, b"nope"))
        with self.assertRaises(TemporaryConferenceError):
            GoogleMeetAdapter(transport=transport).save_document("clinic/x/y", "본문")
