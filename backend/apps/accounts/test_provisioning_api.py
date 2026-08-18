"""계정 일괄 발급·등록 전환 API 8차 슬라이스 테스트 — PRD 3.1.5·8-3·8-4.

검증 축:
- 기능 게이트: 계정관리 키(FeatureRequired) — 조교 프리셋에 없어 403,
  delta 부여 시 허용
- 일괄 발급: 학생 User(아이디={이름}{뒷4자리}·랜덤 비번·must_change_password) +
  Student(예비등록) / parent_phone → 학부모 계정 생성(아이디=**학생 아이디+p**)·
  **중복 전화면 기존 학부모에 자녀 연결만**(ParentStudent) / **무전화 학생은
  학부모 번호 뒷4자리**(8-4 개정) / 동명이인+같은 뒷4자리는 **접미사로 해소** /
  아이디를 만들 수 없는 행(이름·번호 불량)은 **해당 행만 실패**(행 단위
  savepoint — 성공 행은 유지) / 초기 비밀번호는 응답 반환·credentials_sent_at 미스탬프
- 원번(2026-07-29 재개정): 입력이 아니라 **(이름, 휴대폰) 파생값** — 손입력
  원번은 거절, **학년은 원번에 관여하지 않는다**(없거나 못 읽어도 발급된다),
  동명이인+같은 뒷4자리 두 명은 둘 다 생성되고 **원번이 같다**(단독 UNIQUE 아님)
- 전화번호 정규화(FLOW 2-2): 저장·판정이 정규화된 값을 본다 — 엑셀이 떨어뜨린
  앞자리 0 이 복원되므로 `10…` 과 `010…` 은 같은 학생이다
- 판정 3갈래(FLOW 2-3): 셋 다 일치 → 기존 / 번호 하나만 일치 → **확인필요**
  (아무것도 만들지 않는다) / 하나도 안 맞음 → 새 학생
- 등록 전환: 예비등록→등록 + registered_at (그 외 상태 400)
- 계정 안내(FLOW 3-11 #1): 발급마다 `계정발급` 알림이 **큐에 쌓인다** —
  학생 몫 + 새 학부모 몫, 무전화 학생은 학부모가 대신 받는다
- 한글 정규화(FLOW 2-2 ①): 맥 파일의 분해형(NFD) 이름이 NFC 와 **같은
  아이디·같은 대조키**를 만들고, 같은 학생으로 판정된다
- 비밀번호 재발급(FLOW 2-4): 관리자가 임시 비밀번호를 다시 내보낸다 —
  **그 값으로 실제 로그인이 되고** 변경 강제가 다시 선다. 직원은 대상이 아니다
"""
import datetime
import json
import unicodedata

from django.test import TestCase

from apps.curriculum.models import Class, Course, CourseEnrollment
from apps.notifications.models import Notification

from .features import FeatureKey
from .models import Parent, ParentStudent, StaffFeatureGrant, Student, User

PASSWORD = "pw-Secret-77!"
BULK_URL = "/api/admin/accounts/bulk"


def make_user(login_id, role, name="사용자", **extra):
    return User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=role, **extra
    )


class ProvisioningFixtureMixin:
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("pv-own", User.Role.OWNER, name="대표")
        cls.admin = make_user("pv-adm", User.Role.ADMIN, name="관리자")
        cls.assistant = make_user("pv-ast", User.Role.ASSISTANT, name="조교")
        # 발급은 반을 골라서 한다(FLOW 2-1) — 명단에는 반이 없다.
        cls.course = Course.objects.create(name="2026 여름 N제", total_weeks=10)
        cls.klass = Class.objects.create(
            course=cls.course,
            name="목 6.5 대치러셀",
            start_date=datetime.date(2026, 9, 4),
        )

    def post_bulk(self, rows, user=None, class_id=-1):
        self.client.force_login(user or self.admin)
        body = {
            "class_id": self.klass.class_id if class_id == -1 else class_id,
            "rows": rows,
        }
        return self.client.post(
            BULK_URL, data=json.dumps(body), content_type="application/json"
        )


class BulkFeatureGateTests(ProvisioningFixtureMixin, TestCase):
    """계정관리 기능 키 게이트 — 프리셋 ⊕ delta."""

    def test_assistant_without_feature_gets_403(self):
        self.assertEqual(self.post_bulk([], user=self.assistant).status_code, 403)

    def test_assistant_with_delta_passes_gate(self):
        StaffFeatureGrant.objects.create(
            user=self.assistant,
            feature_key=FeatureKey.ACCOUNT_ADMIN,
            is_granted=True,
            granted_by=self.owner,
        )
        # 게이트는 통과하고 빈 명단 검증(400)까지 도달한다.
        self.assertEqual(self.post_bulk([], user=self.assistant).status_code, 400)

    def test_student_role_gets_403(self):
        student_user = make_user("pv-stu", User.Role.STUDENT)
        self.assertEqual(self.post_bulk([], user=student_user).status_code, 403)


