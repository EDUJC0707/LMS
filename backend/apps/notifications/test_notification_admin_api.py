"""관리자 발송내역 조회 API 테스트 — GET /api/admin/notifications (PRD 3.1.2).

PRD 요구: *"발송 대상·채널·발송시각·전달 상태(성공/실패)를 관리자가 조회·확인"*.

이 화면이 없으면 발송이 실패해도 사유가 `error_msg` 에 쌓이기만 하고 아무도
못 본다 — 그래서 응답에 **실패 사유가 반드시 실려야** 한다.
"""
import datetime

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.features import FeatureKey
from apps.accounts.models import Parent, StaffFeatureGrant, Student, User
from config.celery import app as celery_app

from .channels import FakeChannelAdapter
from .models import Notification

URL = "/api/admin/notifications"
PASSWORD = "pw-Secret-77!"
FAKE_CHANNEL = "apps.notifications.channels.FakeChannelAdapter"


def make_user(login_id, role, name="사용자", **extra):
    return User.objects.create_user(
        login_id=login_id, password=PASSWORD, name=name, role=role, **extra
    )


class NotificationAdminFixtureMixin:
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("na-own", User.Role.OWNER, name="대표")
        cls.admin = make_user("na-adm", User.Role.ADMIN, name="관리자")
        cls.assistant = make_user("na-ast", User.Role.ASSISTANT, name="조교")
        cls.student = Student.objects.create(
            user=make_user("na-stu", User.Role.STUDENT, name="김하늘", phone="01011112222"),
            matching_key="김하늘0001",
        )
        cls.parent = Parent.objects.create(
            user=make_user("na-par", User.Role.PARENT, name="김학부"),
            name="김학부",
            phone="01033334444",
        )

    def login(self, user=None):
        self.client.force_login(user or self.admin)

    def make_notif(self, **kwargs):
        kwargs.setdefault("channel", Notification.Channel.KAKAO)
        kwargs.setdefault("type", Notification.Type.GRADE)
        if not any(k in kwargs for k in ("student", "parent", "user")):
            kwargs["student"] = self.student
        return Notification.objects.create(**kwargs)

    def rows(self, query=""):
        return self.client.get(f"{URL}{query}").json()["results"]


class NotificationAdminGateTests(NotificationAdminFixtureMixin, TestCase):
    """게이트는 기능 키 `알림발송` — 관리자 프리셋에 있고 조교엔 없다."""

    def test_admin_is_allowed(self):
        self.login()
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_owner_is_allowed(self):
        self.login(self.owner)
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_assistant_is_denied_without_the_feature(self):
        self.login(self.assistant)
        self.assertEqual(self.client.get(URL).status_code, 403)

    def test_assistant_is_allowed_once_granted(self):
        StaffFeatureGrant.objects.create(
            user=self.assistant, feature_key=FeatureKey.NOTIFICATION_SEND, is_granted=True
        )
        self.login(self.assistant)
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_student_is_denied(self):
        self.client.force_login(self.student.user)
        self.assertEqual(self.client.get(URL).status_code, 403)

    def test_anonymous_is_denied(self):
        self.assertIn(self.client.get(URL).status_code, (401, 403))


class NotificationAdminListTests(NotificationAdminFixtureMixin, TestCase):
    def setUp(self):
        self.login()

    def test_row_carries_what_prd_asks_for(self):
        # 대상·채널·발송시각·전달 상태(PRD 3.1.2).
        sent_at = timezone.now()
        self.make_notif(
            title="성적 안내",
            body="3회차 성적이 등록되었습니다.",
            status=Notification.Status.SUCCESS,
            sent_at=sent_at,
        )

        row = self.rows()[0]

        self.assertEqual(row["channel"], "카카오알림톡")
        self.assertEqual(row["type"], "성적")
        self.assertEqual(row["status"], "성공")
        self.assertEqual(row["title"], "성적 안내")
        self.assertEqual(row["body"], "3회차 성적이 등록되었습니다.")
        self.assertIsNotNone(row["sent_at"])
        self.assertEqual(
            row["target"],
            {"kind": "학생", "id": self.student.student_id, "name": "김하늘"},
        )

    def test_failure_reason_is_visible(self):
        # 이 API 의 존재 이유 — 사유가 안 보이면 실패를 알 길이 없다.
        self.make_notif(status=Notification.Status.FAILED, error_msg="수신 거부된 번호")

        self.assertEqual(self.rows()[0]["error_msg"], "수신 거부된 번호")

    def test_parent_target_is_labelled(self):
        self.make_notif(student=None, parent=self.parent)

        self.assertEqual(
            self.rows()[0]["target"],
            {"kind": "학부모", "id": self.parent.parent_id, "name": "김학부"},
        )

    def test_staff_target_is_labelled(self):
        self.make_notif(student=None, user=self.admin)

        self.assertEqual(
            self.rows()[0]["target"],
            {"kind": "직원", "id": self.admin.user_id, "name": "관리자"},
        )

    def test_student_without_account_falls_back_to_unique_id(self):
        # 계정 발급 전 학생 — 이름이 users 행에 있어서 비어 있다.
        orphan = Student.objects.create(matching_key="장예준0029")
        self.make_notif(student=orphan)

        self.assertEqual(self.rows()[0]["target"]["name"], "장예준0029")

    def test_latest_first(self):
        first = self.make_notif(title="먼저")
        second = self.make_notif(title="나중")

        self.assertEqual(
            [row["notif_id"] for row in self.rows()],
            [second.notif_id, first.notif_id],
        )

    def test_page_is_capped(self):
        for _ in range(21):
            self.make_notif()

        body = self.client.get(URL).json()
        self.assertEqual(body["count"], 21)
        self.assertEqual(len(body["results"]), 20)


