"""채널톡 통화 로그 어댑터 — 번호 정규화·시도 매칭 (PRD 9.2, 8-18).

여기서 지키는 것은 둘이다:
- **업체 형식을 도메인으로 들이지 않는다** — E.164 를 우리 저장 형식으로 되돌린다
- **한 번호에 카드가 여럿일 수 있다**(ParentStudent M:N) — 그래서 매칭은
  후보를 주는 데까지고, 확정은 조교가 화면에서 한다(decisions.md §5 와 같은 패턴)
"""
import datetime
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from . import channeltalk


class PhoneNormalizeTests(SimpleTestCase):
    def test_e164_becomes_our_stored_form(self):
        self.assertEqual(channeltalk.normalize("+821097649812"), "01097649812")

    def test_hyphens_and_spaces_are_stripped(self):
        self.assertEqual(channeltalk.normalize("010-9764-9812"), "01097649812")

    def test_landline_e164_keeps_its_leading_zero(self):
        self.assertEqual(channeltalk.normalize("+827047685420"), "07047685420")

    def test_unknown_shape_is_returned_digits_only(self):
        # 못 알아보는 것을 버리면 매칭이 조용히 실패한다 — 숫자만 남겨 넘긴다.
        self.assertEqual(channeltalk.normalize("+1 415 555 0100"), "14155550100")

    def test_empty_is_empty(self):
        self.assertEqual(channeltalk.normalize(None), "")


FAKE_LOG = [
    {
        "direction": "outbound",
        "from": "+827047685420",
        "to": "+821097649812",
        "createdAt": "2026-08-12T04:31:49Z",
        "engagedAt": "2026-08-12T04:31:59.212Z",
        "userChatId": "6a7bf735aaba03d98dde",
    },
    {
        "direction": "outbound",
        "from": "+827047685420",
        "to": "+821011112222",
        "createdAt": "2026-08-12T05:00:00Z",
        "missedReason": "ringTimeOver",
    },
    {
        "direction": "inbound",
        "from": "+821097649812",
        "to": "+827047685420",
        "createdAt": "2026-08-12T06:00:00Z",
    },
]


@override_settings(CHANNELTALK_ACCESS_KEY="k", CHANNELTALK_ACCESS_SECRET="s")
class RecentCallsTests(SimpleTestCase):
    def calls_for(self, phone):
        with patch.object(channeltalk, "fetch_calls", return_value=FAKE_LOG):
            return channeltalk.recent_calls(phone, since=datetime.timedelta(hours=6))

    def test_finds_the_outbound_call_to_that_number(self):
        found = self.calls_for("010-9764-9812")

        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["connected"])
        self.assertEqual(found[0]["user_chat_id"], "6a7bf735aaba03d98dde")

    def test_unanswered_call_is_reported_as_not_connected(self):
        found = self.calls_for("01011112222")

        self.assertEqual(len(found), 1)
        self.assertFalse(found[0]["connected"])
        self.assertEqual(found[0]["missed_reason"], "ringTimeOver")

    def test_inbound_calls_are_ignored(self):
        # 학부모가 우리한테 건 것은 우리의 시도가 아니다 — 3회에 섞이면 안 된다.
        found = self.calls_for("01097649812")

        self.assertEqual([c["direction"] for c in found], ["outbound"])

    def test_no_credentials_means_no_calls_not_an_error(self):
        # 키가 없어도 화면은 떠야 한다 — 매칭만 비는 것이 맞다(안전 기본값).
        with override_settings(CHANNELTALK_ACCESS_KEY="", CHANNELTALK_ACCESS_SECRET=""):
            self.assertEqual(channeltalk.recent_calls("01097649812"), [])
