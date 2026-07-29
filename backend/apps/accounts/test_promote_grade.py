"""promote_grade 관리 커맨드 테스트 — **학년만** 올린다 (2026-07-29 재개정).

같은 날 오전 판이 원번을 함께 재계산했는데, 원번에서 학년이 빠지면서 그 이유가
사라졌다. 이제 이 커맨드가 건드리는 컬럼은 `students.grade` 하나뿐이다.

검증 축:
- 승급: 등록 학생의 `grade` 가 한 학년 오른다(고1→고2→고3→N수, N수 정지)
- 불변 계약: `unique_id`·`login_id`·`student_id` 를 승급이 건드리지 않는다
- 대상 한정: 예비등록·퇴원 학생은 손대지 않는다
- 건너뜀: 승급표에 없는 표기(N수·중3 등) — 계정·번호는 더 이상 조건이 아니다
- 출력: 학년 변화만 보인다(원번 얘기가 없다)
- `--dry-run`: 무엇이 바뀔지 출력만 하고 DB 는 그대로
"""
import io

from django.core.management import call_command
from django.test import TestCase

from .models import Student, User
from .unique_id import build_unique_id


def make_student(name, phone, grade, status=Student.EnrollmentStatus.REGISTERED):
    """학생 1명 — 아이디·원번은 발급 규칙과 같은 형태로 직접 만든다."""
    user = User.objects.create_user(
        login_id=f"{name}{phone[-4:]}",
        password="pw-Secret-77!",
        name=name,
        role=User.Role.STUDENT,
        phone=phone,
    )
    return Student.objects.create(
        user=user,
        unique_id=build_unique_id(name, phone),
        grade=grade,
        enrollment_status=status,
    )


def promote(*args):
    out = io.StringIO()
    call_command("promote_grade", *args, stdout=out)
    return out.getvalue()


class PromoteGradeTests(TestCase):
    def test_promotes_grade_only(self):
        student = make_student("김하늘", "01010000001", "고1")
        promote()
        student.refresh_from_db()
        self.assertEqual(student.grade, "고2")
        self.assertEqual(student.unique_id, "김하늘0001")

    def test_unique_id_login_id_and_student_id_never_change(self):
        """셋 다 불변이다 — 원번은 학년이 빠지면서 승급의 관심사가 아니게 됐다."""
        student = make_student("박서준", "01010000002", "고2")
        before = (
            student.student_id,
            student.unique_id,
            student.user.login_id,
            student.user.user_id,
        )
        promote()
        student.refresh_from_db()
        student.user.refresh_from_db()
        self.assertEqual(
            (
                student.student_id,
                student.unique_id,
                student.user.login_id,
                student.user.user_id,
            ),
            before,
        )
        self.assertEqual(student.grade, "고3")

    def test_output_shows_the_grade_change_and_nothing_about_unique_id(self):
        """실제 반영에서도 **바뀌기 전 학년**이 보여야 한다(반영 뒤 찍으면 둘이 같아진다)."""
        make_student("김하늘", "01010000001", "고1")
        output = promote()
        self.assertIn("고1 → 고2", output)
        self.assertNotIn("원번", output)
        self.assertNotIn("김하늘0001", output)

    def test_go3_becomes_n_su(self):
        student = make_student("최고삼", "01010000003", "고3")
        output = promote()
        student.refresh_from_db()
        self.assertEqual(student.grade, "N수")
        self.assertIn("고3 → N수", output)

    def test_n_su_is_the_top(self):
        """N수는 더 올릴 곳이 없다 — 졸업 처리는 아직 없다."""
        student = make_student("정엔수", "01010000009", "N수")
        output = promote()
        student.refresh_from_db()
        self.assertEqual(student.grade, "N수")
        self.assertIn("건너뜀", output)

    def test_unlisted_grade_is_skipped(self):
        """승급 표에 없는 표기 — 다음 학년을 만들 수 없어 건너뛴다."""
        student = make_student("정중등", "01010000004", "중3")
        output = promote()
        student.refresh_from_db()
        self.assertEqual(student.grade, "중3")
        self.assertIn("건너뜀", output)

    def test_pre_registered_and_withdrawn_are_untouched(self):
        pre = make_student(
            "이예비", "01010000005", "고1", Student.EnrollmentStatus.PRE_REGISTERED
        )
        out = make_student(
            "강퇴원", "01010000006", "고1", Student.EnrollmentStatus.WITHDRAWN
        )
        promote()
        pre.refresh_from_db()
        out.refresh_from_db()
        self.assertEqual(pre.grade, "고1")
        self.assertEqual(out.grade, "고1")

    def test_student_without_account_still_promotes(self):
        """계정은 더 이상 승급 조건이 아니다 — 학년은 학생 정보이고 원번은 안 바뀐다."""
        student = Student.objects.create(
            unique_id="이름없음0000", grade="고1",
            enrollment_status=Student.EnrollmentStatus.REGISTERED,
        )
        promote()
        student.refresh_from_db()
        self.assertEqual(student.grade, "고2")
        self.assertEqual(student.unique_id, "이름없음0000")

    def test_student_without_any_phone_still_promotes(self):
        """번호도 승급 조건이 아니다 — 뒷4자리는 원번을 만들 때만 필요했다."""
        user = User.objects.create_user(
            login_id="무번호0000", password="pw-Secret-77!",
            name="무번호", role=User.Role.STUDENT, phone="",
        )
        student = Student.objects.create(
            user=user, unique_id="", grade="고1",
            enrollment_status=Student.EnrollmentStatus.REGISTERED,
        )
        promote()
        student.refresh_from_db()
        self.assertEqual(student.grade, "고2")


class PromoteGradeDryRunTests(TestCase):
    def test_dry_run_changes_nothing(self):
        student = make_student("김하늘", "01010000001", "고1")
        promote("--dry-run")
        student.refresh_from_db()
        self.assertEqual(student.grade, "고1")

    def test_dry_run_shows_before_and_after(self):
        make_student("김하늘", "01010000001", "고1")
        output = promote("--dry-run")
        self.assertIn("고1", output)
        self.assertIn("고2", output)