class NotificationAdminFilterTests(NotificationAdminFixtureMixin, TestCase):
    def setUp(self):
        self.login()
        self.failed = self.make_notif(status=Notification.Status.FAILED, error_msg="사유")
        self.sent = self.make_notif(status=Notification.Status.SUCCESS, sent_at=timezone.now())
        self.sms = self.make_notif(
            channel=Notification.Channel.SMS, type=Notification.Type.ACCOUNT_ISSUED
        )
        self.to_parent = self.make_notif(student=None, parent=self.parent)

    def ids(self, query):
        return {row["notif_id"] for row in self.rows(query)}

    def test_filter_by_status(self):
        # 운영에서 제일 먼저 보는 것 — "안 나간 게 있나".
        self.assertEqual(self.ids("?status=실패"), {self.failed.notif_id})

    def test_filter_by_channel(self):
        self.assertEqual(self.ids("?channel=문자"), {self.sms.notif_id})

    def test_filter_by_type(self):
        self.assertEqual(self.ids("?type=계정발급"), {self.sms.notif_id})

    def test_filter_by_student(self):
        mine = self.ids(f"?student_id={self.student.student_id}")
        self.assertNotIn(self.to_parent.notif_id, mine)

    def test_filter_by_parent(self):
        self.assertEqual(
            self.ids(f"?parent_id={self.parent.parent_id}"), {self.to_parent.notif_id}
        )

    def test_filters_combine(self):
        self.assertEqual(self.ids("?status=실패&channel=카카오알림톡"), {self.failed.notif_id})

    def test_filter_by_date_range_uses_created_at(self):
        # sent_at 은 미발송 행에서 NULL 이라 범위 축으로 못 쓴다.
        old = self.make_notif()
        Notification.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - datetime.timedelta(days=10)
        )
        today = timezone.localdate().isoformat()

        self.assertNotIn(old.notif_id, self.ids(f"?from={today}"))
        self.assertEqual(self.ids(f"?to={today}&status=실패"), {self.failed.notif_id})

    def test_unknown_status_value_is_400(self):
        # 오타를 빈 목록으로 돌려주면 "발송이 하나도 없다"로 읽힌다.
        self.assertEqual(self.client.get(f"{URL}?status=없는상태").status_code, 400)

    def test_unknown_channel_value_is_400(self):
        self.assertEqual(self.client.get(f"{URL}?channel=카톡").status_code, 400)

    def test_malformed_date_is_400(self):
        self.assertEqual(self.client.get(f"{URL}?from=어제").status_code, 400)

    def test_non_numeric_target_id_is_400(self):
        self.assertEqual(self.client.get(f"{URL}?student_id=abc").status_code, 400)

    def test_unknown_type_value_is_allowed(self):
        # type 은 개방 값집합(8-17 대기) — 값집합 검증을 걸면 새 유형이 조회 불가가 된다.
        self.assertEqual(self.client.get(f"{URL}?type=새유형").status_code, 200)


