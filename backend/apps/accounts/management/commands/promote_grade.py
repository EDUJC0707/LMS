"""promote_grade — 학년을 한 학년씩 올리고 **원번을 다시 계산**한다.

2026-07-29 원번 개정으로 원번이 `{학년}{이름}{뒷4자리}` 파생값이 됐다. 학년이
원번의 일부이므로 "매년 학년을 올린다"는 운영 행위에 원번 재계산이 따라붙는다 —
손으로 고칠 수 있는 화면이 없으므로 이 커맨드가 그 유일한 수단이다.

## 불변 계약

`users.login_id` 와 `students.student_id` 는 **건드리지 않는다.** 아이디가 바뀌면
재로그인 혼란·계정정보 재발송이 생기고, `student_id` 는 전 도메인 FK 의 대상이라
애초에 바꿀 수 없다. 바뀌는 것은 `students.grade` 와 `students.unique_id` 뿐이다.

## 대상과 건너뜀

대상은 **등록 학생**뿐이다(예비등록은 아직 학사에 들어오지 않았고, 퇴원은 지난
기록이라 학년을 올리면 이력이 왜곡된다). 다음은 건너뛰고 사유와 함께 알린다:

- **N수** — 자리값 4가 끝이다. 그다음(졸업)은 아직 정해지지 않았다(범위 밖).
- **학년을 읽을 수 없음** — 숫자가 둘 이상이거나, 표에 없는 표기(중등 등).
- **계정 없음·번호 없음** — 원번을 다시 계산할 재료(이름·휴대폰)가 없다.

## 사용

    python manage.py promote_grade --dry-run   # 무엇이 바뀔지만 출력
    python manage.py promote_grade             # 실제 반영(한 트랜잭션)

`--dry-run` 을 먼저 돌려 대상과 건너뜀을 확인한 뒤 실행한다.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.login_id import LoginIdError
from apps.accounts.models import ParentStudent, Student
from apps.accounts.unique_id import UniqueIdError, build_unique_id, grade_digit

# 승급표 — **학년 표기**를 키로 잡는다. 자리값(grade_digit)으로 키를 잡으면
# `중3` 이 자리값 3이라 고3과 같은 칸을 타고 N수로 올라간다(2026-07-29 실측).
# 고3 다음은 N수(사용자 확정 "n수는 학년이 4야 그게 끝").
# N수는 표에 없다 — 재수를 몇 년 하든 4에 머물고, 그다음 졸업 처리는 아직 없다.
NEXT_GRADE = {"고1": "고2", "고2": "고3", "고3": "N수"}


class Command(BaseCommand):
    help = "등록 학생의 학년을 한 학년 올리고 원번을 다시 계산한다(고3→N수, N수는 건너뜀)"

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
        parent_phones = _parent_phone_by_student()

        planned, skipped = [], []
        for student in students:
            try:
                planned.append(_plan(student, parent_phones.get(student.student_id, "")))
            except _Skip as skip:
                skipped.append((student, skip.reason))

        if not dry_run:
            with transaction.atomic():
                for change in planned:
                    change.student.grade = change.grade
                    change.student.unique_id = change.unique_id
                    change.student.save(update_fields=["grade", "unique_id"])

        self._report(planned, skipped, dry_run)

    def _report(self, planned, skipped, dry_run):
        w = self.stdout.write
        for change in planned:
            w(
                f"  {change.student.user.name} · {change.was_grade} → {change.grade}"
                f" · 원번 {change.was_unique_id or '(없음)'} → {change.unique_id}"
            )
        for student, reason in skipped:
            name = student.user.name if student.user else f"학생 #{student.student_id}"
            w(f"  건너뜀 — {name} · {student.grade or '(학년 없음)'} · {reason}")
        headline = (
            f"승급 대상 {len(planned)}명 · 건너뜀 {len(skipped)}명"
            if dry_run
            else f"승급 {len(planned)}명 · 건너뜀 {len(skipped)}명"
        )
        w(self.style.SUCCESS(headline) if not dry_run else headline)


class _Skip(Exception):
    """이 학생은 승급하지 않는다 — reason 이 그대로 출력된다."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class _Change:
    """한 학생의 승급 전·후 값 — dry-run 과 실제 반영이 같은 계산을 쓰게 묶는다.

    **전 값을 여기 복사해 둔다.** 학생 객체에서 그때그때 읽으면 실제 반영 뒤에는
    전·후가 같은 값이 되어 리포트가 "고2 → 고2" 로 찍힌다.
    """

    __slots__ = ("student", "was_grade", "was_unique_id", "grade", "unique_id")

    def __init__(self, student, grade, unique_id):
        self.student = student
        self.was_grade = student.grade
        self.was_unique_id = student.unique_id
        self.grade = grade
        self.unique_id = unique_id


def _plan(student, parent_phone):
    """학생 1명의 승급 후 (학년, 원번). 승급 불가면 `_Skip`."""
    if student.user is None:
        raise _Skip("계정이 없어 원번을 다시 만들 수 없습니다.")
    try:
        grade_digit(student.grade)  # 원번을 만들 수 있는 학년인지 먼저 본다
    except UniqueIdError as exc:
        raise _Skip(str(exc)) from exc
    grade = NEXT_GRADE.get("".join((student.grade or "").split()))
    if grade is None:
        raise _Skip(f"다음 학년이 없습니다: {(student.grade or '').strip() or '(빈값)'}")
    try:
        unique_id = build_unique_id(
            grade, student.user.name, student.user.phone, parent_phone
        )
    except (LoginIdError, UniqueIdError) as exc:
        raise _Skip(str(exc)) from exc
    return _Change(student, grade, unique_id)


def _parent_phone_by_student():
    """학생 → 학부모 번호 — 무전화 학생의 뒷4자리 출처(발급 때와 같은 규칙)."""
    phones = {}
    links = (
        ParentStudent.objects.select_related("parent")
        .order_by("id")
        .values_list("student_id", "parent__phone")
    )
    for student_id, phone in links:
        phones.setdefault(student_id, phone or "")
    return phones
