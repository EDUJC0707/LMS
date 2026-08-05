"""클리닉 관리자 API 8차 슬라이스 테스트 — PRD 3.2.4 관리자 측 결정 강제.

검증 축:
- 기능 게이트(클리닉배정): 조교 프리셋 포함 — 조교·관리자 허용, 학생 403
- 대기열 조회: status·date 필터, 학생 노쇼·제한 상태 동봉
- 승인+배정: 대기→승인배정(assigned_staff·meet_url 수동 입력), 재배정 허용,
  비직원 배정 400 / 미승인: 대기→미승인
- 출석/결석 처리: 결석 = noshow_count 증가, **2회 도달 시 clinic_banned=true**,
  이중 처리 400(노쇼 이중 집계 방지), 학부모 알림 행 기록(발송은 알림톡 대기)
- unban: **대표 전용**(관리자·조교 403), noshow_count 는 유지
- 평가: 항목별 기록(3표 — criteria/evaluation/item), upsert, 게이트
"""
import datetime
import json

from django.test import TestCase

from apps.accounts.models import Parent, ParentStudent, Student, User
from apps.grades.models import Exam
from apps.notifications.models import Notification

from .models import (
    ClinicEvalCriteria,
    ClinicEvaluation,
    ClinicEvaluationItem,
    ClinicRequest,
    ClinicSlot,
)

PASSWORD = "pw-Secret-77!"
REQUESTS_URL = "/api/admin/clinic/requests"
CRITERIA_URL = "/api/admin/clinic/eval-criteria"

WED = datetime.date(2026, 7, 22)


def make_user(login_id, role, name="사용자", **extra):
    return User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=role, **extra
    )


class ClinicAdminFixtureMixin:
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("ca-own", User.Role.OWNER, name="대표")
        cls.admin = make_user("ca-adm", User.Role.ADMIN, name="관리자")
        cls.assistant = make_user("ca-ast", User.Role.ASSISTANT, name="조교")
        cls.student_user = make_user("ca-stu", User.Role.STUDENT, name="박클리")
        cls.student = Student.objects.create(
            user=cls.student_user,
            matching_key="3_1111",
            enrollment_status=Student.EnrollmentStatus.REGISTERED,
        )
        cls.parent = Parent.objects.create(
            user=make_user("ca-par", User.Role.PARENT, name="박클리 학부모"),
            phone="01044445555",
        )
        ParentStudent.objects.create(parent=cls.parent, student=cls.student)
        cls.exam = Exam.objects.create(name="7월 모의고사", exam_date=WED)
        cls.slot = ClinicSlot.objects.create(
            weekday=3,
            start_time=datetime.time(19, 0),
            end_time=datetime.time(20, 0),
        )

    @classmethod
    def make_request(cls, status=ClinicRequest.Status.PENDING, student=None, **extra):
        return ClinicRequest.objects.create(
            student=student or cls.student,
            exam=cls.exam,
            slot=cls.slot,
            requested_date=WED,
            requested_time=cls.slot.start_time,
            status=status,
            **extra,
        )

    def login(self, user=None):
        self.client.force_login(user or self.admin)

    def post_json(self, url, body=None):
        return self.client.post(
            url, data=json.dumps(body or {}), content_type="application/json"
        )


class ClinicAdminGateTests(ClinicAdminFixtureMixin, TestCase):
    """클리닉배정 게이트 — 조교 프리셋 포함, 학생·학부모 차단."""

    def test_assistant_preset_allows_queue(self):
        self.login(self.assistant)
        self.assertEqual(self.client.get(REQUESTS_URL).status_code, 200)

    def test_student_gets_403(self):
        self.login(self.student_user)
        self.assertEqual(self.client.get(REQUESTS_URL).status_code, 403)


