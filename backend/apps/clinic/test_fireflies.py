"""Fireflies 어댑터 검증 — HTTP 는 주입한 전송으로 갈음한다.

실제 Fireflies 를 부르지 않는다. 고정하는 것은 어댑터의 일 두 가지다:
**무엇을 보내는가**(봇 투입 요청의 링크·제목·언어) 와 **응답을 어떻게 읽는가**
(요약을 찾았나 · 아직 없나 · 실패인가).

Fireflies 는 **미래 예약이 없다** — `addToLiveMeeting` 은 진행 중인 회의에만
봇을 넣는다. 그래서 "언제 부르는가"는 어댑터가 아니라 `supervision.dispatch` 의
일이고 거기서 따로 검증한다.

봇 투입 응답에는 전사 ID 가 없다. 나중에 **제목으로 되찾는다** — 그래서 제목에
`supervision.artifact_path` 를 그대로 싣는 것이 이 어댑터의 뼈대다.
"""
import json

from django.test import SimpleTestCase, override_settings

from .conferencing import PermanentConferenceError, TemporaryConferenceError
from .fireflies import GRAPHQL_ENDPOINT, FirefliesAdapter

TITLE = "clinic/2026-08/2026-08-12_1900_김하늘0001"

DISPATCH_OK = (200, json.dumps({"data": {"addToLiveMeeting": {"success": True}}}).encode())


def transcripts_response(*rows):
    return (200, json.dumps({"data": {"transcripts": list(rows)}}).encode())


def row(
    title=TITLE,
    overview="오답 원인을 끝까지 설명했다.",
    ident="01JQF",
    duration=58.0,
    live=False,
):
    return {
        "id": ident,
        "title": title,
        "duration": duration,
        "is_live": live,
        "transcript_url": f"https://app.fireflies.ai/view/{ident}",
        "summary": {"overview": overview},
    }


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


@override_settings(FIREFLIES_API_KEY="ff-key")
class DispatchTests(SimpleTestCase):
    """봇 투입 — 회의가 도는 동안 부른다."""

    def test_sends_the_meeting_link_and_files_it_under_our_title(self):
        transport = FakeTransport(DISPATCH_OK)
        FirefliesAdapter(transport=transport).start_supervision(
            "https://meet.google.com/a-b-c", title=TITLE, minutes=60
        )

        call = transport.calls[0]
        self.assertEqual(call["url"], GRAPHQL_ENDPOINT)
        self.assertEqual(call["headers"]["Authorization"], "Bearer ff-key")
        sent = json.loads(call["body"])
        self.assertIn("addToLiveMeeting", sent["query"])
        self.assertEqual(sent["variables"]["link"], "https://meet.google.com/a-b-c")
        # 제목이 곧 나중에 되찾을 열쇠다
        self.assertEqual(sent["variables"]["title"], TITLE)

    def test_asks_for_korean(self):
        transport = FakeTransport(DISPATCH_OK)
        FirefliesAdapter(transport=transport).start_supervision(
            "https://meet.google.com/a-b-c", title=TITLE, minutes=60
        )
        self.assertEqual(json.loads(transport.calls[0]["body"])["variables"]["language"], "ko")

    def test_clamps_the_duration_to_what_the_api_accepts(self):
        # 계약은 15~120 분이다. 슬롯이 그 밖이면 업체가 요청 전체를 거절한다.
        transport = FakeTransport(DISPATCH_OK, DISPATCH_OK)
        adapter = FirefliesAdapter(transport=transport)
        adapter.start_supervision("https://x/a", title=TITLE, minutes=5)
        adapter.start_supervision("https://x/a", title=TITLE, minutes=600)
        self.assertEqual(json.loads(transport.calls[0]["body"])["variables"]["minutes"], 15)
        self.assertEqual(json.loads(transport.calls[1]["body"])["variables"]["minutes"], 120)

    def test_server_error_is_temporary(self):
        transport = FakeTransport((503, b"upstream"))
        with self.assertRaises(TemporaryConferenceError):
            FirefliesAdapter(transport=transport).start_supervision(
                "https://x/a", title=TITLE, minutes=60
            )

    def test_rejected_credentials_are_permanent(self):
        transport = FakeTransport((401, b"unauthorized"))
        with self.assertRaises(PermanentConferenceError):
            FirefliesAdapter(transport=transport).start_supervision(
                "https://x/a", title=TITLE, minutes=60
            )

    def test_graphql_errors_are_permanent(self):
        # GraphQL 은 실패를 200 에 담아 보낸다 — 상태 코드만 보면 성공으로 읽힌다
        transport = FakeTransport((200, json.dumps({"errors": [{"message": "bad"}]}).encode()))
        with self.assertRaises(PermanentConferenceError):
            FirefliesAdapter(transport=transport).start_supervision(
                "https://x/a", title=TITLE, minutes=60
            )

    def test_missing_key_is_permanent(self):
        with override_settings(FIREFLIES_API_KEY=""):
            with self.assertRaises(PermanentConferenceError):
                FirefliesAdapter(transport=FakeTransport()).start_supervision(
                    "https://x/a", title=TITLE, minutes=60
                )


