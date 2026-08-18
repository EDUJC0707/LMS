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


def bot(ident="bot-1", state="done", audio="https://cdn.recall/audio.mp3", video=None):
    # **미디어는 봇이 아니라 `recordings[]` 안에 있다**(2026-08-18 실측 —
    # 봇 최상위에는 media_shortcuts 자체가 없다).
    shortcuts = {}
    if audio:
        shortcuts["audio_mixed"] = {"data": {"download_url": audio}}
    if video:
        shortcuts["video_mixed"] = {"data": {"download_url": video}}
    return {
        "id": ident,
        "status_changes": [{"code": "joining_call"}, {"code": state}],
        "recordings": [{"media_shortcuts": shortcuts}],
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
        # 예약이 이 업체를 고른 이유다 — 시각을 업체가 지킨다.
        # **시작보다 일찍 들어간다**: 정각에 맞추면 조교·학생이 먼저 들어와
        # 인사하는 동안 봇이 없어서 그 앞부분이 안 남는다. 빈 방에 혼자
        # 기다려도 업체 기본값(noone_joined_timeout 1200초)이 훨씬 길어 안전하다.
        self.assertEqual(sent["join_at"], "2026-08-13T16:50:00+00:00")
        # 우리 이름표 — 되찾을 때 쓴다(그래서 컬럼이 필요 없다)
        self.assertEqual(sent["metadata"]["clinic"], KEY)

    def test_the_bot_shows_a_name_a_student_can_read(self):
        # 봇은 **참가자 목록에 뜬다**. 되찾기는 metadata 로 하므로 이름은 자유고,
        # 내부 경로를 그대로 쓰면 학생 화면에 자기 원번이 붙은 문자열이 앉아
        # 있게 된다(2026-08-18 실측: "clinic/2026-08/2026-08-18_1720_김하늘0001
        # is in this call").
        transport = FakeTransport(CREATED)
        RecallAdapter(transport=transport).schedule_supervision(
            "https://x/a", key=KEY, title=TITLE, starts_at=STARTS, minutes=60
        )
        name = json.loads(transport.calls[0]["body"])["bot_name"]
        self.assertNotIn("김하늘0001", name)
        self.assertNotIn("clinic/", name)

    def test_asks_for_audio_and_turns_video_off(self):
        # 키 이름이 틀리면 업체가 **조용히 무시하고 기본값(영상)으로 녹음한다**
        # (2026-08-18 실측: `audio_mixed` 로 보냈더니 video_mixed_mp4 가 왔다).
        # 영상은 우리가 안 쓰는데 용량만 크다.
        transport = FakeTransport(CREATED)
        RecallAdapter(transport=transport).schedule_supervision(
            "https://x/a", key=KEY, title=TITLE, starts_at=STARTS, minutes=60
        )
        config = json.loads(transport.calls[0]["body"])["recording_config"]
        self.assertEqual(config["audio_mixed_mp3"], {})
        self.assertIsNone(config["video_mixed_mp4"])
        # 업체 기본값은 **영구 보관**이다. 원본은 회의가 끝나면 우리 드라이브로
        # 옮기므로 저쪽은 옮기기가 몇 번 실패해도 될 여유만 있으면 된다.
        # 7일까지가 업체 무료 보관 구간이라 거기서 끝낸다.
        self.assertEqual(config["retention"], {"type": "timed", "hours": 24 * 7})
        # 전사는 CLOVA 가 한다 — 업체 전사를 켜면 돈만 더 나가고 한국어는 더 나쁘다
        self.assertNotIn("transcript", json.dumps(config))

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
        self.assertEqual(self.asked[0], "https://cdn.recall/audio.mp3")
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

    def test_falls_back_to_the_video_when_only_that_exists(self):
        # 옛 예약은 영상으로 녹음됐다(설정 키를 틀렸던 기간). 전사 엔진은
        # 영상에서도 소리를 읽으므로 버리지 않는다.
        transport = FakeTransport(listed(bot(audio=None, video="https://cdn.recall/v.mp4")))
        adapter = RecallAdapter(transport=transport, transcriber=self.stub_transcriber())
        adapter.fetch_supervision("spaces/S1", file_as=TITLE, key=KEY)
        self.assertEqual(self.asked[0], "https://cdn.recall/v.mp4")

    def test_waits_when_the_media_is_not_ready_yet(self):
        transport = FakeTransport(listed(bot(audio=None)))
        self.assertIsNone(
            RecallAdapter(transport=transport).fetch_supervision(
                "spaces/S1", file_as=TITLE, key=KEY
            )
        )
