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
        self.assertFalse(body["closed_by_sms"])
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

    def test_third_unreached_closes_with_sms_record_only(self):
        card = self.card
        for attempt in (1, 2):
            body = self.patch_card(card.counsel_id, {"result": "미연결"}).json()
            self.assertEqual(body["attempts"], attempt)
            card = AbsenceCounseling.objects.get(pk=body["next_counsel_id"])
        body = self.patch_card(card.counsel_id, {"result": "미연결"}).json()
        self.assertEqual(body["attempts"], 3)
        self.assertTrue(body["closed_by_sms"])
        self.assertIsNone(body["next_counsel_id"])
        # 재시도 카드 미생성 — 대기열 비움(8-18 종결).
        self.assertEqual(
            AbsenceCounseling.objects.filter(
                status=AbsenceCounseling.Status.PENDING
            ).count(),
            0,
        )
        # 종결 알림은 학부모 대상. 발송은 커밋 뒤라 이 시점엔 아직 대기다.
        notif = Notification.objects.get(type=Notification.Type.ABSENCE_COUNSEL)
        self.assertEqual(notif.parent, self.parent)
        self.assertEqual(notif.status, Notification.Status.PENDING)

    @override_settings(NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": FAKE_CHANNEL})
    def test_sms_closure_is_dispatched_on_commit(self):
        # 3회 미연결 종결은 학부모에게 **실제로 나가야** 끝난 것이다 —
        # 행만 남기면 재발송 배치가 집을 때까지 결석 안내가 밀린다.
        eager = celery_app.conf.task_always_eager
        celery_app.conf.task_always_eager = True
        self.addCleanup(setattr, celery_app.conf, "task_always_eager", eager)
        card = self.card
        for _ in (1, 2):
            body = self.patch_card(card.counsel_id, {"result": "미연결"}).json()
            card = AbsenceCounseling.objects.get(pk=body["next_counsel_id"])

        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(
                self.patch_card(card.counsel_id, {"result": "미연결"}).json()["closed_by_sms"]
            )

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