class BulkIssueTests(ProvisioningFixtureMixin, TestCase):
    """POST /api/admin/accounts/bulk — 생성·연결·행 단위 실패."""

    def test_creates_student_and_parent_accounts(self):
        rows = [
            {
                "name": "김학생",
                "phone": "01011112222",
                "parent_phone": "01033334444",
                "grade": "고3",
                "school": "한종철고",
            }
        ]
        res = self.post_bulk(rows)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        result = body["results"][0]
        self.assertEqual(result["status"], "생성")
        self.assertEqual(result["login_id"], "김학생2222")

        student_user = User.objects.get(login_id="김학생2222")
        self.assertEqual(student_user.role, User.Role.STUDENT)
        self.assertEqual(student_user.name, "김학생")
        self.assertEqual(student_user.phone, "01011112222")  # 연락처는 그대로 보존
        self.assertTrue(student_user.must_change_password)
        self.assertTrue(student_user.check_password(result["initial_password"]))

        student = Student.objects.get(user=student_user)
        self.assertEqual(student.enrollment_status, Student.EnrollmentStatus.PRE_REGISTERED)
        # 원번은 파생값 — 이름 + 뒷4자리. 응답에도 실려 나간다
        # (관리자가 OMR 답안지에 적을 값이라 발급 시점에 보여야 한다).
        self.assertEqual(student.matching_key, "김학생2222")
        self.assertEqual(result["matching_key"], "김학생2222")
        self.assertEqual(student.grade, "고3")
        self.assertEqual(student.school, "한종철고")
        self.assertIsNone(student.credentials_sent_at)  # 발송은 알림톡 연동 대기

        parent = Parent.objects.get(phone="01033334444")
        self.assertIsNotNone(parent.user)
        self.assertEqual(parent.user.role, User.Role.PARENT)
        # 학부모 아이디 = 학생 아이디 + p (학부모 번호와 무관)
        self.assertEqual(parent.user.login_id, "김학생2222p")
        self.assertEqual(result["parent"]["login_id"], "김학생2222p")
        self.assertEqual(parent.user.phone, "01033334444")
        self.assertIsNone(parent.credentials_sent_at)
        self.assertTrue(result["parent"]["created"])
        self.assertTrue(parent.user.check_password(result["parent"]["initial_password"]))
        self.assertTrue(
            ParentStudent.objects.filter(parent=parent, student=student).exists()
        )

    def test_duplicate_parent_phone_links_to_existing_parent(self):
        # 학부모 번호만 겹치는 둘째는 확인필요다(FLOW 2-3) — 조교가 형제라고
        # 답한 뒤(force_new) 기존 학부모에 붙는지를 본다.
        rows = [
            {
                "name": "김첫째", "phone": "01011110001",
                "parent_phone": "01099998888", "grade": "고2",
            },
            {
                "name": "김둘째", "phone": "01011110002",
                "parent_phone": "01099998888", "grade": "고1",
                "force_new": True,
            },
        ]
        res = self.post_bulk(rows)
        body = res.json()
        self.assertEqual(Parent.objects.filter(phone="01099998888").count(), 1)
        parent = Parent.objects.get(phone="01099998888")
        self.assertEqual(ParentStudent.objects.filter(parent=parent).count(), 2)
        self.assertTrue(body["results"][0]["parent"]["created"])
        self.assertFalse(body["results"][1]["parent"]["created"])
        self.assertNotIn("initial_password", body["results"][1]["parent"])
        # 다자녀 학부모 아이디는 **최초 연결 자녀** 기준으로 고정된다(login_id 모듈 계약)
        self.assertEqual(parent.user.login_id, "김첫째0001p")
        self.assertEqual(body["results"][1]["parent"]["login_id"], "김첫째0001p")

    def test_existing_parent_in_db_gets_link_only(self):
        existing = Parent.objects.create(
            user=make_user("기존학부모0000p", User.Role.PARENT, name="기존학부모"),
            phone="01055550000",
        )
        res = self.post_bulk(
            [{
                "name": "신규생", "phone": "01055551111",
                "parent_phone": "01055550000", "grade": "고2",
            }]
        )
        body = res.json()
        self.assertFalse(body["results"][0]["parent"]["created"])
        self.assertEqual(Parent.objects.filter(phone="01055550000").count(), 1)
        student = Student.objects.get(user__login_id="신규생1111")
        self.assertTrue(
            ParentStudent.objects.filter(parent=existing, student=student).exists()
        )

    def test_phoneless_student_uses_parent_phone_tail(self):
        # 무전화 학생 — 학부모 번호 뒷4자리를 쓰고, 학부모는 그 아이디 + p
        res = self.post_bulk(
            [{"name": "무폰생", "parent_phone": "01077774821", "grade": "고2"}]
        )
        body = res.json()
        self.assertEqual(body["results"][0]["login_id"], "무폰생4821")
        self.assertEqual(body["results"][0]["parent"]["login_id"], "무폰생4821p")
        # 원번도 같은 뒷자리 규칙을 쓴다(학부모 번호 뒷4자리)
        self.assertEqual(body["results"][0]["matching_key"], "무폰생4821")
        self.assertTrue(User.objects.filter(login_id="무폰생4821").exists())
        self.assertTrue(
            User.objects.filter(login_id="무폰생4821p", role=User.Role.PARENT).exists()
        )

    def test_same_name_and_tail_gets_suffix(self):
        # 동명이인 + 같은 뒷4자리 — 실패가 아니라 접미사로 해소, 학부모도 따라간다
        rows = [
            {
                "name": "김민준", "phone": "01011111234",
                "parent_phone": "01055551111", "grade": "고2",
            },
            {
                "name": "김민준", "phone": "01022221234",
                "parent_phone": "01055552222", "grade": "고2",
            },
        ]
        res = self.post_bulk(rows)
        body = res.json()
        self.assertEqual(body["results"][0]["login_id"], "김민준1234")
        self.assertEqual(body["results"][1]["login_id"], "김민준1234a")
        self.assertEqual(body["results"][0]["parent"]["login_id"], "김민준1234p")
        self.assertEqual(body["results"][1]["parent"]["login_id"], "김민준1234ap")
        self.assertEqual(body["summary"]["created"], 2)

    def test_same_name_and_tail_share_one_matching_key(self):
        """원번은 **단독 UNIQUE 가 아니다** — 같은 이름·뒷4자리 두 명이 성립한다.

        아이디는 접미사로 갈라지지만(위 테스트) 원번은 갈리지 않는다. 겹치면
        지면 매칭에서 중복으로 떨어지고 관리자가 고른다(2026-07-29 확정).
        """
        rows = [
            {"name": "김민준", "phone": "01011111234", "grade": "고2"},
            {"name": "김민준", "phone": "01022221234", "grade": "고2"},
        ]
        res = self.post_bulk(rows)
        body = res.json()
        self.assertEqual(body["summary"]["created"], 2)
        self.assertEqual(
            [row["matching_key"] for row in body["results"]], ["김민준1234", "김민준1234"]
        )
        self.assertEqual(Student.objects.filter(matching_key="김민준1234").count(), 2)

    def test_grade_is_not_part_of_the_matching_key(self):
        """학년이 달라도 이름·뒷4자리가 같으면 원번이 같다(2026-07-29 재개정)."""
        rows = [
            {"name": "동명이", "phone": "01011110001", "grade": "고1"},
            {"name": "동명이", "phone": "01022220001", "grade": "고3"},
        ]
        body = self.post_bulk(rows).json()
        self.assertEqual(body["results"][0]["matching_key"], "동명이0001")
        self.assertEqual(body["results"][1]["matching_key"], "동명이0001")

    def test_supplied_matching_key_rejected(self):
        """손입력 원번은 **행 실패**다 — 무시하면 준 값이 저장됐다고 오해한다.

        원번이 파생값이 된 뒤 입력칸은 사라졌다(AccountsPage). 옛 서식이 그대로
        들어오면 조용히 다른 값이 저장되는 대신 그 행만 사유와 함께 실패한다.
        """
        rows = [
            {
                "name": "손입력", "phone": "01011110001",
                "grade": "고2", "matching_key": "26901",
            },
            {"name": "정상생", "phone": "01011110002", "grade": "고2"},
        ]
        body = self.post_bulk(rows).json()
        self.assertEqual(body["results"][0]["status"], "실패")
        self.assertIn("원번", body["results"][0]["error"])
        self.assertFalse(User.objects.filter(name="손입력").exists())
        self.assertEqual(body["results"][1]["status"], "생성")
        self.assertEqual(body["summary"], {
            "created": 1, "existing": 0, "needs_review": 0, "failed": 1,
            "parents_created": 0, "parents_linked": 0,
        })

    def test_row_without_grade_is_issued(self):
        """학년이 비어도 발급된다 — 원번의 재료가 아니게 됐다(2026-07-29 재개정).

        학년은 학생 정보로 계속 쓰지만(승급·명단) 계정 발급을 막을 이유가 없다.
        비면 그대로 빈 문자열로 저장되고 승급 커맨드가 건너뛰며 드러난다.
        """
        body = self.post_bulk([{"name": "무학년", "phone": "01011110001"}]).json()
        self.assertEqual(body["results"][0]["status"], "생성")
        self.assertEqual(body["results"][0]["matching_key"], "무학년0001")
        self.assertEqual(Student.objects.get(user__name="무학년").grade, "")

    def test_free_form_grade_is_stored_as_is(self):
        """학년 표기는 원번에 관여하지 않으므로 파싱하지 않는다 — 적힌 대로 저장."""
        body = self.post_bulk(
            [
                {"name": "엔수생", "phone": "01011110001", "grade": "N수"},
                {"name": "미상생", "phone": "01011110002", "grade": "고등부"},
            ]
        ).json()
        self.assertEqual(
            [row["status"] for row in body["results"]], ["생성", "생성"]
        )
        self.assertEqual(body["results"][0]["matching_key"], "엔수생0001")
        self.assertEqual(Student.objects.get(user__name="미상생").grade, "고등부")

    def test_name_with_spaces_normalized(self):
        res = self.post_bulk(
            [{"name": " 김 하늘 ", "phone": "010-1111-4821", "grade": "고2"}]
        )
        self.assertEqual(res.json()["results"][0]["login_id"], "김하늘4821")

    def test_unusable_name_fails_only_that_row(self):
        rows = [
            {"name": "!!!", "phone": "01088880000", "grade": "고2"},
            {"name": "정상생", "phone": "01088880001", "grade": "고2"},
        ]
        res = self.post_bulk(rows)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["results"][0]["status"], "실패")
        self.assertTrue(body["results"][0]["error"])
        self.assertEqual(body["results"][1]["status"], "생성")
        # 실패 행 잔재 없음(행 단위 savepoint 롤백) — 성공 행은 유지.
        self.assertFalse(Student.objects.filter(user__phone="01088880000").exists())
        self.assertTrue(Student.objects.filter(user__login_id="정상생0001").exists())
        self.assertEqual(body["summary"]["created"], 1)
        self.assertEqual(body["summary"]["failed"], 1)

    def test_row_without_any_phone_fails_that_row(self):
        res = self.post_bulk([{"name": "무연락생", "grade": "고2"}])
        body = res.json()
        self.assertEqual(body["results"][0]["status"], "실패")

    def test_row_with_short_phone_fails_that_row(self):
        res = self.post_bulk([{"name": "짧은번호", "phone": "12", "grade": "고2"}])
        body = res.json()
        self.assertEqual(body["results"][0]["status"], "실패")
        self.assertFalse(User.objects.filter(name="짧은번호").exists())

    def test_row_without_name_fails_that_row(self):
        res = self.post_bulk([{"phone": "01012340000", "grade": "고2"}])
        body = res.json()
        self.assertEqual(body["results"][0]["status"], "실패")
        self.assertFalse(User.objects.filter(phone="01012340000").exists())

    def test_non_list_or_empty_body_rejected(self):
        self.assertEqual(self.post_bulk({"name": "딕셔너리"}).status_code, 400)
        self.assertEqual(self.post_bulk([]).status_code, 400)

    def test_unknown_or_missing_class_rejected(self):
        rows = [{"name": "반없음", "phone": "01055550000"}]
        self.assertEqual(self.post_bulk(rows, class_id=None).status_code, 400)
        self.assertEqual(self.post_bulk(rows, class_id=999999).status_code, 400)
        self.assertFalse(User.objects.filter(phone="01055550000").exists())


