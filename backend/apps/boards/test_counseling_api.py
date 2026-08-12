"""결석 상담 API 8차 슬라이스 테스트 — PRD 3.1.9(1)·6-17·8-18.

검증 축:
- 기능 게이트(상담기록): 조교 프리셋 미포함 403 · 관리자 허용
- 대기열: 출결 트리거가 만든 `대기` 카드 + **시도 횟수 표시**
- 통화 결과 기록: 연결→완료 / 미연결→카드 확정 + **재시도 카드 생성**
  (행=시도 이력 — 스키마 불변 제약 하의 시도 횟수 산출 축)
- **3회 시도 후 문자 종결(8-18)**: 재시도 카드 미생성 + 학부모 알림 발송
  (행은 지금, 발송은 커밋 뒤)
- 동보 여부는 기록만 — 지급은 동보 체크 API(영상지급관리) 소관
"""
import datetime
import json

from django.test import TestCase, override_settings

from apps.accounts.features import FeatureKey
from apps.accounts.models import Parent, ParentStudent, StaffFeatureGrant, Student, User
from apps.grades.models import Attendance, ClassSession
from apps.notifications.models import Notification
from apps.videos.models import MakeupGrant
from config.celery import app as celery_app

from .models import AbsenceCounseling

FAKE_CHANNEL = "apps.notifications.channels.FakeChannelAdapter"

PASSWORD = "pw-Secret-77!"
QUEUE_URL = "/api/admin/counseling/queue"


def make_user(login_id, role, name="사용자", **extra):
    return User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=role, **extra
    )


class CounselingFixtureMixin:
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("co-own", User.Role.OWNER, name="대표")
        cls.admin = make_user("co-adm", User.Role.ADMIN, name="관리자")
        cls.assistant = make_user("co-ast", User.Role.ASSISTANT, name="조교")
        cls.student = Student.objects.create(
            user=make_user("co-stu", User.Role.STUDENT, name="이결석"),
            matching_key="3_2222",
            enrollment_status=Student.EnrollmentStatus.REGISTERED,
        )
        cls.parent = Parent.objects.create(
            user=make_user("co-par", User.Role.PARENT, name="이결석 학부모"),
            phone="01066667777",
        )
        ParentStudent.objects.create(parent=cls.parent, student=cls.student)
        cls.session = ClassSession.objects.create(session_date=datetime.date(2026, 7, 20))
        cls.attendance = Attendance.objects.create(
            session=cls.session, student=cls.student, status=Attendance.Status.ABSENT
        )

    @classmethod
    def make_card(cls, **extra):
        """출결 트리거(3차)가 만드는 것과 동일한 형태의 대기 카드."""
        extra.setdefault("status", AbsenceCounseling.Status.PENDING)
        return AbsenceCounseling.objects.create(
            student=cls.student,
            attendance=cls.attendance,
            target=AbsenceCounseling.Target.PARENT,
            **extra,
        )

    def login(self, user=None):
        self.client.force_login(user or self.admin)

    def patch_card(self, counsel_id, body):
        return self.client.patch(
            f"/api/admin/counseling/{counsel_id}",
            data=json.dumps(body),
            content_type="application/json",
        )


class CounselingGateTests(CounselingFixtureMixin, TestCase):
    def test_assistant_without_feature_gets_403(self):
        self.login(self.assistant)
        self.assertEqual(self.client.get(QUEUE_URL).status_code, 403)

    def test_assistant_with_delta_allowed(self):
        StaffFeatureGrant.objects.create(
            user=self.assistant,
            feature_key=FeatureKey.COUNSEL_RECORD,
            is_granted=True,
            granted_by=self.owner,
        )
        self.login(self.assistant)
        self.assertEqual(self.client.get(QUEUE_URL).status_code, 200)


class CounselingQueueTests(CounselingFixtureMixin, TestCase):
    def setUp(self):
        self.login()

    def test_lists_pending_cards_with_attempts(self):
        card = self.make_card()
        body = self.client.get(QUEUE_URL).json()
        row = body["queue"][0]
        self.assertEqual(row["counsel_id"], card.counsel_id)
        self.assertEqual(row["student"]["name"], "이결석")
        self.assertEqual(row["target"], "학부모")
        self.assertEqual(row["attempts"], 0)
        self.assertEqual(row["absence_date"], "2026-07-20")

    def test_handled_cards_leave_queue(self):
        self.make_card(
            status=AbsenceCounseling.Status.COMPLETED,
        )
        body = self.client.get(QUEUE_URL).json()
        self.assertEqual(body["queue"], [])


