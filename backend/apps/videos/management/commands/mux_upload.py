"""Mux 로 영상 하나를 올린다 — 화면 붙이기 전의 임시 경로.

    manage.py mux_upload <파일경로> --title "1주차 1강" --week 181

관리 화면의 업로드 UI 는 아직 만들지 않는다(2026-08-04 사용자 지시). 그 전까지
**등급·해상도 설정을 틀리지 않고** 올릴 수 있는 자리가 필요해서 커맨드로 둔다.

## 이 커맨드가 존재하는 진짜 이유 — 기본값이 사람을 속인다

Mux 는 **`max_resolution_tier` 를 안 주면 4K 원본도 1080p 로 자른다**
("예상치 못한 요금을 피하도록 4K 를 자동 처리하지 않는다" — 공식 문서).
실제로 대표가 4K 를 올렸는데 1080p 사다리만 나왔고, 등급을 premium 으로 올려도
그대로였다(2026-08-04). **등급과 무관한 별개 설정이기 때문이다.**

대시보드에서 손으로 올리면 이 값을 매번 기억해야 하고, 한 번 틀리면 **재인코딩**
말고는 되돌릴 방법이 없다. 그래서 기본값을 코드에 박는다.

## 왜 `premium` 인가 (2026-08-04 — 처음엔 plus 로 정했다가 실측으로 뒤집었다)

`basic` 은 **DRM 이 안 된다**(필수 요건). 남은 건 plus vs premium 인데,
1.5배가 사는 것은 "영화용 튜닝" 이 아니라 **렌디션 한 칸과 사다리 바닥**이다.

| | plus | premium |
|---|---|---|
| 1080p | 6.59 Mbps **1칸** | 8.04 + 10.71 Mbps **2칸** |
| 사다리 바닥 | 270p / 480p | **360p / 540p** |

판서에 이게 결정적인 이유:
- **가는 분필선은 고주파라 양자화에서 가장 먼저 버려진다.** H.264 출력뿐이라
  코덱으로 벌 방법이 없고 레버는 비트레이트 하나다.
- **plus 는 회선이 나빠지면 270p 까지 떨어진다.** 거기서 판서는 소멸한다 —
  그 시간은 수업이 아니라 소리만 남는다. premium 은 270p 칸이 아예 없다.

**반직관적인 것**: premium 의 이득은 1080p 이하에 몰려 있고 **4K 꼭대기에서는
오히려 plus 보다 낮았다**(2160p plus 27.56 vs premium 26.18 Mbps). 22~27 Mbps 를
지속적으로 버티는 학생은 거의 없어 결국 1080p 칸에 앉는다 — 즉 "글씨가 안 보이면
4K로" 는 틀린 길이고, 같은 돈이면 4K plus 보다 1080p premium 이 낫다.

차액은 연 약 ₩304,000(총액의 10%. DRM 이 72%). 반면 등급은 **자산 생성 시 확정**이라
바꾸려면 전량 재인코딩 + 새 playback ID + DB·서명·워터마크 재배선이다.
되돌리기가 비싸고 앞으로 내는 값이 싸면 비싼 쪽으로 간다.

## 왜 `signed` 인가

재생 권한을 "링크를 아는가"에서 "우리 서버가 내줬는가"로 옮긴다. 서버가 서명한
JWT 없이는 403 이다(apps/videos/mux.py). `public` 으로 올리면 그 방어가 통째로 빠지고,
정책은 **자산 생성 시점에 정해져** 나중에 바꾸려면 Playback ID 를 새로 만들어야 한다.
"""
import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.curriculum.models import CourseWeek
from apps.videos.models import Video

API = "https://api.mux.com/video/v1"

#: 업로드 기본값 — 틀리면 재인코딩뿐이라 코드에 박는다(머리말 참조).
VIDEO_QUALITY = "premium"
MAX_RESOLUTION = "2160p"
PLAYBACK_POLICY = "signed"

#: 자산 처리 대기 — 4K 1시간은 인코딩에 수 분 걸린다.
POLL_INTERVAL = 5
POLL_LIMIT = 240  # 20분


def _auth_header():
    token_id = (getattr(settings, "MUX_TOKEN_ID", "") or "").strip()
    secret = (getattr(settings, "MUX_TOKEN_SECRET", "") or "").strip()
    if not token_id or not secret:
        raise CommandError(
            "MUX_TOKEN_ID·MUX_TOKEN_SECRET 이 없습니다. backend/.env 에 넣으세요.\n"
            "  대시보드 Settings → Access Tokens (서명 키와 다른 값입니다)."
        )
    raw = f"{token_id}:{secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _api(method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{API}{path}",
        data=body,
        method=method,
        headers={"Authorization": _auth_header(), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())["data"]
    except urllib.error.HTTPError as error:
        # Mux 는 에러 본문에 사유를 담는다 — 삼키면 "왜 400 이지" 로 헤맨다.
        raise CommandError(f"Mux {method} {path} → {error.code}\n{error.read().decode()}")


