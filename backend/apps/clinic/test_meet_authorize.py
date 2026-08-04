"""`manage.py meet_authorize` — 자격증명이 없으면 브라우저를 열기 전에 멈춘다.

동의 URL 조립·코드 교환은 `test_google_meet.ConsentFlowTests` 가 잡는다. 여기서
고정하는 것은 **로컬 서버를 띄우기 전에** 막히는가 하나다 — 포트를 잡고 나서
"클라이언트 ID 가 없다"를 알려주면 사람은 브라우저를 이미 열어 둔 뒤다.
"""
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings


class MeetAuthorizeGuardTests(SimpleTestCase):
    @override_settings(GOOGLE_MEET_CLIENT_ID="", GOOGLE_MEET_CLIENT_SECRET="")
    def test_without_client_credentials_it_stops(self):
        with self.assertRaises(CommandError) as caught:
            call_command("meet_authorize", stdout=StringIO())
        self.assertIn("GOOGLE_MEET_CLIENT_ID", str(caught.exception))

    @override_settings(GOOGLE_MEET_CLIENT_ID="cid", GOOGLE_MEET_CLIENT_SECRET="")
    def test_client_secret_is_also_required(self):
        with self.assertRaises(CommandError) as caught:
            call_command("meet_authorize", stdout=StringIO())
        self.assertIn("GOOGLE_MEET_CLIENT_SECRET", str(caught.exception))