class BulkEnrollmentTests(ProvisioningFixtureMixin, TestCase):
    """발급이 학생을 **반에 넣는다** — FLOW 2-1·2-4."""

    def test_issued_student_is_enrolled_in_the_chosen_class(self):
        res = self.post_bulk([{"name": "박서준", "phone": "01033330001"}])
        student_id = res.json()["results"][0]["student_id"]
        enrollment = CourseEnrollment.objects.get(student_id=student_id)
        self.assertEqual(enrollment.klass_id, self.klass.class_id)
        self.assertEqual(enrollment.course_id, self.course.course_id)
        # 요일은 개강일에서 얻는다(FLOW 1-2) — 2026-09-04 는 금요일(0=일…6=토)
        self.assertEqual(enrollment.primary_weekday, 5)

    def test_existing_account_gets_enrollment_only(self):
        first = self.post_bulk([{"name": "최유진", "phone": "01033330002"}]).json()
        student_id = first["results"][0]["student_id"]

        again = self.post_bulk([{"name": "최유진", "phone": "01033330002"}]).json()
        row = again["results"][0]
        self.assertEqual(row["status"], "기존")
        self.assertEqual(row["student_id"], student_id)
        self.assertNotIn("initial_password", row)  # 안내가 안 나간다(FLOW 2-4)
        self.assertEqual(again["summary"], {**again["summary"], "created": 0, "existing": 1})
        self.assertEqual(User.objects.filter(phone="01033330002").count(), 1)
        self.assertEqual(CourseEnrollment.objects.filter(student_id=student_id).count(), 1)

    def test_existing_account_in_another_class_adds_a_second_enrollment(self):
        first = self.post_bulk([{"name": "정하윤", "phone": "01033330003"}]).json()
        student_id = first["results"][0]["student_id"]
        other = Class.objects.create(
            course=Course.objects.create(name="내신 파이널", total_weeks=6),
            name="화 8.0 대치러셀",
            start_date=datetime.date(2026, 9, 1),
        )

        again = self.post_bulk(
            [{"name": "정하윤", "phone": "01033330003"}], class_id=other.class_id
        ).json()
        self.assertEqual(again["results"][0]["status"], "기존")
        self.assertEqual(
            sorted(
                CourseEnrollment.objects.filter(student_id=student_id).values_list(
                    "klass_id", flat=True
                )
            ),
            sorted([self.klass.class_id, other.class_id]),
        )
        self.assertEqual(Student.objects.filter(user__phone="01033330003").count(), 1)

    def test_phoneless_student_is_matched_by_parent_phone_and_name(self):
        first = self.post_bulk(
            [{"name": "한지우", "parent_phone": "01044440001"}]
        ).json()
        student_id = first["results"][0]["student_id"]

        again = self.post_bulk([{"name": "한지우", "parent_phone": "01044440001"}]).json()
        self.assertEqual(again["results"][0]["status"], "기존")
        self.assertEqual(again["results"][0]["student_id"], student_id)

    def test_sibling_sharing_a_parent_phone_is_asked_about(self):
        """형제는 묻는다(FLOW 2-3) — 형제일 수도, 남의 번호를 잘못 적었을 수도."""
        self.post_bulk([{"name": "한지우", "parent_phone": "01044440002"}])
        res = self.post_bulk([{"name": "한지호", "parent_phone": "01044440002"}]).json()
        self.assertEqual(res["results"][0]["status"], "확인필요")
        self.assertEqual(Student.objects.filter(user__name__startswith="한지").count(), 1)

    def test_sibling_confirmed_as_new_joins_the_same_parent(self):
        """조교가 형제라고 답하면 **먼저 만들어진 학부모 계정에 붙는다**(FLOW 2-4)."""
        self.post_bulk([{"name": "한지우", "parent_phone": "01044440003"}])
        res = self.post_bulk(
            [{"name": "한지호", "parent_phone": "01044440003", "force_new": True}]
        ).json()
        self.assertEqual(res["results"][0]["status"], "생성")
        self.assertFalse(res["results"][0]["parent"]["created"])
        self.assertEqual(Parent.objects.filter(phone="01044440003").count(), 1)
        self.assertEqual(Student.objects.filter(user__name__startswith="한지").count(), 2)


