"""재생 제한 규칙을 만들고 id 를 알려준다 (Mux Playback Restrictions).

    manage.py mux_restriction --domain hjcedu.com --domain localhost
    manage.py mux_restriction --list

## 왜 필요한가 — 만료만으로는 다운로드를 못 막는다

토큰이 살아 있는 6시간 동안에는 URL 만 복사하면 스트림을 통째로 받아갈 수 있다.
50분 강의는 1분이면 내려받힌다. 제한 규칙을 걸면 Mux 가 `Referer` 와
`User-Agent` 를 함께 보고, **referer 없는 요청을 기본으로 거부**한다 —
curl·yt-dlp 처럼 브라우저가 아닌 도구가 여기서 막힌다.

**벽은 아니다.** 두 헤더 다 위조할 수 있다. 복사한 URL 을 도구에 그대로
붙여넣는 경로를 닫는 것이고, 진짜 방어는 DRM 이다(런칭 직전 — decisions.md §3).

## 왜 커맨드인가

규칙은 **환경(environment)당 한 번** 만들고 그 id 를 `.env` 에 넣어 계속 쓴다.
화면에서 만들 일이 없고, 도메인이 바뀌는 일도 드물다. 대시보드에서 손으로
만들면 어떤 도메인을 넣었는지 저장소에 남지 않는다 — 커맨드로 두면 인자가 곧 기록이다.
"""
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.videos import mux


class Command(BaseCommand):
    help = "Mux 재생 제한 규칙 생성·조회 (Referer·User-Agent)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--domain",
            action="append",
            default=[],
            help="허용 도메인(여러 번 지정 가능). `*.example.com` 형태도 된다",
        )
        parser.add_argument(
            "--list", action="store_true", help="이미 만든 규칙을 보여준다"
        )
        parser.add_argument(
            "--allow-no-referrer",
            action="store_true",
            help="referer 없는 요청도 허용한다 — **이 기능의 요점을 없앤다.** "
            "네이티브 앱이 붙을 때만 쓴다",
        )

    def handle(self, *args, **options):
        if not mux.api_configured():
            raise CommandError(
                "MUX_TOKEN_ID·MUX_TOKEN_SECRET 이 없습니다. backend/.env 에 넣으세요."
            )

        if options["list"]:
            rows = mux._api("GET", "/playback-restrictions")
            if not rows:
                self.stdout.write("규칙 없음")
                return
            for row in rows:
                referrer = row.get("referrer") or {}
                self.stdout.write(
                    f"  {row['id']}  도메인 {referrer.get('allowed_domains') or []} "
                    f"· referer 없음 허용 {referrer.get('allow_no_referrer')}"
                )
            current = (getattr(settings, "MUX_PLAYBACK_RESTRICTION_ID", "") or "").strip()
            self.stdout.write(f"\n지금 쓰는 규칙: {current or '(없음 — 제한 없이 서명한다)'}")
            return

        domains = options["domain"]
        if not domains:
            raise CommandError(
                "--domain 을 하나 이상 주세요. 예: --domain hjcedu.com --domain localhost"
            )
        payload = {
            "referrer": {
                "allowed_domains": domains,
                # 기본은 거부다 — 이걸 켜면 curl·yt-dlp 가 다시 통과한다.
                "allow_no_referrer": options["allow_no_referrer"],
            },
            "user_agent": {
                # 브라우저가 아닌 클라이언트를 거른다. 위조는 가능하다.
                "allow_no_user_agent": False,
                "allow_high_risk_user_agent": False,
            },
        }
        data = mux._api("POST", "/playback-restrictions", payload)
        self.stdout.write(self.style.SUCCESS("규칙 생성"))
        self.stdout.write(json.dumps(data, ensure_ascii=False, indent=1))
        self.stdout.write(
            f"\nbackend/.env 에 넣으세요:\n  MUX_PLAYBACK_RESTRICTION_ID={data['id']}"
        )
