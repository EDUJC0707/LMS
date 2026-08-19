"""CLOVA Speech 전사 검증 — HTTP 는 주입한 전송으로 갈음한다.

이 엔진을 고른 이유는 두 가지고 그 둘이 그대로 테스트가 된다:
  ① **한국어 정확도** — 제3자 벤치마크(rtzr, AI-Hub 6종)에서 한국어 강연 CER
     7.08% 로 1위. Deepgram 21%, Gemini 16.6%, Google STT 11.5%
  ② **`boostings`** — 전사 전에 단어를 미리 넣어 그쪽으로 인식을 쏠리게 한다.
     LMS 는 그 클리닉이 어느 시험·단원인지 이미 아니까 단원 용어를 실어 보낼
     수 있다. 우리가 실제로 틀렸던 `대립유전자 → 대리비전자` 가 이걸로 푸는
     종류다(2026-08-12 실측). 기성 회의록 서비스는 이 자리가 없다.

**화자 이름은 우리가 붙이지 않는다.** 업체는 `1`, `2` 같은 라벨만 주고, 누가
조교인지는 회의 밖 정보다. 라벨을 그대로 남기고 판단은 사람이 한다.
"""
import json

from django.test import SimpleTestCase, override_settings

from .clova import transcribe
from .conferencing import PermanentConferenceError, TemporaryConferenceError

CREDENTIALS = {
    "CLOVA_SPEECH_INVOKE_URL": "https://clovaspeech-gw.ncloud.com/external/v1/1234/abcd",
    "CLOVA_SPEECH_SECRET": "cs-secret",
}

def recognized(*segments):
    return (
        200,
        json.dumps(
            {"text": " ".join(s["text"] for s in segments), "segments": list(segments)}
        ).encode(),
    )


def segment(text, speaker="1", start=0):
    return {"text": text, "speaker": {"label": speaker}, "start": start}


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


@override_settings(**CREDENTIALS)
class TranscribeTests(SimpleTestCase):
    def test_sends_the_audio_url_and_asks_for_korean(self):
        transport = FakeTransport(recognized(segment("안녕하세요")))
        transcribe("https://cdn.recall/audio.mp4", transport=transport)
        call = transport.calls[0]
        self.assertTrue(call["url"].endswith("/recognizer/url"))
        self.assertEqual(call["headers"]["X-CLOVASPEECH-API-KEY"], "cs-secret")
        sent = json.loads(call["body"])
        self.assertEqual(sent["url"], "https://cdn.recall/audio.mp4")
        self.assertEqual(sent["language"], "ko-KR")
        # 동기로 받는다 — 콜백 주소를 열면 공개 엔드포인트가 하나 더 생긴다
        self.assertEqual(sent["completion"], "sync")

    def test_asks_for_speakers_to_be_separated(self):
        # 조교와 학생이 갈리지 않으면 감독 근거가 안 된다
        transport = FakeTransport(recognized(segment("네")))
        transcribe("https://x/a", transport=transport)
        self.assertIn("diarization", json.loads(transport.calls[0]["body"]))

    def test_pushes_the_unit_vocabulary_in(self):
        transport = FakeTransport(recognized(segment("대립유전자")))
        transcribe("https://x/a", terms=("대립유전자", "유전자형"), transport=transport)
        sent = json.loads(transport.calls[0]["body"])
        self.assertEqual(
            sent["boostings"], [{"words": "대립유전자"}, {"words": "유전자형"}]
        )

    def test_omits_boostings_when_there_are_no_terms(self):
        # 빈 배열을 보내면 업체가 요청을 거절한다
        transport = FakeTransport(recognized(segment("네")))
        transcribe("https://x/a", transport=transport)
        self.assertNotIn("boostings", json.loads(transport.calls[0]["body"]))

    def test_returns_one_line_per_speaker_turn(self):
        # **시각을 붙인다.** 요약이 근거로 든 대목을 사람이 찾아 들으려면
        # 어디쯤인지 알아야 하고, 그게 없으면 40분을 처음부터 뒤져야 한다.
        transport = FakeTransport(
            recognized(
                segment("오답 원인이 뭐였죠?", speaker="2", start=7_640),
                segment("대립유전자를 반대로 봤어요.", speaker="1", start=73_200),
            )
        )
        text = transcribe("https://x/a", transport=transport)
        self.assertEqual(
            text,
            "00:00:07 [2] 오답 원인이 뭐였죠?\n00:01:13 [1] 대립유전자를 반대로 봤어요.",
        )

    def test_the_clock_rolls_into_hours(self):
        transport = FakeTransport(recognized(segment("네", start=3_725_000)))
        self.assertEqual(
            transcribe("https://x/a", transport=transport), "01:02:05 [1] 네"
        )

    def test_no_speech_is_not_a_failure(self):
        # 아무도 말하지 않은 회의 — 빈 문자열이지 예외가 아니다
        transport = FakeTransport(recognized())
        self.assertEqual(transcribe("https://x/a", transport=transport), "")

    def test_server_error_is_temporary(self):
        with self.assertRaises(TemporaryConferenceError):
            transcribe("https://x/a", transport=FakeTransport((503, b"busy")))

    def test_rejected_credentials_are_permanent(self):
        with self.assertRaises(PermanentConferenceError):
            transcribe("https://x/a", transport=FakeTransport((401, b"nope")))

    def test_missing_credentials_are_permanent(self):
        with override_settings(CLOVA_SPEECH_SECRET=""):
            with self.assertRaises(PermanentConferenceError):
                transcribe("https://x/a", transport=FakeTransport())

