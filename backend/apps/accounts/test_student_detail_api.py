"""학생 상세·수정 API 테스트 — GET·PATCH /api/admin/students/{id} (FLOW 2-5·2-6).

검증 축:
- 게이트: **계정관리 기능 키** — 목록(직원 공통)과 다르다. 응답이 연락처를 싣고
  수정이 아이디·비밀번호를 다시 만들기 때문(뷰 docstring). 프리셋에 없는 조교는
  403, delta 를 받으면 통과. 학생·학부모·비로그인은 403
- 상세: FLOW 2-6 이 한 화면에 모으라고 한 것들(이름·학교·학년·번호·대조키·
  아이디·구입한 교재·발송 내역·듣는 반) + **학부모 앞 발송도 함께** 보인다
- 수정: 학교·학년만 고치면 아무것도 다시 만들지 않는다 / **번호·이름이 바뀌면
  대조키·아이디·비밀번호가 다시 만들어지고 안내가 다시 나간다**
- **옛 발송 행은 옛 번호를 그대로 든다**(sent_to_phone 스냅샷)
- **이미 낸 답안지는 흔들리지 않는다** — 학생 연결도 지면에서 읽은 값도 그대로
- 학부모 번호 정정: 제자리 수정 + 계정 안내 재발송 / 그 번호를 이미 쓰는
  학부모가 있으면 **새로 만들지 않고 그쪽으로 옮긴다**(형제)
"""
import json

from django.test import TestCase, override_settings

from apps.curriculum.models import Class, Course, CourseEnrollment
from apps.grades.models import AnswerSheet, Exam
from apps.notifications.models import Notification
from apps.notifications.sending import deliver
from apps.payments.models import Order, Product

from .features import FeatureKey
from .models import Parent, ParentStudent, StaffFeatureGrant, Student, User

PASSWORD = "pw-Secret-77!"
FAKE = "apps.notifications.channels.FakeChannelAdapter"
ALL_FAKE = {"카카오알림톡": FAKE, "문자": FAKE, "앱푸시": FAKE}


def make_user(login_id, role, name="사용자", **extra):
    return User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=role, **extra
    )


