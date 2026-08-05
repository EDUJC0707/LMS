"""곧 시작하는 클리닉의 리마인더를 건다.

    .venv/bin/python manage.py send_clinic_reminders

**매분 돌린다**(`infra/crontab`). 보낼 것이 없으면 조회 한 번으로 끝나고, 이미
보낸 건은 대상에서 빠지므로 두 번 돌아도 알림이 두 번 가지 않는다
(`apps.clinic.reminders` 머리말).
"""
from django.core.management.base import BaseCommand

from apps.clinic import reminders


class Command(BaseCommand):
    help = "시작 6분 안쪽인 클리닉에 리마인더를 보낸다."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if options["dry_run"]:
            from django.utils import timezone

            for request in reminders.due(timezone.now()):
                self.stdout.write(
                    f"#{request.clinic_id} {request.student.matching_key} "
                    f"{request.requested_date} {request.requested_time:%H:%M}"
                )
            return
        sent = reminders.send_due()
        if sent:
            self.stdout.write(f"리마인더 {sent}건")