class BulkPhoneNormalizationTests(ProvisioningFixtureMixin, TestCase):
    """저장도 판정도 정규화된 번호를 본다 — FLOW 2-2."""

    def test_stored_phone_is_normalized(self):
        self.post_bulk(
            [{"name": "정규화", "phone": "010-1111-4821", "parent_phone": "+82 10-9999-0000"}]
        )
        student = Student.objects.get(user__login_id="정규화4821")
        self.assertEqual(student.user.phone, "01011114821")
        self.assertEqual(Parent.objects.get().phone, "01099990000")

    def test_excel_dropped_leading_zero_is_the_same_student(self):
        """엑셀이 숫자로 읽어 `010…` 이 `10…` 으로 온 파일 — 둘로 갈리면 안 된다."""
        first = self.post_bulk([{"name": "엑셀생", "phone": "01011114822"}]).json()
        again = self.post_bulk([{"name": "엑셀생", "phone": "1011114822"}]).json()
        self.assertEqual(again["results"][0]["status"], "기존")
        self.assertEqual(again["results"][0]["student_id"], first["results"][0]["student_id"])
        self.assertEqual(Student.objects.filter(user__name="엑셀생").count(), 1)


class BulkMatchVerdictTests(ProvisioningFixtureMixin, TestCase):
    """번호 3갈래 판정 — FLOW 2-3."""

    def seed(self):
        return self.post_bulk(
            [{"name": "원학생", "phone": "01012340001", "parent_phone": "01098760001"}]
        ).json()["results"][0]

    def test_all_three_match_passes(self):
        first = self.seed()
        again = self.post_bulk(
            [{"name": "원학생", "phone": "01012340001", "parent_phone": "01098760001"}]
        ).json()
        self.assertEqual(again["results"][0]["status"], "기존")
        self.assertEqual(again["results"][0]["student_id"], first["student_id"])
        self.assertEqual(again["summary"]["existing"], 1)

    def test_one_number_matching_asks(self):
        self.seed()
        # 학생번호 오타 — 학부모번호만 맞는다
        body = self.post_bulk(
            [{"name": "원학생", "phone": "01012340009", "parent_phone": "01098760001"}]
        ).json()
        row = body["results"][0]
        self.assertEqual(row["status"], "확인필요")
        self.assertEqual(body["summary"]["needs_review"], 1)
        # 조교가 오타인지 형제인지 가릴 값이 실려 온다
        self.assertEqual(
            [(m["name"], m["login_id"], m["phone"], m["parent_phone"]) for m in row["matched"]],
            [("원학생", "원학생0001", "01012340001", "01098760001")],
        )

    def test_both_numbers_match_but_name_differs_asks(self):
        """이름 오타 — 번호가 둘 다 맞아도 이름이 다르면 묻는다(FLOW 2-3 표)."""
        self.seed()
        body = self.post_bulk(
            [{"name": "원핵생", "phone": "01012340001", "parent_phone": "01098760001"}]
        ).json()
        self.assertEqual(body["results"][0]["status"], "확인필요")

    def test_no_number_matches_is_a_new_student(self):
        """동명이인 — 번호가 하나도 안 맞으면 묻지 않는다."""
        self.seed()
        body = self.post_bulk(
            [{"name": "원학생", "phone": "01055550001", "parent_phone": "01055550002"}]
        ).json()
        self.assertEqual(body["results"][0]["status"], "생성")
        self.assertEqual(Student.objects.filter(user__name="원학생").count(), 2)

    def test_needs_review_row_creates_nothing(self):
        """확인필요는 **PK 가 할당되지 않는다**(FLOW 2-3) — 반쪽 계정을 남기지 않는다."""
        self.seed()
        before = (User.objects.count(), Student.objects.count(), CourseEnrollment.objects.count())
        body = self.post_bulk(
            [{"name": "원학생", "phone": "01012340009", "parent_phone": "01098760001"}]
        ).json()
        row = body["results"][0]
        self.assertEqual(row["status"], "확인필요")
        self.assertNotIn("login_id", row)
        self.assertNotIn("initial_password", row)
        self.assertNotIn("student_id", row)
        self.assertEqual(
            (User.objects.count(), Student.objects.count(), CourseEnrollment.objects.count()),
            before,
        )

    def test_confirming_same_person_adds_the_enrollment_only(self):
        first = self.seed()
        other = Class.objects.create(
            course=self.course, name="금 6.5 대치러셀", start_date=datetime.date(2026, 9, 5)
        )
        before = User.objects.count()
        body = self.post_bulk(
            [{
                "name": "원학생", "phone": "01012340009",
                "parent_phone": "01098760001",
                "same_as_student_id": first["student_id"],
            }],
            class_id=other.class_id,
        ).json()
        row = body["results"][0]
        self.assertEqual(row["status"], "기존")
        self.assertEqual(row["student_id"], first["student_id"])
        self.assertEqual(User.objects.count(), before)
        self.assertEqual(
            CourseEnrollment.objects.filter(student_id=first["student_id"]).count(), 2
        )

    def test_confirming_a_missing_student_fails_that_row(self):
        self.seed()
        body = self.post_bulk(
            [{
                "name": "원학생", "phone": "01012340009",
                "parent_phone": "01098760001", "same_as_student_id": 999999,
            }]
        ).json()
        self.assertEqual(body["results"][0]["status"], "실패")

    def test_forcing_new_creates_a_separate_student(self):
        self.seed()
        body = self.post_bulk(
            [{
                "name": "원학생", "phone": "01012340009",
                "parent_phone": "01098760001", "force_new": True,
            }]
        ).json()
        self.assertEqual(body["results"][0]["status"], "생성")
        self.assertEqual(Student.objects.filter(user__name="원학생").count(), 2)


