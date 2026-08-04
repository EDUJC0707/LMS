"""`manage.py meet_authorize` — 자격증명이 없으면 브라우저를 열기 전에 멈춘다.

동의 URL 조립·코드 교환은 `test_google_meet.ConsentFlowTests` 가 잡는다. 여기서
고정하는 것은 **로컬 서버를 띄우기 전에** 막히는가 하나다 — 포트를 잡고 나서
"클라이언트 ID 가 없다"를 알려주면 사람은 브라우저를 이미 열어 둔 뒤다.
"""
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from apps.clinic.management.commands.meet_authorize import redirect_uri_for


class RedirectUriTests(SimpleTestCase):
    def test_uses_the_loopback_address_not_the_name(self):
        # `localhost` 는 맥에서 ::1 로도 풀리는데 코드 수신 서버는 IPv4 에만
        # 붙는다 — 브라우저가 ::1 로 먼저 가면 "연결할 수 없음"이 뜨고,
        # 그때는 동의를 이미 끝낸 뒤라 코드가 통째로 날아간다.
        self.assertEqual(redirect_uri_for(8765), "http://127.0.0.1:8765/")


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
