"""별칭표 규칙 테스트 — FLOW 2-2.

검증 축:
- `alias_key`: 눈에 다른 머리줄이 한 키로 모인다(공백·대소문자·NFD 한글).
  **프런트 `paste.ts` 의 squash() 와 같은 값**이어야 표에 저장한 답이 다음
  파일에서 맞는다
- 초기값: 표로 옮기면서 **자동 매칭이 후퇴하지 않았다** — 예전에 프런트가
  맞히던 머리줄이 표에서도 맞는다(0007 데이터 시드)
- `resolve_school`: 아는 별칭은 정식 이름으로, **모르는 학교는 온 그대로**
  (FLOW 2-3 — 학교는 판정에 쓰지 않으므로 막지 않는다)
- 자기 등록: `alias == alias_key(canonical)` 행 하나가 곧 새 학교 등록이다
"""
import unicodedata

from django.test import SimpleTestCase, TestCase

from .aliases import alias_key, column_map, resolve_school
from .models import SchoolAlias


class AliasKeyTests(SimpleTestCase):
    def test_spaces_and_case_collapse(self):
        """`학생 HP` · `학생hp` · `학생-HP` 는 한 별칭이다."""
        self.assertEqual(alias_key("학생 HP"), "학생hp")
        self.assertEqual(alias_key("학생hp"), "학생hp")
        self.assertEqual(alias_key("학생-HP"), "학생hp")

    def test_decomposed_korean_collapses(self):
        """맥 파일의 분해형(NFD) 머리줄도 같은 키가 된다 — FLOW 2-2 ①."""
        self.assertEqual(alias_key(unicodedata.normalize("NFD", "학생 연락처")), "학생연락처")

    def test_non_string_is_empty(self):
        """엑셀이 숫자로 준 머리줄은 별칭이 아니다(호출자가 빈 값으로 다룬다)."""
        self.assertEqual(alias_key(None), "")
        self.assertEqual(alias_key(3), "")


class ColumnMapTests(TestCase):
    def test_seeded_headers_still_match(self):
        """표로 옮기기 전 프런트가 맞히던 머리줄이 그대로 맞는다."""
        table = column_map()
        self.assertEqual(table[alias_key("학생 연락처")], "phone")
        self.assertEqual(table[alias_key("학부모 연락처")], "parent_phone")
        self.assertEqual(table[alias_key("성명")], "name")
        self.assertEqual(table[alias_key("학교")], "school")


class ResolveSchoolTests(TestCase):
    def test_alias_becomes_canonical(self):
        SchoolAlias.objects.create(alias="숙명여고", canonical="숙명여자고등학교")
        self.assertEqual(resolve_school("숙명여고"), "숙명여자고등학교")
        # 띄어 쓴 같은 이름도 같은 키로 모인다 — FLOW 2-2 의 `숙명 여고`.
        self.assertEqual(resolve_school("숙명 여고"), "숙명여자고등학교")

    def test_unknown_school_passes_through(self):
        """모르는 학교는 막지 않고 온 그대로 저장한다 — FLOW 2-3."""
        self.assertEqual(resolve_school(" 세화고 "), "세화고")
        self.assertEqual(resolve_school(""), "")
        self.assertEqual(resolve_school(None), "")

    def test_self_registration(self):
        """정식 이름 자신을 별칭으로 넣은 행 = 새 학교 등록."""
        SchoolAlias.objects.create(alias="휘문고등학교", canonical="휘문고등학교")
        self.assertEqual(resolve_school("휘문고등학교"), "휘문고등학교")
