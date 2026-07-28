"""로그인 아이디 생성 규칙 전수 테스트 — PRD 8-4 개정(2026-07-28 한글 전환).

검증 축:
- 이름 정규화: 공백·특수문자 제거, 영문 소문자화, 길이 상한
- 휴대폰 뒷4자리: 구분자 제거 후 마지막 4자리, 자릿수 부족은 오류
- 학생: {이름}{뒷4자리} / 무전화 학생은 학부모 번호 뒷4자리
- 학부모: {학생 아이디}p — 같은 뒷4자리를 공유해도 p 로 구분
- 충돌: 접미사 a·b·… (p 제외 — 학부모 아이디와 충돌 불가), 소진 시 오류
- 직원: 학생과 동일 축(이름+뒷4자리)
- 순수성: is_taken 주입만으로 DB 없이 전 규칙이 성립
"""
from django.test import SimpleTestCase, TestCase

from .login_id import (
    COLLISION_SUFFIXES,
    PARENT_SUFFIX,
    LoginIdError,
    issue_parent_login_id,
    issue_staff_login_id,
    issue_student_login_id,
    normalize_name,
    person_base,
    phone_tail4,
)
from .models import User


def taken_set(*ids):
    """주입용 is_taken — DB 없이 규칙만 검증하기 위한 순수 술어."""
    used = set(ids)
    return used.__contains__


class NormalizeNameTests(SimpleTestCase):
    def test_strips_spaces(self):
        self.assertEqual(normalize_name(" 김 하늘 "), "김하늘")

    def test_removes_special_characters(self):
        self.assertEqual(normalize_name("김·하늘(전학)"), "김하늘전학")

    def test_lowercases_ascii_letters(self):
        self.assertEqual(normalize_name("John Doe"), "johndoe")

    def test_keeps_digits(self):
        self.assertEqual(normalize_name("김하늘2"), "김하늘2")

    def test_empty_after_normalization_rejected(self):
        with self.assertRaises(LoginIdError):
            normalize_name("()!!")

    def test_blank_rejected(self):
        with self.assertRaises(LoginIdError):
            normalize_name("   ")

    def test_long_name_truncated(self):
        # login_id max_length=50 을 접미사까지 포함해 넘지 않도록 상한을 둔다
        self.assertEqual(len(normalize_name("가" * 40)), 20)


class PhoneTailTests(SimpleTestCase):
    def test_plain_number(self):
        self.assertEqual(phone_tail4("01012344821"), "4821")

    def test_hyphenated_number(self):
        self.assertEqual(phone_tail4("010-1234-4821"), "4821")

    def test_spaced_number(self):
        self.assertEqual(phone_tail4(" 010 1234 4821 "), "4821")

    def test_too_few_digits_rejected(self):
        with self.assertRaises(LoginIdError):
            phone_tail4("123")

    def test_empty_rejected(self):
        with self.assertRaises(LoginIdError):
            phone_tail4("")


class PersonBaseTests(SimpleTestCase):
    def test_name_plus_tail(self):
        self.assertEqual(person_base("김하늘", "010-1234-4821"), "김하늘4821")


class StudentLoginIdTests(SimpleTestCase):
    def test_own_phone_used(self):
        login_id = issue_student_login_id("김하늘", "01012344821", is_taken=taken_set())
        self.assertEqual(login_id, "김하늘4821")

    def test_phoneless_student_uses_parent_tail(self):
        login_id = issue_student_login_id(
            "김하늘", "", parent_phone="010-9999-4821", is_taken=taken_set()
        )
        self.assertEqual(login_id, "김하늘4821")

    def test_own_phone_wins_over_parent_phone(self):
        login_id = issue_student_login_id(
            "김하늘", "01011111111", parent_phone="01099994821", is_taken=taken_set()
        )
        self.assertEqual(login_id, "김하늘1111")

    def test_no_phone_at_all_rejected(self):
        with self.assertRaises(LoginIdError):
            issue_student_login_id("김하늘", "", parent_phone="", is_taken=taken_set())

    def test_name_normalized_before_use(self):
        login_id = issue_student_login_id("김 하늘", "010-1234-4821", is_taken=taken_set())
        self.assertEqual(login_id, "김하늘4821")