class StudentDetailFixtureMixin:
    """학생 1명(학부모·수강·주문·발송 각 1건) + 역할별 계정."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("sd-own", User.Role.OWNER, name="대표")
        cls.admin = make_user("sd-adm", User.Role.ADMIN, name="관리자")
        cls.assistant = make_user("sd-ast", User.Role.ASSISTANT, name="조교")

        cls.student_user = make_user(
            "김하늘1111", User.Role.STUDENT, name="김하늘", phone="01000001111"
        )
        cls.student = Student.objects.create(
            user=cls.student_user, matching_key="김하늘1111", grade="고2", school="세화고"
        )
        cls.parent_user = make_user(
            "김하늘1111p", User.Role.PARENT, name="김하늘 학부모", phone="01000002222"
        )
        cls.parent = Parent.objects.create(user=cls.parent_user, phone="01000002222")
        ParentStudent.objects.create(parent=cls.parent, student=cls.student)

        cls.course = Course.objects.create(name="2026 여름 N제")
        cls.klass = Class.objects.create(course=cls.course, name="목 6.5 대치러셀")
        CourseEnrollment.objects.create(
            student=cls.student, course=cls.course, klass=cls.klass
        )

        cls.product = Product.objects.create(name="여름 N제 교재", price=30000, course=cls.course)
        Order.objects.create(
            student=cls.student,
            product=cls.product,
            amount=30000,
            billed_to_parent=cls.parent,
            billed_to_phone="01000002222",
        )

        # 학생·학부모 각 1건 — 상세는 둘 다 보여야 한다(FLOW 2-5).
        cls.student_notif = Notification.objects.create(
            student=cls.student,
            channel=Notification.Channel.KAKAO,
            type=Notification.Type.ACCOUNT_ISSUED,
            body="김하늘 아이디 김하늘1111",
        )
        cls.parent_notif = Notification.objects.create(
            parent=cls.parent,
            channel=Notification.Channel.KAKAO,
            type=Notification.Type.PAYMENT,
            body="교재 청구",
        )

    def url(self, student_id=None):
        return f"/api/admin/students/{student_id or self.student.student_id}"

    def get_detail(self, user=None, student_id=None):
        self.client.force_login(user or self.admin)
        return self.client.get(self.url(student_id))

    def patch_student(self, body, user=None, student_id=None):
        self.client.force_login(user or self.admin)
        return self.client.patch(
            self.url(student_id), data=json.dumps(body), content_type="application/json"
        )


class StudentDetailGateTests(StudentDetailFixtureMixin, TestCase):
    """계정관리 기능 키 — 목록의 직원 공통 게이트와 다르다."""

    def test_admin_and_owner_pass(self):
        self.assertEqual(self.get_detail(self.admin).status_code, 200)
        self.assertEqual(self.get_detail(self.owner).status_code, 200)

    def test_assistant_without_feature_is_denied(self):
        self.assertEqual(self.get_detail(self.assistant).status_code, 403)
        self.assertEqual(
            self.patch_student({"school": "휘문고"}, user=self.assistant).status_code, 403
        )

    def test_assistant_with_delta_passes(self):
        StaffFeatureGrant.objects.create(
            user=self.assistant, feature_key=FeatureKey.ACCOUNT_ADMIN, is_granted=True
        )
        self.assertEqual(self.get_detail(self.assistant).status_code, 200)

    def test_consumers_are_denied(self):
        self.assertEqual(self.get_detail(self.student_user).status_code, 403)
        self.assertEqual(self.get_detail(self.parent_user).status_code, 403)
        self.assertEqual(
            self.patch_student({"school": "휘문고"}, user=self.student_user).status_code, 403
        )

    def test_anonymous_is_denied(self):
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(
            self.client.patch(
                self.url(), data="{}", content_type="application/json"
            ).status_code,
            403,
        )

    def test_unknown_student_is_404(self):
        self.assertEqual(self.get_detail(student_id=999999).status_code, 404)
        self.assertEqual(
            self.patch_student({"school": "휘문고"}, student_id=999999).status_code, 404
        )


class StudentDetailReadTests(StudentDetailFixtureMixin, TestCase):
    """FLOW 2-6 이 상세에 있어야 한다고 적은 것들."""

    def test_detail_carries_the_fields_flow_asks_for(self):
        body = self.get_detail().json()

        self.assertEqual(body["name"], "김하늘")
        self.assertEqual(body["school"], "세화고")
        self.assertEqual(body["grade"], "고2")
        self.assertEqual(body["phone"], "01000001111")
        self.assertEqual(body["matching_key"], "김하늘1111")
        self.assertEqual(body["login_id"], "김하늘1111")
        self.assertEqual([p["phone"] for p in body["parents"]], ["01000002222"])
        self.assertEqual([c["class_name"] for c in body["classes"]], ["목 6.5 대치러셀"])
        self.assertEqual([o["product_name"] for o in body["orders"]], ["여름 N제 교재"])

    def test_notifications_include_the_ones_sent_to_the_parent(self):
        # 번호 없는 학생의 계정 안내는 학부모에게 간다 — 학생 행만 보면 빠진다.
        ids = {row["notif_id"] for row in self.get_detail().json()["notifications"]}
        self.assertEqual(ids, {self.student_notif.notif_id, self.parent_notif.notif_id})


class StudentUpdateTests(StudentDetailFixtureMixin, TestCase):
    """수정 — 무엇이 다시 만들어지고 무엇이 그대로인가."""

    def test_school_and_grade_do_not_reissue_anything(self):
        body = self.patch_student({"school": "휘문고", "grade": "고3"}).json()

        self.student.refresh_from_db()
        self.student_user.refresh_from_db()
        self.assertEqual(self.student.school, "휘문고")
        self.assertEqual(self.student.grade, "고3")
        self.assertEqual(self.student.matching_key, "김하늘1111")
        self.assertEqual(self.student_user.login_id, "김하늘1111")
        self.assertIsNone(body["initial_password"])

    def test_phone_correction_reissues_key_login_id_and_password(self):
        old_hash = self.student_user.password

        body = self.patch_student({"phone": "01000009999"}).json()

        self.student.refresh_from_db()
        self.student_user.refresh_from_db()
        self.assertEqual(self.student.matching_key, "김하늘9999")
        self.assertEqual(self.student_user.login_id, "김하늘9999")
        self.assertEqual(self.student_user.phone, "01000009999")
        self.assertNotEqual(self.student_user.password, old_hash)
        self.assertTrue(self.student_user.must_change_password)
        self.assertEqual(body["login_id"], "김하늘9999")
        self.assertTrue(body["initial_password"])

    def test_reissue_queues_the_credential_notice_again(self):
        before = Notification.objects.filter(type=Notification.Type.ACCOUNT_ISSUED).count()

        self.patch_student({"phone": "01000009999"})

        latest = (
            Notification.objects.filter(type=Notification.Type.ACCOUNT_ISSUED)
            .order_by("-notif_id")
            .first()
        )
        self.assertEqual(
            Notification.objects.filter(type=Notification.Type.ACCOUNT_ISSUED).count(),
            before + 1,
        )
        self.assertIn("김하늘9999", latest.body)

    def test_name_typo_also_reissues(self):
        # 대조키가 {이름}{뒷4자리} 라 이름 오타도 아이디의 근거를 바꾼다.
        self.patch_student({"name": "김하늘아"})

        self.student.refresh_from_db()
        self.student_user.refresh_from_db()
        self.assertEqual(self.student.matching_key, "김하늘아1111")
        self.assertEqual(self.student_user.login_id, "김하늘아1111")

    def test_login_id_takes_a_suffix_when_the_new_one_is_taken(self):
        make_user("김하늘9999", User.Role.STUDENT, name="김하늘", phone="01000009999")

        self.patch_student({"phone": "01000009999"})

        self.student.refresh_from_db()
        self.student_user.refresh_from_db()
        # 대조키는 겹쳐도 된다(지면 대조 전용) — 아이디만 접미사로 갈린다.
        self.assertEqual(self.student.matching_key, "김하늘9999")
        self.assertEqual(self.student_user.login_id, "김하늘9999a")

    @override_settings(NOTIFICATION_CHANNEL_BACKENDS=ALL_FAKE)
    def test_past_notifications_keep_the_number_they_went_to(self):
        # 이것이 FLOW 3-8 이 요구한 것 — 번호를 고쳐도 옛 발송은 옛 번호를 든다.
        deliver(self.student_notif.notif_id)

        self.patch_student({"phone": "01000009999"})

        self.student_notif.refresh_from_db()
        self.assertEqual(self.student_notif.sent_to_phone, "01000001111")
        rows = {
            row["notif_id"]: row["sent_to_phone"]
            for row in self.get_detail().json()["notifications"]
        }
        self.assertEqual(rows[self.student_notif.notif_id], "01000001111")

    def test_submitted_answer_sheets_are_not_touched(self):
        exam = Exam.objects.create(name="1주차 모의고사", exam_date="2026-09-04")
        sheet = AnswerSheet.objects.create(
            exam=exam,
            student=self.student,
            recognized_matching_key="김하늘1111",
            recognized_name="김하늘",
            match_status=AnswerSheet.MatchStatus.MATCHED,
        )

        self.patch_student({"phone": "01000009999"})

        sheet.refresh_from_db()
        # 대조는 낼 때 이미 끝난 일이다(FLOW 2-6) — 연결도 읽은 값도 그대로다.
        self.assertEqual(sheet.student_id, self.student.student_id)
        self.assertEqual(sheet.recognized_matching_key, "김하늘1111")
        self.assertEqual(sheet.match_status, AnswerSheet.MatchStatus.MATCHED)

    def test_enrollment_and_orders_survive(self):
        self.patch_student({"phone": "01000009999"})

        self.assertEqual(CourseEnrollment.objects.filter(student=self.student).count(), 1)
        # 이미 나간 청구는 그때 번호 그대로다(스냅샷).
        self.assertEqual(
            Order.objects.get(student=self.student).billed_to_phone, "01000002222"
        )

    def test_parent_phone_correction_resends_that_parents_credentials(self):
        old_hash = self.parent_user.password

        body = self.patch_student({"parent_phone": "010-0000-3333"}).json()

        self.parent.refresh_from_db()
        self.parent_user.refresh_from_db()
        self.assertEqual(self.parent.phone, "01000003333")
        self.assertEqual(self.parent_user.phone, "01000003333")
        self.assertNotEqual(self.parent_user.password, old_hash)
        self.assertTrue(body["parent_initial_password"])
        # 학생 번호는 그대로라 학생 아이디는 움직이지 않는다.
        self.assertEqual(body["login_id"], "김하늘1111")

    def test_parent_phone_moves_to_the_parent_that_already_has_it(self):
        # 형제가 먼저 등록해 둔 경우 — 한 번호에 학부모 계정이 둘 생기면 안 된다.
        sibling_parent = Parent.objects.create(
            user=make_user("이바다2222p", User.Role.PARENT, name="이바다 학부모"),
            phone="01000004444",
        )

        self.patch_student({"parent_phone": "01000004444"})

        links = ParentStudent.objects.filter(student=self.student)
        self.assertEqual([link.parent_id for link in links], [sibling_parent.parent_id])
        self.assertEqual(Parent.objects.filter(phone="01000004444").count(), 1)
        # 그 계정의 안내는 이미 맞는 번호로 나갔다 — 다시 보내지 않는다.
        self.assertIsNone(
            self.patch_student({"parent_phone": "01000004444"}).json()[
                "parent_initial_password"
            ]
        )

    def test_phoneless_student_takes_the_tail_from_the_corrected_parent_number(self):
        self.student_user.phone = ""
        self.student_user.save(update_fields=["phone"])

        self.patch_student({"parent_phone": "01000005555"})

        self.student.refresh_from_db()
        self.student_user.refresh_from_db()
        self.assertEqual(self.student.matching_key, "김하늘5555")
        self.assertEqual(self.student_user.login_id, "김하늘5555")

    def test_rejects_empty_body_and_non_string_values(self):
        self.assertEqual(self.patch_student({}).status_code, 400)
        self.assertEqual(self.patch_student({"phone": 1000009999}).status_code, 400)
        self.assertEqual(self.patch_student({"student_id": "3"}).status_code, 400)

    def test_rejects_clearing_the_only_number(self):
        # 학부모도 없는데 학생 번호까지 비우면 아이디를 만들 근거가 사라진다.
        alone_user = make_user("이바다2222", User.Role.STUDENT, name="이바다", phone="01000002222")
        alone = Student.objects.create(user=alone_user, matching_key="이바다2222")

        response = self.patch_student({"phone": ""}, student_id=alone.student_id)

        self.assertEqual(response.status_code, 400)
        alone_user.refresh_from_db()
        self.assertEqual(alone_user.phone, "01000002222")
