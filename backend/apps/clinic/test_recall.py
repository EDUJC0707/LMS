"""Recall 어댑터 검증 — HTTP 는 주입한 전송으로 갈음한다.

이 업체를 고른 이유가 셋이고 그 셋이 그대로 테스트가 된다:
  ① **예약 참가**(`join_at`) — 배정할 때 걸어 두면 우리 쪽에 도는 것이 없다
  ② **우리 이름표**(`metadata`) — 나중에 그 봇을 되찾을 때 컬럼이 필요 없다
  ③ **오디오 원본** — 전사는 우리가 고른 엔진(CLOVA)이 한다

봇을 조직 계정으로 로그인시키는 설정은 **업체 대시보드에 있다**(요청 필드가
아니다). 그래서 코드에는 자격증명이 없고 여기서 검증할 것도 없다.
"""
import datetime
import json

from django.test import SimpleTestCase, override_settings

from .conferencing import PermanentConferenceError, TemporaryConferenceError
from .recall import RecallAdapter

KEY = "clinic13"
TITLE = "clinic/2026-08/2026-08-13_1700_김하늘0001"
STARTS = datetime.datetime(2026, 8, 13, 17, 0, tzinfo=datetime.UTC)

CREATED = (201, json.dumps({"id": "bot-1"}).encode())


def listed(*bots):
    return (200, json.dumps({"results": list(bots)}).encode())


def bot(ident="bot-1", state="done", audio="https://cdn.recall/audio.mp4"):
    return {
        "id": ident,
        "status_changes": [{"code": "joining_call"}, {"code": state}],
        "media_shortcuts": {"audio_mixed": {"data": {"download_url": audio}}},
    }


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, body, headers, timeout):
        self.calls.append({"method": method, "url": url, "body": body, "headers": headers})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@override_settings(RECALL_API_KEY="rc-key", RECALL_REGION="ap-northeast-1")
class ScheduleTests(SimpleTestCase):
    def test_books_the_bot_for_the_clinic_start(self):
        transport = FakeTransport(CREATED)
        RecallAdapter(transport=transport).schedule_supervision(
            "https://meet.google.com/a-b-c", key=KEY, title=TITLE, starts_at=STARTS, minutes=60
        )
        call = transport.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertIn("ap-northeast-1.recall.ai", call["url"])
        self.assertEqual(call["headers"]["Authorization"], "Token rc-key")
        sent = json.loads(call["body"])
        self.assertEqual(sent["meeting_url"], "https://meet.google.com/a-b-c")
        # 예약이 이 업체를 고른 이유다 — 시각을 업체가 지킨다
        self.assertEqual(sent["join_at"], "2026-08-13T17:00:00+00:00")
        # 우리 이름표 — 되찾을 때 쓴다(그래서 컬럼이 필요 없다)
        self.assertEqual(sent["metadata"]["clinic"], KEY)

    def test_asks_for_audio_not_their_transcript(self):
        # 전사는 CLOVA 가 한다. 업체 전사를 켜면 돈만 더 나가고 한국어는 더 나쁘다.
        transport = FakeTransport(CREATED)
        RecallAdapter(transport=transport).schedule_supervision(
            "https://x/a", key=KEY, title=TITLE, starts_at=STARTS, minutes=60
        )
        sent = json.loads(transport.calls[0]["body"])
        self.assertIn("audio_mixed", json.dumps(sent["recording_config"]))
        self.assertNotIn("transcript", json.dumps(sent["recording_config"]))

    def test_server_error_is_temporary(self):
        with self.assertRaises(TemporaryConferenceError):
            RecallAdapter(transport=FakeTransport((503, b"nope"))).schedule_supervision(
                "https://x/a", key=KEY, title=TITLE, starts_at=STARTS, minutes=60
            )

    def test_rejected_key_is_permanent(self):
        with self.assertRaises(PermanentConferenceError):
            RecallAdapter(transport=FakeTransport((401, b"nope"))).schedule_supervision(
                "https://x/a", key=KEY, title=TITLE, starts_at=STARTS, minutes=60
            )

    def test_missing_key_is_permanent(self):
        with override_settings(RECALL_API_KEY=""):
            with self.assertRaises(PermanentConferenceError):
                RecallAdapter(transport=FakeTransport()).schedule_supervision(
                    "https://x/a", key=KEY, title=TITLE, starts_at=STARTS, minutes=60
                )


@override_settings(RECALL_API_KEY="rc-key", RECALL_REGION="ap-northeast-1")
class CancelTests(SimpleTestCase):
    def test_finds_our_bot_by_name_and_removes_it(self):
        transport = FakeTransport(listed(bot()), (204, b""))
        RecallAdapter(transport=transport).cancel_supervision(KEY)
        self.assertIn("metadata__clinic=clinic13", transport.calls[0]["url"])
        self.assertEqual(transport.calls[1]["method"], "DELETE")
        self.assertIn("/bot/bot-1", transport.calls[1]["url"])

    def test_no_booking_is_not_a_failure(self):
        # 취소를 두 번 눌러도, 예약이 애초에 없어도 조용히 끝나야 한다 —
        # 여기서 터지면 학생의 취소가 실패한다.
        transport = FakeTransport(listed())
        RecallAdapter(transport=transport).cancel_supervision(KEY)
        self.assertEqual(len(transport.calls), 1)


@override_settings(RECALL_API_KEY="rc-key", RECALL_REGION="ap-northeast-1")
class FetchTests(SimpleTestCase):
    def stub_transcriber(self, text="[조교] 오답 원인은 여기다."):
        def transcribe(url, *, terms=()):
            self.asked = (url, terms)
            return text

        return transcribe

    def test_waits_while_the_bot_is_still_in_the_call(self):
        transport = FakeTransport(listed(bot(state="in_call_recording")))
        found = RecallAdapter(transport=transport).fetch_supervision(
            "spaces/S1", file_as=TITLE, key=KEY
        )
        self.assertIsNone(found)

    def test_waits_when_no_bot_was_ever_booked(self):
        transport = FakeTransport(listed())
        self.assertIsNone(
            RecallAdapter(transport=transport).fetch_supervision(
                "spaces/S1", file_as=TITLE, key=KEY
            )
        )

    def test_sends_the_audio_to_our_own_engine(self):
        transport = FakeTransport(listed(bot()))
        adapter = RecallAdapter(transport=transport, transcriber=self.stub_transcriber())
        found = adapter.fetch_supervision("spaces/S1", file_as=TITLE, key=KEY)
        self.assertEqual(self.asked[0], "https://cdn.recall/audio.mp4")
        self.assertEqual(found.transcript_ref, "bot-1")
        self.assertIn("오답 원인", found.summary)

    def test_a_dead_bot_does_not_wait_forever(self):
        # `fatal` 은 다시 물어도 안 생긴다 — 대기가 아니라 실패로 끝내야
        # 30일 동안 같은 건을 계속 묻지 않는다.
        transport = FakeTransport(listed(bot(state="fatal")))
        with self.assertRaises(PermanentConferenceError):
            RecallAdapter(transport=transport).fetch_supervision(
                "spaces/S1", file_as=TITLE, key=KEY
            )
