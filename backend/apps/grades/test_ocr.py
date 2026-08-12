"""손글씨 OCR 계약 — 못 믿으면 사람에게 넘긴다 (apps/grades/ocr.py).

네트워크는 전부 갈아 끼운다. 여기서 고정하는 것은 **언제 None 이냐**다:
키 없음 · 호출 실패 · 신뢰도 미달 · 지면이 낼 수 없는 값. 넷 다 "그 장은
보류"로 수렴해야 한다(닫힘 기본값 — key_considerations §5).

문턱 0.90 의 근거는 실측이다(ocr.py 모듈 docstring 표).
"""
from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings

from . import ocr

PNG = b"\x89PNG\r\n\x1a\n"


def upstage(text, confidence):
    response = mock.Mock()
    response.json.return_value = {"text": text, "confidence": confidence}
    response.raise_for_status.return_value = None
    return response


@override_settings(UPSTAGE_API_KEY="test-key", OMR_OCR_MIN_CONFIDENCE=0.90)
class ReadScoreTests(SimpleTestCase):
    def read(self, response):
        with mock.patch.object(ocr.requests, "post", return_value=response) as post:
            return ocr.read_score(PNG), post

    def test_reads_a_confident_number(self):
        score, post = self.read(upstage("46", 0.99))

        self.assertEqual(score, 46)
        self.assertEqual(post.call_args.kwargs["data"], {"model": "ocr"})

    def test_strips_whatever_is_not_a_digit(self):
        """`46점` 처럼 단위가 붙어 와도 숫자만 남긴다."""
        self.assertEqual(self.read(upstage("46점", 0.97))[0], 46)

    def test_low_confidence_goes_to_a_person(self):
        """실측에서 틀린 두 건의 신뢰도가 0.617·0.890 이었다 — 그 아래는 안 쓴다."""
        self.assertIsNone(self.read(upstage("41", 0.617))[0])
        self.assertIsNone(self.read(upstage("47", 0.89))[0])

    def test_a_value_the_paper_cannot_express_is_refused(self):
        """10의 자리가 1~5 라 59 가 최대다. 그 밖이면 칸 밖 글자를 문 것이다."""
        self.assertIsNone(self.read(upstage("460", 0.99))[0])
        self.assertIsNone(self.read(upstage("87", 0.99))[0])

    def test_empty_text_is_not_a_zero(self):
        """글씨가 없는 것과 0점은 다르다 — 실물 34장 중 12장이 백지였다."""
        self.assertIsNone(self.read(upstage("", 0.99))[0])

    def test_a_dead_vendor_does_not_kill_the_batch(self):
        with mock.patch.object(
            ocr.requests, "post", side_effect=requests.Timeout("느림")
        ):
            self.assertIsNone(ocr.read_score(PNG))


class NoKeyTests(SimpleTestCase):
    @override_settings(UPSTAGE_API_KEY="")
    def test_without_a_key_nothing_leaves_the_building(self):
        """키가 없으면 **부르지도 않는다** — OCR 없이도 시스템은 그대로 돈다."""
        with mock.patch.object(ocr.requests, "post") as post:
            self.assertIsNone(ocr.read_score(PNG))

        post.assert_not_called()
