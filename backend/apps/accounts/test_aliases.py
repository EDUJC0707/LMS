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
from .features import FeatureKey
from .models import SchoolAlias, StaffFeatureGrant, User

PASSWORD = "pw-Secret-77!"


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


class AliasApiTests(TestCase):
    """별칭표 API — 보고 고치는 자리(FLOW 5-1).

    게이트는 이 표를 소비하는 계정 발급과 같은 `계정관리` 다.
    """

    URL = "/api/admin/aliases"

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            login_id="al-own", password=PASSWORD, name="대표", role=User.Role.OWNER
        )
        cls.assistant = User.objects.create_user(
            login_id="al-ast", password=PASSWORD, name="조교", role=User.Role.ASSISTANT
        )

    def post(self, body, user=None):
        self.client.force_login(user or self.owner)
        return self.client.post(self.URL, data=body, content_type="application/json")

    def test_assistant_needs_the_account_admin_key(self):
        self.client.force_login(self.assistant)
        self.assertEqual(self.client.get(self.URL).status_code, 403)
        StaffFeatureGrant.objects.create(
            user=self.assistant,
            feature_key=FeatureKey.ACCOUNT_ADMIN,
            is_granted=True,
            granted_by=self.owner,
        )
        self.assertEqual(self.client.get(self.URL).status_code, 200)

    def test_added_alias_is_stored_squashed(self):
        """조교가 적은 그대로가 아니라 **대조되는 형태**로 저장된다."""
        res = self.post({"table": "컬럼", "alias": "학생 폰번호", "target": "phone"})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["alias"], "학생폰번호")
        self.assertEqual(column_map()["학생폰번호"], "phone")

    def test_duplicate_alias_is_rejected(self):
        """같은 별칭이 두 열에 붙으면 어느 쪽이 이기는지 알 수 없다.

        `학생 HP` 는 초기값에 이미 있다 — 눌러 보면 그 사실이 나온다.
        """
        res = self.post({"table": "컬럼", "alias": "학생 HP", "target": "parent_phone"})
        self.assertEqual(res.status_code, 400)

    def test_unknown_column_is_rejected(self):
        res = self.post({"table": "컬럼", "alias": "학생주소", "target": "address"})
        self.assertEqual(res.status_code, 400)

    def test_retarget_and_delete(self):
        """잘못 붙인 것을 고치고 지운다 — FLOW 5-1 이 요구한 자리."""
        created = self.post(
            {"table": "학교", "alias": "숙명여고", "target": "숭명여자고등학교"}
        ).json()
        detail = f"{self.URL}/학교/{created['id']}"
        res = self.client.patch(
            detail, data={"target": "숙명여자고등학교"}, content_type="application/json"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(resolve_school("숙명 여고"), "숙명여자고등학교")
        self.assertEqual(self.client.delete(detail).status_code, 204)
        self.assertEqual(resolve_school("숙명여고"), "숙명여고")
