"""구글 미트 갱신 토큰 발급 — 사람이 한 번 돌리는 명령.

## 왜 이 명령이 필요한가

Meet REST API 는 **사용자 인증만** 받는다(google_meet.py 머리말). 서버가 혼자
얻을 수 있는 자격증명이 없고, 계정 주인이 브라우저에서 한 번 동의해야 갱신
토큰이 나온다. 그 한 번을 사람이 손으로 하려면 URL 조립·리다이렉트 수신·코드
교환을 다 해야 해서 틀리기 쉽다 — 그래서 명령으로 만든다.

## 쓰는 순서

1. Google Cloud 콘솔에서 프로젝트를 만들고 **Google Meet API 를 사용 설정**한다.
2. OAuth 동의 화면을 만든다. 스코프는 `meetings.space.created` 하나다.

   ⚠ **여기서 한 번 틀리면 일주일마다 조용히 끊긴다.** 게시 상태가
   `테스트` 인 외부 앱의 갱신 토큰은 **7일 뒤 만료**된다 — 배정이 갑자기
   400 을 뱉기 시작하고 원인은 화면 어디에도 안 적힌다. 둘 중 하나로 간다:
   - 계정이 **Workspace** 다 → 사용자 유형을 **내부(Internal)** 로. 만료도
     검증도 없다.
   - 계정이 **개인(@gmail.com)** 이다 → 외부로 만들되 **게시 상태를
     `프로덕션`으로 올린다**. 미검증 앱 경고가 뜨지만 동의는 우리 계정 하나가
     한 번 하고 끝이라 상관없다. `테스트` 로 두지 말 것.
3. 사용자 인증 정보 > OAuth 클라이언트 ID > **데스크톱 앱**을 만든다.
   (웹 애플리케이션으로 만들면 승인된 리디렉션 URI 에 아래 주소를 넣어야 한다.)
4. 받은 값을 넣고 실행한다:

       GOOGLE_MEET_CLIENT_ID=... GOOGLE_MEET_CLIENT_SECRET=... \\
         .venv/bin/python manage.py meet_authorize

5. 출력된 주소를 브라우저에서 열고 **미트를 쓸 그 계정**으로 승인한다.
6. 마지막에 찍히는 갱신 토큰을 `GOOGLE_MEET_REFRESH_TOKEN` 으로 넣는다
   (운영은 `fly secrets set`).

## 리다이렉트를 왜 로컬 서버로 받나

구글은 2022 년에 복붙 방식(`urn:ietf:wg:oauth:2.0:oob`)을 없앴다. 남은 길은
**루프백 리디렉션**뿐이라 이 명령이 잠깐 127.0.0.1 에 서버를 띄워 코드를 받는다.
서버는 코드를 한 번 받으면 바로 닫힌다.
"""
import http.server
import threading
import urllib.parse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.clinic.conferencing import ConferenceError
from apps.clinic.google_meet import build_consent_url, exchange_code

DEFAULT_PORT = 8765


class _CodeReceiver(http.server.BaseHTTPRequestHandler):
    """리디렉션 한 건만 받고 끝. 받은 코드는 서버 객체에 얹는다."""

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler 규약)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        self.server.auth_code = (query.get("code") or [None])[0]
        self.server.auth_error = (query.get("error") or [None])[0]
        body = (
            "승인됐습니다. 터미널로 돌아가세요."
            if self.server.auth_code
            else f"승인되지 않았습니다: {self.server.auth_error}"
        )
        payload = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        """접근 로그를 표준 오류로 흘리지 않는다 — 사람이 볼 것은 토큰뿐이다."""


class Command(BaseCommand):
    help = "구글 미트 갱신 토큰을 발급받는다(1회성 동의)."

    def add_arguments(self, parser):
        parser.add_argument("--port", type=int, default=DEFAULT_PORT)

    def handle(self, *args, **options):
        client_id = (getattr(settings, "GOOGLE_MEET_CLIENT_ID", "") or "").strip()
        client_secret = (getattr(settings, "GOOGLE_MEET_CLIENT_SECRET", "") or "").strip()
        # 포트를 잡기 **전에** 막는다 — 브라우저를 열어 둔 뒤에 알려주면 늦다.
        if not client_id:
            raise CommandError("GOOGLE_MEET_CLIENT_ID 가 없습니다.")
        if not client_secret:
            raise CommandError("GOOGLE_MEET_CLIENT_SECRET 가 없습니다.")

        port = options["port"]
        redirect_uri = f"http://localhost:{port}/"
        code = self._await_code(port, redirect_uri, client_id)
        try:
            refresh_token = exchange_code(client_id, client_secret, code, redirect_uri)
        except ConferenceError as error:
            raise CommandError(str(error)) from error

        self.stdout.write("")
        self.stdout.write("GOOGLE_MEET_REFRESH_TOKEN=" + refresh_token)

    def _await_code(self, port, redirect_uri, client_id):
        try:
            server = http.server.HTTPServer(("127.0.0.1", port), _CodeReceiver)
        except OSError as error:
            raise CommandError(f"{port} 포트를 열지 못했습니다: {error}") from error
        server.auth_code = None
        server.auth_error = None
        self.stdout.write("아래 주소를 브라우저에서 열고 미트를 쓸 계정으로 승인하세요:")
        self.stdout.write("")
        self.stdout.write(build_consent_url(client_id, redirect_uri))
        self.stdout.write("")
        self.stdout.write("승인을 기다리는 중…")
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        thread.join()
        server.server_close()
        if not server.auth_code:
            raise CommandError(f"인가 코드를 받지 못했습니다: {server.auth_error or '취소됨'}")
        return server.auth_code