class CounselingPatchTests(CounselingFixtureMixin, TestCase):
    def setUp(self):
        self.login()
        self.card = self.make_card()

    def test_connected_call_completes_card(self):
        res = self.patch_card(
            self.card.counsel_id,
            {
                "result": "연결",
                "absence_reason": "감기몸살",
                "makeup_requested": True,
                "call_memo": "집에서 영상 보강 원함",
                "follow_up_action": "동보 처리 예정",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.card.refresh_from_db()
        self.assertEqual(self.card.status, AbsenceCounseling.Status.COMPLETED)
        self.assertIsNotNone(self.card.called_at)
        self.assertEqual(self.card.counselor, self.admin)
        self.assertEqual(self.card.absence_reason, "감기몸살")
        self.assertTrue(self.card.makeup_requested)
        # 기록만 — 지급 연계는 동보 체크 API(3차) 소관.
        self.assertEqual(MakeupGrant.objects.count(), 0)
        # 완료됐으니 재시도 카드 없음.
        self.assertEqual(AbsenceCounseling.objects.count(), 1)

    def test_unreached_call_creates_retry_card(self):
        res = self.patch_card(self.card.counsel_id, {"result": "미연결"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["attempts"], 1)
        self.assertFalse(body["closed"])
        self.assertIsNotNone(body["next_counsel_id"])
        self.card.refresh_from_db()
        self.assertEqual(self.card.status, AbsenceCounseling.Status.UNREACHED)
        retry = AbsenceCounseling.objects.get(pk=body["next_counsel_id"])
        self.assertEqual(retry.status, AbsenceCounseling.Status.PENDING)
        self.assertEqual(retry.attendance, self.attendance)
        self.assertEqual(retry.target, AbsenceCounseling.Target.PARENT)
        # 대기열의 새 카드는 시도 1회를 표시한다.
        row = self.client.get(QUEUE_URL).json()["queue"][0]
        self.assertEqual(row["counsel_id"], retry.counsel_id)
        self.assertEqual(row["attempts"], 1)

    def test_third_unreached_stops_retrying(self):
        card = self.card
        for attempt in (1, 2):
            body = self.patch_card(card.counsel_id, {"result": "미연결"}).json()
            self.assertEqual(body["attempts"], attempt)
            card = AbsenceCounseling.objects.get(pk=body["next_counsel_id"])
        body = self.patch_card(card.counsel_id, {"result": "미연결"}).json()
        self.assertEqual(body["attempts"], 3)
        self.assertTrue(body["closed"])
        self.assertIsNone(body["next_counsel_id"])
        # 재시도 카드 미생성 — 대기열 비움(8-18).
        self.assertEqual(
            AbsenceCounseling.objects.filter(
                status=AbsenceCounseling.Status.PENDING
            ).count(),
            0,
        )

    @override_settings(NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": FAKE_CHANNEL})
    def test_notify_button_dispatches_on_commit(self):
        # 결석 안내는 학부모에게 **실제로 나가야** 끝난 것이다 — 행만 남기면
        # 재발송 배치가 집을 때까지 밀린다. 다만 시점은 3회가 아니라 버튼이다.
        eager = celery_app.conf.task_always_eager
        celery_app.conf.task_always_eager = True
        self.addCleanup(setattr, celery_app.conf, "task_always_eager", eager)
        self.patch_card(self.card.counsel_id, {"result": "종결"})

        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post(
                f"/api/admin/counseling/{self.card.counsel_id}/notify"
            )

        self.assertEqual(res.status_code, 200)
        notif = Notification.objects.get(type=Notification.Type.ABSENCE_COUNSEL)
        self.assertEqual(notif.status, Notification.Status.SUCCESS)

    def test_handled_card_cannot_be_patched_again(self):
        self.patch_card(self.card.counsel_id, {"result": "연결"})
        self.assertEqual(
            self.patch_card(self.card.counsel_id, {"result": "연결"}).status_code, 400
        )

    def test_invalid_result_rejected(self):
        self.assertEqual(
            self.patch_card(self.card.counsel_id, {"result": "보류"}).status_code, 400
        )
        self.assertEqual(
            self.patch_card(self.card.counsel_id, {"result": "연결", "makeup_requested": "y"}
            ).status_code,
            400,
        )

    def test_unknown_card_404(self):
        self.assertEqual(self.patch_card(999999, {"result": "연결"}).status_code, 404)


class CounselingManualCloseTests(CounselingFixtureMixin, TestCase):
    """닫는 것도 보내는 것도 사람이 누른다 (2026-08-12 확정).

    3회는 "닫아도 된다"는 신호일 뿐 자동 종결이 아니다. 조교가 창을 넘겨
    계속 걸 수도 있고, 3회 전에 판단해서 닫을 수도 있다.
    """

    def setUp(self):
        self.login()
        self.card = self.make_card()

    def _third_unreached(self):
        card = self.card
        for _ in (1, 2):
            body = self.patch_card(card.counsel_id, {"result": "미연결"}).json()
            card = AbsenceCounseling.objects.get(pk=body["next_counsel_id"])
        return self.patch_card(card.counsel_id, {"result": "미연결"}).json()

    def test_third_unreached_does_not_send_anything(self):
        body = self._third_unreached()

        self.assertEqual(body["attempts"], 3)
        self.assertFalse(Notification.objects.exists(), "알림톡은 버튼으로만 나간다")

    def test_third_unreached_stops_making_retry_cards(self):
        self._third_unreached()

        self.assertEqual(
            AbsenceCounseling.objects.filter(
                status=AbsenceCounseling.Status.PENDING
            ).count(),
            0,
        )

    def test_assistant_can_close_before_three_attempts(self):
        res = self.patch_card(self.card.counsel_id, {"result": "종결"})

        self.assertEqual(res.status_code, 200)
        self.card.refresh_from_db()
        self.assertEqual(self.card.status, AbsenceCounseling.Status.UNREACHED)
        self.assertEqual(
            AbsenceCounseling.objects.filter(
                status=AbsenceCounseling.Status.PENDING
            ).count(),
            0,
            "강제 종결은 재시도 카드를 만들지 않는다",
        )

    def test_notify_sends_to_parent_on_a_closed_card(self):
        self.patch_card(self.card.counsel_id, {"result": "종결"})

        res = self.client.post(f"/api/admin/counseling/{self.card.counsel_id}/notify")

        self.assertEqual(res.status_code, 200)
        notif = Notification.objects.get(type=Notification.Type.ABSENCE_COUNSEL)
        self.assertEqual(notif.parent, self.parent)

    def test_notify_refuses_a_card_still_being_called(self):
        res = self.client.post(f"/api/admin/counseling/{self.card.counsel_id}/notify")

        self.assertEqual(res.status_code, 400)
        self.assertFalse(Notification.objects.exists())


class CounselingStudentCallTests(CounselingFixtureMixin, TestCase):
    """학생 2차는 조교가 버튼으로 연다 (8-18 "학부모 선에서 해결 안 될 때")."""

    def setUp(self):
        self.login()
        self.parent_card = self.make_card()

    def test_creates_a_student_card_for_the_same_absence(self):
        res = self.client.post(
            "/api/admin/counseling",
            data=json.dumps({"from_counsel_id": self.parent_card.counsel_id, "target": "학생"}),
            content_type="application/json",
        )

        self.assertEqual(res.status_code, 201)
        card = AbsenceCounseling.objects.get(pk=res.json()["counsel_id"])
        self.assertEqual(card.target, AbsenceCounseling.Target.STUDENT)
        self.assertEqual(card.status, AbsenceCounseling.Status.PENDING)

    def test_student_attempts_are_counted_separately_from_parent(self):
        self.patch_card(self.parent_card.counsel_id, {"result": "미연결"})

        res = self.client.post(
            "/api/admin/counseling",
            data=json.dumps({"from_counsel_id": self.parent_card.counsel_id, "target": "학생"}),
            content_type="application/json",
        )
        body = self.patch_card(res.json()["counsel_id"], {"result": "미연결"}).json()

        self.assertEqual(body["attempts"], 1, "학부모 시도가 학생 카운트에 섞이면 안 된다")


class CounselingClosedStayVisibleTests(CounselingFixtureMixin, TestCase):
    """닫힌 카드는 알림을 보낼 때까지 화면에 남는다.

    발송이 버튼이 된 이상 닫자마자 목록에서 사라지면 누를 자리가 없어지고,
    학부모는 아무 연락도 못 받은 채 끝난다.
    """

    def setUp(self):
        self.login()
        self.card = self.make_card()

    def test_closed_card_awaits_notification_in_queue(self):
        self.patch_card(self.card.counsel_id, {"result": "종결"})

        rows = self.client.get(QUEUE_URL).json()["queue"]

        self.assertEqual([r["counsel_id"] for r in rows], [self.card.counsel_id])
        self.assertTrue(rows[0]["awaiting_notice"])

    def test_notified_card_leaves_the_queue(self):
        self.patch_card(self.card.counsel_id, {"result": "종결"})
        self.client.post(f"/api/admin/counseling/{self.card.counsel_id}/notify")

        self.assertEqual(self.client.get(QUEUE_URL).json()["queue"], [])

    def test_connected_card_never_awaits_notification(self):
        self.patch_card(self.card.counsel_id, {"result": "연결"})

        self.assertEqual(self.client.get(QUEUE_URL).json()["queue"], [])
