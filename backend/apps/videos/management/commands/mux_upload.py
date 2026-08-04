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

## 왜 `plus` 인가

`basic` 은 **DRM 이 안 된다**(우리 필수 요건). `premium` 은 전 항목 1.5배인데
"라이브 스포츠·스튜디오 영화" 튜닝이라 판서 강의에 값을 못 한다.
셋 다 4K 를 내고 per-title encoding 은 plus·premium 이 같은 것을 쓴다.
(2026-08-04 확정 — docs/2026-08-04-영상호스팅-비용재계산.md)

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
VIDEO_QUALITY = "plus"
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
        self.stdout.write(
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
        self.stdout.write("  업로드 자리 생성 · 전송 중…")
        _put_file(upload["url"], path)

        self.stdout.write("  전송 완료 · 인코딩 대기…")
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

        self.stdout.write(self.style.SUCCESS("  완료"))
        self.stdout.write(f"    asset_id      {asset_id}")
        self.stdout.write(f"    playback_id   {playback_id}  ← external_ref 에 넣는 값")
        self.stdout.write(f"    최대 저장 해상도  {asset.get('max_stored_resolution')}")
        self.stdout.write(f"    길이          {round(asset.get('duration', 0) / 60)}분")

        if options["no_record"]:
            self.stdout.write("  (videos 행은 만들지 않았습니다)")
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
        self.stdout.write(f"    videos 행     {video.video_id} ({video.status})")