class ClinicQueueTests(ClinicAdminFixtureMixin, TestCase):
    """GET /api/admin/clinic/requests — 대기열·필터."""

    def setUp(self):
        self.login()

    def test_lists_requests_with_student_state(self):
        req = self.make_request()
        body = self.client.get(REQUESTS_URL).json()
        row = body["requests"][0]
        self.assertEqual(row["clinic_id"], req.clinic_id)
        self.assertEqual(row["student"]["name"], "박클리")
        self.assertEqual(row["student"]["noshow_count"], 0)
        self.assertFalse(row["student"]["clinic_banned"])
        self.assertEqual(row["status"], "대기")

    def test_status_and_date_filters(self):
        self.make_request()
        approved = self.make_request(
            status=ClinicRequest.Status.APPROVED, assigned_staff=self.assistant
        )
        body = self.client.get(REQUESTS_URL, {"status": "승인배정"}).json()
        self.assertEqual(
            [r["clinic_id"] for r in body["requests"]], [approved.clinic_id]
        )
        body = self.client.get(REQUESTS_URL, {"date": "2026-07-29"}).json()
        self.assertEqual(body["requests"], [])

    def test_invalid_filters_rejected(self):
        self.assertEqual(self.client.get(REQUESTS_URL, {"status": "이상값"}).status_code, 400)
        self.assertEqual(self.client.get(REQUESTS_URL, {"date": "22-07"}).status_code, 400)


