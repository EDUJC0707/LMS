"""원번 생성 규칙 전수 테스트 — 2026-07-29 개정(원번 = 학년 + 이름 + 뒷4자리).

검증 축:
- 형식: `{학년숫자}{정규화 이름}{휴대폰 뒷4자리}` — 예 `3김하늘4821`
- 학년 반영: 같은 학생도 학년이 다르면 원번이 다르다(원번은 가변)
- 로그인 아이디와의 관계: 원번 몸통 == 로그인 아이디 몸통(뒷자리 규칙 공유)
- 무전화 학생: 학부모 번호 뒷4자리(login_id 8-3 과 같은 규칙)
- 학년 파싱 실패: 숫자를 못 뽑거나 여러 자리면 예외
- OMR 숫자부: 학년1 + 뒷4 = 5자리(이름은 한글이라 버블로 못 마킹한다)
- 순수성: DB 없이 규칙 전수가 성립(SimpleTestCase)
"""
from django.test import SimpleTestCase

from .login_id import LoginIdError, person_base, student_phone_tail4
from .models import Student
from .unique_id import UniqueIdError, build_unique_id, grade_digit, numeric_key


class GradeDigitTests(SimpleTestCase):
    def test_high_school_grades(self):
        self.assertEqual(grade_digit("고1"), "1")
        self.assertEqual(grade_digit("고2"), "2")
        self.assertEqual(grade_digit("고3"), "3")

    def test_middle_school_notation(self):
        self.assertEqual(grade_digit("중3"), "3")

    def test_bare_digit(self):
        self.assertEqual(grade_digit("2"), "2")

    def test_surrounding_spaces_ignored(self):
        self.assertEqual(grade_digit(" 고2 "), "2")

    def test_no_digit_rejected(self):
        # 숫자도 없고 이름표에도 없는 표기 — 어느 학년인지 알 수 없다
        with self.assertRaises(UniqueIdError):
            grade_digit("고등부")

    def test_blank_rejected(self):
        with self.assertRaises(UniqueIdError):
            grade_digit("")

    def test_none_rejected(self):
        with self.assertRaises(UniqueIdError):
            grade_digit(None)

    def test_multiple_digits_rejected(self):
        # 원번의 학년부는 한 자리다 — 두 자리가 섞이면 어느 쪽이 학년인지 알 수 없다
        with self.assertRaises(UniqueIdError):
            grade_digit("고2-3반")

    def test_error_is_value_error(self):
        # 호출자가 ValueError 로 잡던 자리에서 그대로 잡힌다(LoginIdError 와 같은 결)
        self.assertTrue(issubclass(UniqueIdError, ValueError))


class BuildUniqueIdTests(SimpleTestCase):
    def test_grade_name_and_phone_tail(self):
        self.assertEqual(build_unique_id("고3", "김하늘", "01012344821"), "3김하늘4821")

    def test_grade_changes_the_unique_id(self):
        # 원번은 가변이다 — 학년이 올라가면 앞자리가 바뀐다(2026-07-29 확정)
        self.assertEqual(build_unique_id("고1", "김하늘", "01012344821"), "1김하늘4821")
        self.assertEqual(build_unique_id("고2", "김하늘", "01012344821"), "2김하늘4821")

    def test_name_normalized_like_login_id(self):
        self.assertEqual(build_unique_id("고2", " 김 하늘 ", "010-1234-4821"), "2김하늘4821")

    def test_body_equals_login_id_body(self):
        # 원번 = 학년 + 로그인아이디 몸통 — 두 규칙이 갈리지 않는지 못 박는다
        self.assertEqual(
            build_unique_id("고2", "김하늘", "01012344821")[1:],
            person_base("김하늘", "01012344821"),
        )

    def test_phoneless_student_uses_parent_tail(self):
        self.assertEqual(
            build_unique_id("고2", "김하늘", "", parent_phone="010-9999-4821"),
            "2김하늘4821",
        )

    def test_own_phone_wins_over_parent_phone(self):
        self.assertEqual(
            build_unique_id("고2", "김하늘", "01011111111", parent_phone="01099994821"),
            "2김하늘1111",
        )

    def test_no_phone_at_all_rejected(self):
        with self.assertRaises(LoginIdError):
            build_unique_id("고2", "김하늘", "", parent_phone="")

    def test_unusable_name_rejected(self):
        with self.assertRaises(LoginIdError):
            build_unique_id("고2", "!!!", "01012344821")

    def test_unparseable_grade_rejected(self):
        with self.assertRaises(UniqueIdError):
            build_unique_id("고등부", "김하늘", "01012344821")

    def test_longest_possible_fits_the_column(self):
        # 이름 상한(login_id 정규화 20자)까지 쓴 원번이 students.unique_id 에 들어가야 한다
        longest = build_unique_id("고3", "가" * 40, "01012344821")
        self.assertEqual(len(longest), 1 + 20 + 4)
        column = Student._meta.get_field("unique_id")
        self.assertLessEqual(len(longest), column.max_length)


class NumericKeyTests(SimpleTestCase):
    def test_five_digits_grade_then_tail(self):
        # OMR 답안지는 숫자부 5칸만 마킹한다(이름은 한글이라 버블 대상이 아니다)
        key = numeric_key("고2", "01012344821")
        self.assertEqual(key, "24821")
        self.assertEqual(len(key), 5)
        self.assertTrue(key.isdigit())

    def test_phoneless_student_uses_parent_tail(self):
        self.assertEqual(numeric_key("고1", "", parent_phone="010-9999-4821"), "14821")

    def test_matches_the_digits_of_the_unique_id(self):
        full = build_unique_id("고3", "김하늘", "01012344821")
        self.assertEqual(numeric_key("고3", "01012344821"), full[0] + full[-4:])

    def test_unparseable_grade_rejected(self):
        with self.assertRaises(UniqueIdError):
            numeric_key("고등부", "01012344821")


class SharedTailRuleTests(SimpleTestCase):
    """뒷자리 추출은 login_id 모듈 것을 그대로 쓴다 — 두 곳에 흩어지면 갈린다."""

    def test_unique_id_tail_is_login_id_tail(self):
        self.assertEqual(
            build_unique_id("고2", "김하늘", "", parent_phone="01099994821")[-4:],
            student_phone_tail4("", "01099994821"),
        )


class NSuGradeTests(SimpleTestCase):
    """N수 = 자리값 4 (2026-07-29 사용자 확정 — "n수는 학년이 4야 그게 끝").

    숫자가 없는 표기라 `_DIGITS` 로는 못 뽑는다. 이름으로 알아본다.
    """

    def test_n_su_is_four(self):
        for label in ("N수", "n수", "N 수", "재수"):
            self.assertEqual(grade_digit(label), "4", label)

    def test_n_su_unique_id(self):
        self.assertEqual(
            build_unique_id("N수", "김하늘", "01012344821"), "4김하늘4821"
        )

    def test_no_such_thing_as_go4(self):
        """자리값 4는 오직 N수다 — `고4` 라는 학년 표기는 쓰지 않는다.

        (표기 자체를 막지는 않는다. 여기서 못 박는 건 N수가 4를 차지한다는 것.)
        """
        self.assertEqual(grade_digit("N수"), grade_digit("재수"))
