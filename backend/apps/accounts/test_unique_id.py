"""원번 생성 규칙 전수 테스트 — 2026-07-29 재개정(원번 = 이름 + 뒷4자리).

같은 날 오전에 넣었던 학년 자리를 **걷어냈다**. 지면(OMR·워크북)에 들어오는
것이 이름 + 뒷4자리이므로 원번도 그 두 축뿐이다.

검증 축:
- 형식: `{정규화 이름}{휴대폰 뒷4자리}` — 예 `김하늘4821`
- 로그인 아이디와의 관계: **원번 == 아이디에서 충돌 접미사를 뗀 값**
- 동명이인+같은 뒷4자리: 아이디는 접미사로 갈리고 **원번은 둘 다 같다**
- 무전화 학생: 학부모 번호 뒷4자리(login_id 8-3 과 같은 규칙)
- 학년 비관여: 학년은 원번에 영향을 주지 않는다(인자로도 받지 않는다)
- 순수성: DB 없이 규칙 전수가 성립(SimpleTestCase)
"""
import inspect

from django.test import SimpleTestCase

from . import unique_id as unique_id_module
from .login_id import LoginIdError, issue_student_login_id, person_base, student_phone_tail4
from .models import Student
from .unique_id import build_unique_id


class BuildUniqueIdTests(SimpleTestCase):
    def test_name_and_phone_tail(self):
        self.assertEqual(build_unique_id("김하늘", "01012344821"), "김하늘4821")

    def test_name_normalized_like_login_id(self):
        self.assertEqual(build_unique_id(" 김 하늘 ", "010-1234-4821"), "김하늘4821")

    def test_equals_login_id_body(self):
        # 원번 = 로그인 아이디에서 충돌 접미사를 뗀 값 — 두 규칙이 갈리지 않게 못 박는다
        self.assertEqual(
            build_unique_id("김하늘", "01012344821"),
            person_base("김하늘", "01012344821"),
        )

    def test_equals_login_id_when_there_is_no_collision(self):
        """충돌이 없으면 원번과 로그인 아이디가 **같은 문자열**이다."""
        self.assertEqual(
            build_unique_id("김하늘", "01012344821"),
            issue_student_login_id("김하늘", "01012344821", is_taken=lambda _: False),
        )

    def test_phoneless_student_uses_parent_tail(self):
        self.assertEqual(
            build_unique_id("김하늘", "", parent_phone="010-9999-4821"), "김하늘4821"
        )

    def test_own_phone_wins_over_parent_phone(self):
        self.assertEqual(
            build_unique_id("김하늘", "01011111111", parent_phone="01099994821"),
            "김하늘1111",
        )

    def test_no_phone_at_all_rejected(self):
        with self.assertRaises(LoginIdError):
            build_unique_id("김하늘", "", parent_phone="")

    def test_unusable_name_rejected(self):
        with self.assertRaises(LoginIdError):
            build_unique_id("!!!", "01012344821")

    def test_longest_possible_fits_the_column(self):
        # 이름 상한(login_id 정규화 20자)까지 쓴 원번이 students.unique_id 에 들어가야 한다
        longest = build_unique_id("가" * 40, "01012344821")
        self.assertEqual(len(longest), 20 + 4)
        column = Student._meta.get_field("unique_id")
        self.assertLessEqual(len(longest), column.max_length)


class DuplicateUniqueIdTests(SimpleTestCase):
    """동명이인 + 같은 뒷4자리 — 아이디는 갈리고 원번은 갈리지 않는다.

    이것이 원번의 성격이다(2026-07-29 사용자 확정). 겹치면 지면 매칭에서
    중복으로 떨어지고 **관리자가 고른다** — 접미사로 자동 해소하지 않는다.
    """

    def test_two_students_share_one_unique_id(self):
        first = build_unique_id("김민준", "01011111234")
        second = build_unique_id("김민준", "01022221234")
        self.assertEqual(first, second)
        self.assertEqual(first, "김민준1234")

    def test_login_ids_split_while_unique_ids_do_not(self):
        taken = set()

        def is_taken(candidate):
            return candidate in taken

        first = issue_student_login_id("김민준", "01011111234", is_taken=is_taken)
        taken.add(first)
        second = issue_student_login_id("김민준", "01022221234", is_taken=is_taken)
        self.assertEqual((first, second), ("김민준1234", "김민준1234a"))
        self.assertEqual(
            build_unique_id("김민준", "01011111234"),
            build_unique_id("김민준", "01022221234"),
        )

    def test_unique_id_is_the_login_id_without_its_suffix(self):
        login_id = issue_student_login_id(
            "김민준", "01022221234", is_taken=lambda c: c == "김민준1234"
        )
        self.assertEqual(login_id, "김민준1234a")
        self.assertEqual(build_unique_id("김민준", "01022221234"), login_id[:-1])


class SharedTailRuleTests(SimpleTestCase):
    """뒷자리 추출은 login_id 모듈 것을 그대로 쓴다 — 두 곳에 흩어지면 갈린다."""

    def test_unique_id_tail_is_login_id_tail(self):
        self.assertEqual(
            build_unique_id("김하늘", "", parent_phone="01099994821")[-4:],
            student_phone_tail4("", "01099994821"),
        )


class NoGradeInUniqueIdTests(SimpleTestCase):
    """학년은 원번에서 빠졌다 — 모듈에 학년이 남아 있으면 안 된다.

    (같은 날 오전 개정의 잔재를 못 박아 둔다. `grade_digit`·`numeric_key` 는
    원번 때문에 있었고, 지면 전제가 이름+뒷4 로 바뀌면서 쓸 데가 사라졌다.)
    """

    def test_signature_has_no_grade_argument(self):
        params = list(inspect.signature(build_unique_id).parameters)
        self.assertEqual(params, ["name", "phone", "parent_phone"])

    def test_module_exposes_nothing_grade_shaped(self):
        for gone in ("grade_digit", "numeric_key", "UniqueIdError"):
            self.assertFalse(hasattr(unique_id_module, gone), gone)
