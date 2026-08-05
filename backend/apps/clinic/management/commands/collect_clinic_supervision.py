"""끝난 클리닉의 감독 자료(요약·문서 링크)를 거둬 평가에 붙인다.

    .venv/bin/python manage.py collect_clinic_supervision

**아무 주기로나 돌려도 된다.** 이미 가져온 건은 대상에서 빠지므로 30분마다
돌리든 정오에 한 번 더 돌리든 결과가 같다(`supervision.collect` 머리말).
지금은 스케줄러가 없어 손으로 돌린다 — Celery 가 올라오면 이 명령이 하는 일을
그대로 태스크가 부르면 된다(할 일은 `.claude/to-do.md`).

`--dry-run` 은 대상만 세어 보고 업체를 부르지 않는다. 무엇이 걸려 있는지
확인할 때 쓴다.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.clinic import supervision
from apps.clinic.conferencing import ConferenceError


class Command(BaseCommand):
    help = "끝난 클리닉의 전사 요약·문서 링크를 수집한다."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        now = timezone.now()
        if options["dry_run"]:
            for request in supervision.pending(now):
                self.stdout.write(
                    f"#{request.clinic_id} {request.student.unique_id} "
                    f"{request.requested_date} {request.requested_time:%H:%M} "
                    f"→ {supervision.artifact_path(request)}"
                )
            return
        try:
            counts = supervision.collect(now=now)
        except ConferenceError as error:
            # 어댑터를 아예 못 만든 경우(설정 없음 등) — 대상 순회 전에 끝난다
            self.stderr.write(str(error))
            return
        self.stdout.write(
            f"수집 {counts['collected']} · 대기 {counts['waiting']} · 실패 {counts['failed']}"
        )