class RegisterTests(ProvisioningFixtureMixin, TestCase):
    """POST /api/admin/accounts/{student_id}/register — 예비등록→등록."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.student = Student.objects.create(
            user=make_user("rg-stu", User.Role.STUDENT, name="예비생"),
            matching_key="예비생0001",
        )

    def register(self, student_id, user=None):
        self.client.force_login(user or self.admin)
        return self.client.post(f"/api/admin/accounts/{student_id}/register")

    def test_registers_pre_registered_student(self):
        res = self.register(self.student.student_id)
        self.assertEqual(res.status_code, 200)
        self.student.refresh_from_db()
        self.assertEqual(self.student.enrollment_status, Student.EnrollmentStatus.REGISTERED)
        self.assertIsNotNone(self.student.registered_at)
        self.assertEqual(res.json()["enrollment_status"], "등록")

    def test_already_registered_rejected(self):
        self.register(self.student.student_id)
        self.assertEqual(self.register(self.student.student_id).status_code, 400)

    def test_withdrawn_rejected(self):
        self.student.enrollment_status = Student.EnrollmentStatus.WITHDRAWN
        self.student.save(update_fields=["enrollment_status"])
        self.assertEqual(self.register(self.student.student_id).status_code, 400)

    def test_unknown_student_404(self):
        self.assertEqual(self.register(999999).status_code, 404)

    def test_assistant_without_feature_gets_403(self):
        self.assertEqual(
            self.register(self.student.student_id, user=self.assistant).status_code, 403
        )


class BulkCredentialNotificationTests(ProvisioningFixtureMixin, TestCase):
    """발급 → 계정 안내가 큐에 쌓인다(FLOW 3-11 #1).

    **발송은 아직 안 된다** — 템플릿 승인 전이라(8-17) 행만 쌓이고, 승인분이
    들어오면 설정만 채워도 그대로 나간다. 여기서 보는 것은 "걸렸는가"다.
    """

    def issued(self):
        return Notification.objects.filter(type=Notification.Type.ACCOUNT_ISSUED)

    def test_student_and_new_parent_each_get_one(self):
        res = self.post_bulk(
            [{"name": "김학생", "phone": "01011112222", "parent_phone": "01033334444"}]
        )
        result = res.json()["results"][0]
        student = Student.objects.get(user__login_id="김학생2222")
        parent = Parent.objects.get(phone="01033334444")

        self.assertEqual(self.issued().count(), 2)
        to_student = self.issued().get(student=student)
        self.assertEqual(to_student.status, Notification.Status.PENDING)  # 발송은 커밋 뒤
        self.assertEqual(to_student.channel, Notification.Channel.KAKAO)
        self.assertIn("김학생2222", to_student.body)
        self.assertIn(result["initial_password"], to_student.body)
        to_parent = self.issued().get(parent=parent)
        self.assertIn("김학생2222p", to_parent.body)
        self.assertIn(result["parent"]["initial_password"], to_parent.body)

    def test_phoneless_student_credentials_go_to_the_parent(self):
        # 학생 번호가 없으면 학생 계정 안내까지 학부모 번호로 나간다(FLOW 2-4).
        self.post_bulk([{"name": "무전화", "parent_phone": "01055556666"}])
        parent = Parent.objects.get(phone="01055556666")
        self.assertEqual(self.issued().count(), 2)
        self.assertEqual(self.issued().filter(student__isnull=False).count(), 0)
        self.assertEqual(self.issued().filter(parent=parent).count(), 2)

    def test_existing_student_gets_no_notice(self):
        # 계정은 한 번 만들면 끝이다 — 재업로드에 안내가 다시 나가면 안 된다.
        row = {"name": "김학생", "phone": "01011112222", "parent_phone": "01033334444"}
        self.post_bulk([row])
        self.assertEqual(self.issued().count(), 2)
        self.assertEqual(self.post_bulk([row]).json()["results"][0]["status"], "기존")
        self.assertEqual(self.issued().count(), 2)

    def test_second_child_does_not_renotify_the_parent(self):
        # 둘째는 연결만 된다 — 학부모 아이디가 그대로라 보낼 것이 없다.
        self.post_bulk([{"name": "첫째", "phone": "01011112222", "parent_phone": "01033334444"}])
        self.post_bulk(
            [
                {
                    "name": "둘째",
                    "phone": "01099998888",
                    "parent_phone": "01033334444",
                    "force_new": True,
                }
            ]
        )
        parent = Parent.objects.get(phone="01033334444")
        self.assertEqual(self.issued().filter(parent=parent).count(), 1)


class BulkNameNormalizationTests(ProvisioningFixtureMixin, TestCase):
    """맥에서 만든 파일의 분해형 한글(FLOW 2-2 ①)."""

    NFD_NAME = unicodedata.normalize("NFD", "김서연")

    def test_decomposed_name_makes_the_same_login_id_and_key(self):
        res = self.post_bulk([{"name": self.NFD_NAME, "phone": "01012341234"}])
        result = res.json()["results"][0]
        self.assertEqual(result["status"], "생성")
        self.assertEqual(result["login_id"], "김서연1234")
        self.assertEqual(result["matching_key"], "김서연1234")
        # 저장된 이름도 합쳐진 값이다 — 화면·검색이 NFC 로 도는데 이 행만
        # 분해형이면 이름으로 찾지 못한다.
        self.assertEqual(User.objects.get(login_id="김서연1234").name, "김서연")

    def test_reupload_in_the_other_form_is_the_same_student(self):
        # 1차 NFC · 2차 NFD 로 같은 명단이 올라와도 이름 비교가 어긋나지 않는다
        # (어긋나면 전 행이 확인필요로 서고 아무것도 진행되지 않는다).
        row = {"name": "김서연", "phone": "01012341234", "parent_phone": "01043214321"}
        self.assertEqual(self.post_bulk([row]).json()["results"][0]["status"], "생성")
        again = self.post_bulk([{**row, "name": self.NFD_NAME}]).json()["results"][0]
        self.assertEqual(again["status"], "기존")
        self.assertEqual(Student.objects.filter(matching_key="김서연1234").count(), 1)


class PasswordResetTests(ProvisioningFixtureMixin, TestCase):
    """POST /api/admin/accounts/{user_id}/password — 잊은 사람을 사람이 되돌린다."""

    def setUp(self):
        self.post_bulk(
            [{"name": "김학생", "phone": "01011112222", "parent_phone": "01033334444"}]
        )
        self.student_user = User.objects.get(login_id="김학생2222")
        self.parent_user = User.objects.get(login_id="김학생2222p")

    def reset(self, user_id, user=None):
        self.client.force_login(user or self.admin)
        return self.client.post(f"/api/admin/accounts/{user_id}/password")

    def test_new_password_actually_logs_in(self):
        res = self.reset(self.student_user.user_id)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["login_id"], "김학생2222")

        self.client.logout()
        signed_in = self.client.post(
            "/api/auth/login",
            data=json.dumps({"login_id": "김학생2222", "password": body["initial_password"]}),
            content_type="application/json",
        )
        self.assertEqual(signed_in.status_code, 200)

    def test_reset_forces_the_change_again(self):
        # 임시 비밀번호가 영구 비밀번호로 굳으면 안 된다.
        self.student_user.must_change_password = False
        self.student_user.save(update_fields=["must_change_password"])
        self.reset(self.student_user.user_id)
        self.student_user.refresh_from_db()
        self.assertTrue(self.student_user.must_change_password)

    def test_old_password_stops_working(self):
        self.reset(self.student_user.user_id)
        self.client.logout()
        stale = self.client.post(
            "/api/auth/login",
            data=json.dumps({"login_id": "김학생2222", "password": PASSWORD}),
            content_type="application/json",
        )
        self.assertEqual(stale.status_code, 401)

    def test_reset_notifies_the_owner_of_the_account(self):
        before = Notification.objects.filter(type=Notification.Type.ACCOUNT_ISSUED).count()
        res = self.reset(self.parent_user.user_id)
        notif = Notification.objects.filter(type=Notification.Type.ACCOUNT_ISSUED).last()
        self.assertEqual(
            Notification.objects.filter(type=Notification.Type.ACCOUNT_ISSUED).count(),
            before + 1,
        )
        self.assertEqual(notif.parent, Parent.objects.get(phone="01033334444"))
        self.assertIn(res.json()["initial_password"], notif.body)

    def test_staff_account_is_not_resettable(self):
        # 계정관리 키를 받은 조교가 대표 비밀번호를 갈아 끼우는 길을 막는다.
        self.assertEqual(self.reset(self.owner.user_id).status_code, 404)

    def test_unknown_user_404(self):
        self.assertEqual(self.reset(999999).status_code, 404)

    def test_assistant_without_feature_gets_403(self):
        self.assertEqual(
            self.reset(self.student_user.user_id, user=self.assistant).status_code, 403
        )