@override_settings(FIREFLIES_API_KEY="ff-key")
class FetchSupervisionTests(SimpleTestCase):
    """수집 — 우리가 붙인 제목으로 되찾는다."""

    def test_finds_the_transcript_by_our_title(self):
        transport = FakeTransport(transcripts_response(row()))
        found = FirefliesAdapter(transport=transport).fetch_supervision(
            "spaces/S1", file_as=TITLE
        )
        self.assertEqual(found.transcript_ref, "01JQF")
        self.assertEqual(found.transcript_url, "https://app.fireflies.ai/view/01JQF")
        self.assertIn("오답 원인", found.summary)

    def test_searches_by_the_last_segment_because_slashes_never_match(self):
        # 업체 필터는 정확 일치가 아니라 단어 검색이고 `/` 가 색인에 없다
        # (2026-08-12 실측: 'clinic/2026-08' → 0건, 'clinic' → 1건).
        # 전체 경로를 그대로 보내면 **영원히 0건**이라 수집이 조용히 멎는다.
        transport = FakeTransport(transcripts_response(row()))
        FirefliesAdapter(transport=transport).fetch_supervision("spaces/S1", file_as=TITLE)
        self.assertEqual(
            json.loads(transport.calls[0]["body"])["variables"]["title"],
            "2026-08-12_1900_김하늘0001",
        )

    def test_still_matches_the_whole_title_before_accepting(self):
        # 좁히는 것은 서버, 확정은 우리다 — 부분 일치가 남의 요약을 물어 오면 안 된다.
        transport = FakeTransport(
            transcripts_response(row(title="clinic/딴것/2026-08-12_1900_김하늘0001"))
        )
        self.assertIsNone(
            FirefliesAdapter(transport=transport).fetch_supervision("spaces/S1", file_as=TITLE)
        )

    def test_takes_the_longest_when_the_title_repeats(self):
        # 같은 제목이 둘 나올 수 있다 — 학생이 같은 날 같은 시각으로 취소하고
        # 다시 잡으면 `artifact_path` 가 글자 그대로 같다. 짧은 쪽은 봇이
        # 들어갔다 튕긴 자국이지 수업이 아니다(구글 경로와 같은 규칙).
        transport = FakeTransport(
            transcripts_response(
                row(ident="short", duration=0.4),
                row(ident="real", duration=57.2),
            )
        )
        found = FirefliesAdapter(transport=transport).fetch_supervision(
            "spaces/S1", file_as=TITLE
        )
        self.assertEqual(found.transcript_ref, "real")

    def test_ignores_a_transcript_still_being_recorded(self):
        # 아직 도는 회의는 요약이 없거나 반쪽이다 — 다음 차례에 온전한 걸 받는다.
        transport = FakeTransport(transcripts_response(row(live=True)))
        self.assertIsNone(
            FirefliesAdapter(transport=transport).fetch_supervision("spaces/S1", file_as=TITLE)
        )

    def test_returns_none_while_the_title_has_not_appeared(self):
        # 아직 처리 중이다 — 실패가 아니라 대기다(`conferencing` 계약)
        transport = FakeTransport(transcripts_response(row(title="남의 회의")))
        found = FirefliesAdapter(transport=transport).fetch_supervision(
            "spaces/S1", file_as=TITLE
        )
        self.assertIsNone(found)

    def test_keeps_the_link_when_the_summary_is_empty(self):
        # 요약을 못 받아도 사람이 열어 볼 링크는 남긴다
        transport = FakeTransport(transcripts_response(row(overview="")))
        found = FirefliesAdapter(transport=transport).fetch_supervision(
            "spaces/S1", file_as=TITLE
        )
        self.assertIsNone(found.summary)
        self.assertEqual(found.transcript_url, "https://app.fireflies.ai/view/01JQF")

    def test_without_a_title_there_is_nothing_to_match(self):
        # 관리자가 손으로 넣은 링크에는 우리 제목이 없다 — 물어볼 것이 없다
        transport = FakeTransport()
        self.assertIsNone(
            FirefliesAdapter(transport=transport).fetch_supervision("spaces/S1", file_as=None)
        )
        self.assertEqual(transport.calls, [])


class CreateSpaceTests(SimpleTestCase):
    """방은 여전히 구글이 만든다 — Fireflies 는 화상 업체가 아니다."""

    def test_delegates_to_the_conference_provider(self):
        class StubConference:
            def create_space(self):
                return "만들었다"

        adapter = FirefliesAdapter(conference=StubConference())
        self.assertEqual(adapter.create_space(), "만들었다")


class ToggleTests(SimpleTestCase):
    """설정 한 줄로 갈아 끼운다 — 구글 코드는 남는다(2026-08-12 지시)."""

    def test_this_is_the_default_now(self):
        # 2026-08-12 전면 교체. 실제 클리닉으로 전사·화자분리·한국어 요약까지
        # 확인하고 기본값을 옮겼다. 구글 어댑터는 지우지 않는다 — 설정 한 줄로
        # 돌아갈 수 있어야 교체가 되돌릴 수 있는 결정으로 남는다.
        from django.conf import settings

        self.assertEqual(
            settings.CLINIC_CONFERENCE_BACKEND, "apps.clinic.fireflies.FirefliesAdapter"
        )

    @override_settings(CLINIC_CONFERENCE_BACKEND="apps.clinic.fireflies.FirefliesAdapter")
    def test_the_configured_path_resolves(self):
        # `.env` 가 문자열로 가리키는 자리다. 클래스를 옮기거나 이름을 바꾸면
        # 배정이 조용히 수동 링크 경로로 돌아간다 — 그때 여기가 먼저 깨진다.
        from .conferencing import get_adapter

        self.assertIsInstance(get_adapter(), FirefliesAdapter)