class ParentLoginIdTests(SimpleTestCase):
    def test_parent_is_student_id_plus_p(self):
        self.assertEqual(
            issue_parent_login_id("김하늘4821", is_taken=taken_set()), "김하늘4821p"
        )

    def test_parent_suffix_constant(self):
        self.assertEqual(PARENT_SUFFIX, "p")

    def test_shared_tail_distinguished_by_p(self):
        # 무전화 학생 — 학생·학부모가 같은 뒷4자리를 쓰되 p 로 구분된다
        student = issue_student_login_id(
            "김하늘", "", parent_phone="01099994821", is_taken=taken_set()
        )
        parent = issue_parent_login_id(student, is_taken=taken_set(student))
        self.assertEqual((student, parent), ("김하늘4821", "김하늘4821p"))

    def test_parent_of_collided_student_follows_that_student(self):
        # 학생이 접미사를 받았으면 학부모는 그 최종 아이디 뒤에 p 를 붙인다
        parent = issue_parent_login_id("김민준1234a", is_taken=taken_set())
        self.assertEqual(parent, "김민준1234ap")


class CollisionTests(SimpleTestCase):
    def test_first_collision_gets_a(self):
        login_id = issue_student_login_id(
            "김민준", "01000001234", is_taken=taken_set("김민준1234")
        )
        self.assertEqual(login_id, "김민준1234a")

    def test_second_collision_gets_b(self):
        login_id = issue_student_login_id(
            "김민준", "01000001234", is_taken=taken_set("김민준1234", "김민준1234a")
        )
        self.assertEqual(login_id, "김민준1234b")

    def test_p_is_never_used_as_collision_suffix(self):
        # p 는 학부모 표식 — 충돌 접미사에서 제외해야 학생/학부모 아이디가 겹치지 않는다
        self.assertNotIn("p", COLLISION_SUFFIXES)
        self.assertEqual(len(COLLISION_SUFFIXES), 25)

    def test_sixteenth_collision_skips_p(self):
        # a..o(15개) 다음은 p 가 아니라 q 여야 한다
        used = ["김민준1234"] + [f"김민준1234{s}" for s in "abcdefghijklmno"]
        self.assertEqual(
            issue_student_login_id("김민준", "01000001234", is_taken=taken_set(*used)),
            "김민준1234q",
        )

    def test_exhausted_suffixes_rejected(self):
        used = ["김민준1234"] + [f"김민준1234{s}" for s in COLLISION_SUFFIXES]
        with self.assertRaises(LoginIdError):
            issue_student_login_id("김민준", "01000001234", is_taken=taken_set(*used))

    def test_parent_collision_also_suffixed(self):
        parent = issue_parent_login_id("김하늘4821", is_taken=taken_set("김하늘4821p"))
        self.assertEqual(parent, "김하늘4821pa")


class StaffLoginIdTests(SimpleTestCase):
    def test_staff_uses_same_axis_as_student(self):
        self.assertEqual(
            issue_staff_login_id("한종철", "010-0000-0001", is_taken=taken_set()),
            "한종철0001",
        )

    def test_staff_collision_suffixed(self):
        self.assertEqual(
            issue_staff_login_id("김관리", "01000000002", is_taken=taken_set("김관리0002")),
            "김관리0002a",
        )


class DefaultTakenPredicateTests(TestCase):
    """is_taken 미지정 시 users 테이블을 준거로 삼는다(발급 경로 공통 기본값)."""

    def test_existing_user_forces_suffix(self):
        User.objects.create_user(
            login_id="김하늘4821", password="pw-1!", name="김하늘", role=User.Role.STUDENT
        )
        self.assertEqual(issue_student_login_id("김하늘", "01000004821"), "김하늘4821a")

    def test_free_id_used_as_is(self):
        self.assertEqual(issue_student_login_id("박서준", "01000007777"), "박서준7777")