def _put_file(url, path):
    """업로드 URL 에 파일을 그대로 올린다.

    파일 객체를 그대로 넘겨 스트리밍한다 — 4K 원본은 GB 단위라 통째로 읽으면
    메모리에 다 올라간다. Content-Length 를 명시해야 서버가 받는다.
    """
    size = path.stat().st_size
    with path.open("rb") as handle:
        request = urllib.request.Request(
            url, data=handle, method="PUT", headers={"Content-Length": str(size)}
        )
        with urllib.request.urlopen(request) as response:
            return response.status


class Command(BaseCommand):
    help = "영상 파일을 Mux 에 올리고(plus·4K·signed) videos 행을 만든다"

    def _say(self, line):
        """진행 표시 — 매 줄 flush 한다.

        기본 stdout 은 파이프·nohup 에서 버퍼링돼, GB 단위 업로드가 도는 내내
        화면에 아무것도 안 뜬다(2026-08-04 3.5GB 업로드에서 실측). 오래 걸리는
        작업일수록 "멈춘 건가"를 판단할 근거가 필요하다.
        """
        self.stdout.write(line)
        self.stdout.flush()

    def add_arguments(self, parser):
        parser.add_argument("path", help="올릴 영상 파일 경로")
        parser.add_argument("--title", required=True, help="영상 제목")
        parser.add_argument("--week", type=int, help="CourseWeek.week_id (없으면 특강)")
        parser.add_argument("--seq", type=int, help="차시")
        parser.add_argument(
            "--quality", default=VIDEO_QUALITY, choices=["basic", "plus", "premium"]
        )
        parser.add_argument(
            "--no-record",
            action="store_true",
            help="Mux 에만 올리고 videos 행은 만들지 않는다(등급 비교용)",
        )

    def handle(self, *args, **options):
        path = Path(options["path"]).expanduser()
        if not path.is_file():
            raise CommandError(f"파일이 없습니다: {path}")
        week = None
        if options["week"]:
            week = CourseWeek.objects.filter(pk=options["week"]).first()
            if week is None:
                raise CommandError(f"주차를 찾을 수 없습니다: {options['week']}")

        size_gb = path.stat().st_size / 1_000_000_000
        self._say(
            f"{path.name} ({size_gb:.2f} GB) → "
            f"{options['quality']} · {MAX_RESOLUTION} · {PLAYBACK_POLICY}"
        )

        upload = _api(
            "POST",
            "/uploads",
            {
                "cors_origin": "*",
                "new_asset_settings": {
                    "playback_policies": [PLAYBACK_POLICY],
                    "video_quality": options["quality"],
                    "max_resolution_tier": MAX_RESOLUTION,
                },
            },
        )
        self._say("  업로드 자리 생성 · 전송 중… (GB 단위라 오래 걸린다)")
        _put_file(upload["url"], path)

        self._say("  전송 완료 · 인코딩 대기…")
        asset_id = None
        for _ in range(POLL_LIMIT):
            state = _api("GET", f"/uploads/{upload['id']}")
            if state.get("asset_id"):
                asset_id = state["asset_id"]
                break
            if state.get("status") == "errored":
                raise CommandError(f"업로드 실패: {state.get('error')}")
            time.sleep(POLL_INTERVAL)
        if asset_id is None:
            raise CommandError("자산 생성이 시간 안에 끝나지 않았습니다.")

        asset = None
        for _ in range(POLL_LIMIT):
            asset = _api("GET", f"/assets/{asset_id}")
            if asset["status"] == "ready":
                break
            if asset["status"] == "errored":
                raise CommandError(f"인코딩 실패: {asset.get('errors')}")
            time.sleep(POLL_INTERVAL)
        if asset["status"] != "ready":
            raise CommandError("인코딩이 시간 안에 끝나지 않았습니다.")

        playback_ids = asset.get("playback_ids") or []
        if not playback_ids:
            raise CommandError("Playback ID 가 없습니다(정책 설정 확인).")
        playback_id = playback_ids[0]["id"]

        self._say(self.style.SUCCESS("  완료"))
        self._say(f"    asset_id      {asset_id}")
        self._say(f"    playback_id   {playback_id}  ← external_ref 에 넣는 값")
        self._say(f"    최대 저장 해상도  {asset.get('max_stored_resolution')}")
        self._say(f"    길이          {round(asset.get('duration', 0) / 60)}분")

        if options["no_record"]:
            self._say("  (videos 행은 만들지 않았습니다)")
            return

        video = Video.objects.create(
            title=options["title"],
            course_week=week,
            sequence_no=options["seq"],
            provider=Video.Provider.MUX,
            external_ref=playback_id,
            duration_seconds=int(asset.get("duration") or 0) or None,
        )
        # 상태는 기본값 `준비중` 이다 — 공개는 관리 화면에서 사람이 누른다.
        self._say(f"    videos 행     {video.video_id} ({video.status})")
