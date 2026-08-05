"""promote_grade — 등록 학생의 학년을 한 학년씩 올린다.

**바꾸는 컬럼은 `students.grade` 하나뿐이다.** 2026-07-29 재개정으로 원번에서
학년이 빠지면서(`accounts.matching_key`) 승급이 원번을 다시 계산할 이유가 사라졌다.
같은 날 오전 판이 하던 원번 재계산은 걷어냈다 — 그 판의 근거였던 "학년이 원번의
일부" 자체가 뒤집혔다.

## 불변 계약

`students.matching_key`·`users.login_id`·`students.student_id` 를 **건드리지 않는다.**
원번은 이름·휴대폰 파생값이라 승급의 관심사가 아니고, 아이디가 바뀌면 재로그인
혼란·계정정보 재발송이 생기며, `student_id` 는 전 도메인 FK 의 대상이라 애초에
바꿀 수 없다.

## 대상과 건너뜀

대상은 **등록 학생**뿐이다(예비등록은 아직 학사에 들어오지 않았고, 퇴원은 지난
기록이라 학년을 올리면 이력이 왜곡된다). 건너뛰는 것은 **승급표에 없는 학년**
하나뿐이다:

- **N수** — 그다음(졸업)은 아직 정해지지 않았다(8-19, 범위 밖).
- **표에 없는 표기** — `중3`·`고등부`·빈값 등. 다음 학년이 무엇인지 알 수 없다.

계정 없음·번호 없음은 **더 이상 건너뜀 사유가 아니다** — 원번을 다시 만들지
않으므로 이름·휴대폰이 필요 없다. 학년은 학생 정보이고 계정 유무와 무관하다.

## 사용

    python manage.py promote_grade --dry-run   # 무엇이 바뀔지만 출력
    python manage.py promote_grade             # 실제 반영(한 트랜잭션)

`--dry-run` 을 먼저 돌려 대상과 건너뜀을 확인한 뒤 실행한다.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Student

# 승급표 — **학년 표기**를 키로 잡는다. 자리값(숫자)으로 키를 잡으면 `중3` 이
# 3이라 고3과 같은 칸을 타고 N수로 올라간다(2026-07-29 실측).
# 고3 다음은 N수(사용자 확정 "n수는 학년이 4야 그게 끝").
# N수는 표에 없다 — 재수를 몇 년 하든 N수에 머물고, 그다음 졸업 처리는 아직 없다.
NEXT_GRADE = {"고1": "고2", "고2": "고3", "고3": "N수"}


class Command(BaseCommand):
    help = "등록 학생의 학년을 한 학년 올린다(고3→N수, N수는 건너뜀)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="바꾸지 않고 바뀔 내용만 출력한다",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        students = (
            Student.objects.filter(
                enrollment_status=Student.EnrollmentStatus.REGISTERED
            )
            .select_related("user")
            .order_by("student_id")
        )

        planned, skipped = [], []
        for student in students:
            grade = NEXT_GRADE.get("".join((student.grade or "").split()))
            if grade is None:
                skipped.append(student)
            else:
                planned.append(_Change(student, grade))

        if not dry_run:
            with transaction.atomic():
                for change in planned:
                    change.student.grade = change.grade
                    change.student.save(update_fields=["grade"])

        self._report(planned, skipped, dry_run)

    def _report(self, planned, skipped, dry_run):
        w = self.stdout.write
        for change in planned:
            w(f"  {_label(change.student)} · {change.was_grade} → {change.grade}")
        for student in skipped:
            w(
                f"  건너뜀 — {_label(student)} · "
                f"{(student.grade or '').strip() or '(학년 없음)'} · 다음 학년이 없습니다."
            )
        headline = (
            f"승급 대상 {len(planned)}명 · 건너뜀 {len(skipped)}명"
            if dry_run
            else f"승급 {len(planned)}명 · 건너뜀 {len(skipped)}명"
        )
        w(self.style.SUCCESS(headline) if not dry_run else headline)


class _Change:
    """한 학생의 승급 전·후 학년 — dry-run 과 실제 반영이 같은 계산을 쓰게 묶는다.

    **전 값을 여기 복사해 둔다.** 학생 객체에서 그때그때 읽으면 실제 반영 뒤에는
    전·후가 같은 값이 되어 리포트가 "고2 → 고2" 로 찍힌다.
    """

    __slots__ = ("student", "was_grade", "grade")

    def __init__(self, student, grade):
        self.student = student
        self.was_grade = student.grade
        self.grade = grade


def _label(student):
    """리포트에 쓰는 이름 — 계정이 없는 학생 행도 있으므로 번호로 대신한다."""
    return student.user.name if student.user else f"학생 #{student.student_id}"