@override_settings(NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": FAKE_CHANNEL})
class NotificationResendTests(NotificationAdminFixtureMixin, TestCase):
    """POST /api/admin/notifications/{id}/resend — 개인별 (재)발송(PRD 3.1.2).

    **끝난 행은 다시 쓰지 않는다.** 성공/전달확인은 확정된 이력이라 새 행을 만들고,
    아직 안 끝난 대기/실패는 그 행을 다시 띄운다(재발송 배치와 같은 축) —
    그래서 배치가 도는 창 안에서 눌러도 같은 행이라 이중 발송이 나지 않는다.
    """

    def setUp(self):
        self.login()
        eager = celery_app.conf.task_always_eager
        celery_app.conf.task_always_eager = True
        self.addCleanup(setattr, celery_app.conf, "task_always_eager", eager)
        FakeChannelAdapter.outbox.clear()

    def resend(self, notif_id):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(f"{URL}/{notif_id}/resend")

    def test_assistant_is_denied(self):
        self.login(self.assistant)
        notif = self.make_notif()
        self.assertEqual(self.client.post(f"{URL}/{notif.notif_id}/resend").status_code, 403)

    def test_unknown_id_is_404(self):
        self.assertEqual(self.client.post(f"{URL}/999999/resend").status_code, 404)

    def test_failed_row_is_retried_in_place(self):
        notif = self.make_notif(status=Notification.Status.FAILED, error_msg="수신 거부된 번호")

        res = self.resend(notif.notif_id)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(Notification.objects.count(), 1)  # 새 행 없음
        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.Status.SUCCESS)
        self.assertIsNone(notif.error_msg)

    def test_pending_row_is_retried_in_place(self):
        notif = self.make_notif()

        self.resend(notif.notif_id)

        self.assertEqual(Notification.objects.count(), 1)
        notif.refresh_from_db()
        self.assertEqual(notif.status, Notification.Status.SUCCESS)

    def test_successful_row_is_sent_again_as_a_new_row(self):
        # "학부모가 못 받았대요" — 성공 이력은 사실이므로 덮지 않는다.
        original = self.make_notif(
            title="성적 안내", status=Notification.Status.SUCCESS, sent_at=timezone.now()
        )

        res = self.resend(original.notif_id)

        self.assertEqual(Notification.objects.count(), 2)
        self.assertNotEqual(res.json()["notif_id"], original.notif_id)
        original.refresh_from_db()
        self.assertEqual(original.status, Notification.Status.SUCCESS)

    def test_confirmed_row_is_sent_again_as_a_new_row(self):
        original = self.make_notif(status=Notification.Status.CONFIRMED)

        self.resend(original.notif_id)

        self.assertEqual(Notification.objects.count(), 2)

    def test_new_row_copies_the_original_content(self):
        original = self.make_notif(
            title="성적 안내",
            body="3회차 성적이 등록되었습니다.",
            ref_type="exam",
            ref_id=7,
            status=Notification.Status.SUCCESS,
        )

        clone = Notification.objects.get(pk=self.resend(original.notif_id).json()["notif_id"])

        self.assertEqual(clone.student_id, original.student_id)
        self.assertEqual(clone.channel, original.channel)
        self.assertEqual(clone.type, original.type)
        self.assertEqual(clone.title, original.title)
        self.assertEqual(clone.body, original.body)
        self.assertEqual(clone.ref_type, "exam")
        self.assertEqual(clone.ref_id, 7)

    def test_response_shows_the_row_back_in_flight(self):
        # 발송은 비동기라 응답 시점에 결과를 알 수 없다. 그래도 `실패` 를 그대로
        # 돌려주면 관리자는 눌렀는지 안 눌렀는지 알 수 없다 — `대기` 로 되돌린다.
        notif = self.make_notif(status=Notification.Status.FAILED, error_msg="수신 거부된 번호")

        with self.captureOnCommitCallbacks(execute=False):
            body = self.client.post(f"{URL}/{notif.notif_id}/resend").json()

        self.assertEqual(body["notif_id"], notif.notif_id)
        self.assertEqual(body["status"], "대기")
        self.assertIsNone(body["error_msg"])
        self.assertEqual(body["target"]["name"], "김하늘")

    def test_resend_actually_hands_the_message_to_the_channel(self):
        notif = self.make_notif(status=Notification.Status.FAILED)

        self.resend(notif.notif_id)

        self.assertEqual(len(FakeChannelAdapter.outbox), 1)
        self.assertEqual(FakeChannelAdapter.outbox[0].recipient, "01011112222")

    def test_nothing_is_sent_before_commit(self):
        notif = self.make_notif(status=Notification.Status.FAILED)

        with self.captureOnCommitCallbacks(execute=False):
            self.client.post(f"{URL}/{notif.notif_id}/resend")

        self.assertEqual(FakeChannelAdapter.outbox, [])
