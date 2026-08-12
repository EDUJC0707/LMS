"""진행 중인 클리닉에 감독 봇을 넣는다.

    .venv/bin/python manage.py dispatch_clinic_supervision

**수집과 달리 시각이 맞아야 한다.** 봇은 회의가 도는 동안에만 들어갈 수 있어서
지난 클리닉에는 넣을 수 없다(`supervision.DISPATCH_WINDOW` 밖은 대상에서 빠진다).
운영에서는 beat 가 1분마다 부르고, 이 명령은 손으로 확인할 때 쓴다.

**구글 경로에서는 아무 일도 일어나지 않는다** — 스페이스 설정이 전사를 알아서
켜므로 넣을 봇이 없다(`conferencing.ConferenceAdapter.start_supervision` 기본값).
봇이 필요한 업체로 `CLINIC_CONFERENCE_BACKEND` 를 바꿨을 때 살아난다.

`--dry-run` 은 대상만 보여 주고 업체를 부르지 않는다.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.clinic import supervision
from apps.clinic.conferencing import ConferenceError


class Command(BaseCommand):
    help = "진행 중인 클리닉에 감독 봇을 넣는다."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        now = timezone.now()
        if options["dry_run"]:
            for request in supervision.starting(now):
                self.stdout.write(
                    f"#{request.clinic_id} {request.student.matching_key} "
                    f"{request.requested_time:%H:%M} {request.conference_url} "
                    f"→ {supervision.artifact_path(request)}"
                )
            return
        try:
            counts = supervision.dispatch(now=now)
        except ConferenceError as error:
            self.stderr.write(str(error))
            return
        self.stdout.write(f"시작 {counts['started']} · 실패 {counts['failed']}")