class ClinicAssignTests(ClinicAdminFixtureMixin, TestCase):
    """POST .../assign · .../reject — 승인+배정·미승인."""

    def setUp(self):
        self.login()

    def test_assigns_pending_request(self):
        req = self.make_request()
        res = self.post_json(
            f"{REQUESTS_URL}/{req.clinic_id}/assign",
            {"assigned_staff_id": self.assistant.user_id, "meet_url": "https://meet.google.com/x"},
        )
        self.assertEqual(res.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, ClinicRequest.Status.APPROVED)
        self.assertEqual(req.assigned_staff, self.assistant)
        self.assertEqual(req.meet_url, "https://meet.google.com/x")

    def test_reassign_approved_request_allowed(self):
        req = self.make_request(
            status=ClinicRequest.Status.APPROVED,
            assigned_staff=self.assistant,
            meet_url="https://meet.google.com/old",
        )
        res = self.post_json(
            f"{REQUESTS_URL}/{req.clinic_id}/assign",
            {"assigned_staff_id": self.admin.user_id, "meet_url": "https://meet.google.com/new"},
        )
        self.assertEqual(res.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.assigned_staff, self.admin)

    def test_assign_requires_staff_and_meet_url(self):
        req = self.make_request()
        self.assertEqual(
            self.post_json(
                f"{REQUESTS_URL}/{req.clinic_id}/assign",
                {"assigned_staff_id": self.student_user.user_id, "meet_url": "https://m"},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.post_json(
                f"{REQUESTS_URL}/{req.clinic_id}/assign",
                {"assigned_staff_id": self.assistant.user_id},
            ).status_code,
            400,
        )

    def test_assign_cancelled_request_rejected(self):
        req = self.make_request(status=ClinicRequest.Status.CANCELLED)
        res = self.post_json(
            f"{REQUESTS_URL}/{req.clinic_id}/assign",
            {"assigned_staff_id": self.assistant.user_id, "meet_url": "https://m"},
        )
        self.assertEqual(res.status_code, 400)

    def test_assign_unknown_request_404(self):
        res = self.post_json(
            f"{REQUESTS_URL}/999999/assign",
            {"assigned_staff_id": self.assistant.user_id, "meet_url": "https://m"},
        )
        self.assertEqual(res.status_code, 404)

    def test_rejects_pending_request_only(self):
        req = self.make_request()
        res = self.post_json(f"{REQUESTS_URL}/{req.clinic_id}/reject")
        self.assertEqual(res.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, ClinicRequest.Status.REJECTED)
        self.assertEqual(
            self.post_json(f"{REQUESTS_URL}/{req.clinic_id}/reject").status_code, 400
        )


class ClinicAttendanceTests(ClinicAdminFixtureMixin, TestCase):
    """POST .../attendance — 출결 처리·노쇼 누적·2회 밴·알림 행."""

    def setUp(self):
        self.login()

    def approved(self, student=None):
        return self.make_request(
            status=ClinicRequest.Status.APPROVED,
            assigned_staff=self.assistant,
            meet_url="https://meet.google.com/x",
            student=student,
        )

    def mark(self, req, value):
        return self.post_json(f"{REQUESTS_URL}/{req.clinic_id}/attendance", {"status": value})

    def test_marks_present_and_notifies_parent(self):
        req = self.approved()
        res = self.mark(req, "출석")
        self.assertEqual(res.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.attendance_status, ClinicRequest.AttendanceStatus.PRESENT)
        self.assertIsNotNone(req.attendance_marked_at)
        self.assertEqual(req.attendance_marked_by, self.admin)
        self.student.refresh_from_db()
        self.assertEqual(self.student.noshow_count, 0)
        notif = Notification.objects.get(type=Notification.Type.CLINIC_ATTENDANCE)
        self.assertEqual(notif.parent, self.parent)
        self.assertEqual(notif.status, Notification.Status.PENDING)  # 발송은 알림톡 대기

    def test_absent_increments_noshow_and_bans_at_two(self):
        first = self.approved()
        self.assertEqual(self.mark(first, "결석").status_code, 200)
        self.student.refresh_from_db()
        self.assertEqual(self.student.noshow_count, 1)
        self.assertFalse(self.student.clinic_banned)

        second = self.approved()
        res = self.mark(second, "결석")
        self.assertEqual(res.status_code, 200)
        self.student.refresh_from_db()
        self.assertEqual(self.student.noshow_count, 2)
        self.assertTrue(self.student.clinic_banned)
        # 노쇼 경고는 학생·학부모 양쪽(PRD 3.2.4) — 행만 기록, 발송은 대기.
        warnings = Notification.objects.filter(type=Notification.Type.NOSHOW_WARNING)
        self.assertEqual(
            {(w.student_id, w.parent_id) for w in warnings.filter(ref_id=first.clinic_id)},
            {(self.student.student_id, None), (None, self.parent.parent_id)},
        )

    def test_double_marking_rejected(self):
        req = self.approved()
        self.mark(req, "결석")
        self.assertEqual(self.mark(req, "결석").status_code, 400)
        self.student.refresh_from_db()
        self.assertEqual(self.student.noshow_count, 1)  # 이중 집계 없음

    def test_pending_request_cannot_be_marked(self):
        req = self.make_request()
        self.assertEqual(self.mark(req, "출석").status_code, 400)

    def test_invalid_status_value_rejected(self):
        req = self.approved()
        self.assertEqual(self.mark(req, "미처리").status_code, 400)


class ClinicUnbanTests(ClinicAdminFixtureMixin, TestCase):
    """POST /api/admin/clinic/students/{id}/unban — 대표 전용 해제."""

    def unban(self, student_id, user):
        self.login(user)
        return self.post_json(f"/api/admin/clinic/students/{student_id}/unban")

    def ban_student(self):
        self.student.noshow_count = 2
        self.student.clinic_banned = True
        self.student.save(update_fields=["noshow_count", "clinic_banned"])

    def test_owner_unbans_keeping_noshow_count(self):
        self.ban_student()
        res = self.unban(self.student.student_id, self.owner)
        self.assertEqual(res.status_code, 200)
        self.student.refresh_from_db()
        self.assertFalse(self.student.clinic_banned)
        self.assertEqual(self.student.noshow_count, 2)  # 누적 사실은 유지

    def test_admin_and_assistant_get_403(self):
        self.ban_student()
        self.assertEqual(self.unban(self.student.student_id, self.admin).status_code, 403)
        self.assertEqual(self.unban(self.student.student_id, self.assistant).status_code, 403)
        self.student.refresh_from_db()
        self.assertTrue(self.student.clinic_banned)

    def test_not_banned_student_rejected(self):
        self.assertEqual(self.unban(self.student.student_id, self.owner).status_code, 400)

    def test_unknown_student_404(self):
        self.assertEqual(self.unban(999999, self.owner).status_code, 404)


class ClinicEvaluationTests(ClinicAdminFixtureMixin, TestCase):
    """평가표 — GET eval-criteria · POST evaluation (3표 사용)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.c1 = ClinicEvalCriteria.objects.create(item="개념 설명 정확성", display_order=1)
        cls.c2 = ClinicEvalCriteria.objects.create(item="시간 준수", display_order=2)
        cls.c_off = ClinicEvalCriteria.objects.create(item="폐지 항목", is_active=False)

    def setUp(self):
        self.login()
        self.req = self.make_request(
            status=ClinicRequest.Status.APPROVED,
            assigned_staff=self.assistant,
            meet_url="https://meet.google.com/x",
        )

    def test_lists_active_criteria_in_order(self):
        body = self.client.get(CRITERIA_URL).json()
        items = [c["item"] for c in body["criteria"]]
        self.assertEqual(items, ["개념 설명 정확성", "시간 준수"])

    def test_records_evaluation_items(self):
        res = self.post_json(
            f"{REQUESTS_URL}/{self.req.clinic_id}/evaluation",
            {
                "items": [
                    {"criteria_id": self.c1.criteria_id, "result": "충족"},
                    {"criteria_id": self.c2.criteria_id, "result": "미충족"},
                ],
                "overall_result": "부적격",
            },
        )
        self.assertEqual(res.status_code, 200)
        evaluation = ClinicEvaluation.objects.get(clinic=self.req)
        self.assertEqual(evaluation.overall_result, "부적격")
        self.assertEqual(evaluation.reviewed_by, self.admin)
        self.assertIsNotNone(evaluation.reviewed_at)
        results = {
            i.criteria_id: i.result
            for i in ClinicEvaluationItem.objects.filter(evaluation=evaluation)
        }
        self.assertEqual(
            results, {self.c1.criteria_id: "충족", self.c2.criteria_id: "미충족"}
        )

    def test_repost_upserts_items(self):
        url = f"{REQUESTS_URL}/{self.req.clinic_id}/evaluation"
        self.post_json(url, {"items": [{"criteria_id": self.c1.criteria_id, "result": "충족"}]})
        self.post_json(url, {"items": [{"criteria_id": self.c1.criteria_id, "result": "미충족"}]})
        self.assertEqual(ClinicEvaluation.objects.filter(clinic=self.req).count(), 1)
        item = ClinicEvaluationItem.objects.get(
            evaluation__clinic=self.req, criteria=self.c1
        )
        self.assertEqual(item.result, "미충족")

    def test_invalid_items_rejected(self):
        url = f"{REQUESTS_URL}/{self.req.clinic_id}/evaluation"
        self.assertEqual(self.post_json(url, {"items": []}).status_code, 400)
        self.assertEqual(
            self.post_json(
                url, {"items": [{"criteria_id": self.c_off.criteria_id, "result": "충족"}]}
            ).status_code,
            400,
        )
        self.assertEqual(
            self.post_json(
                url, {"items": [{"criteria_id": self.c1.criteria_id, "result": "보통"}]}
            ).status_code,
            400,
        )

    def test_pending_request_cannot_be_evaluated(self):
        pending = self.make_request()
        res = self.post_json(
            f"{REQUESTS_URL}/{pending.clinic_id}/evaluation",
            {"items": [{"criteria_id": self.c1.criteria_id, "result": "충족"}]},
        )
        self.assertEqual(res.status_code, 400)
