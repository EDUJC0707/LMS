"""notifications 스모크 테스트 — 도메인 8(알림) 핵심 계약 검증.

설계 근거: docs/db/lms-db-design-2026-07-15.md 도메인 8(§1.4 값만 추가·재사용),
§4.5(발송 이력 인덱스), baseline lms-db-spec.html Domain 7, PRD 3.1.2(알림
발송)·§4(채널 추상화 — 6-8).
핵심은 대상 3분기(셋 중 하나만)와 type 개방 값집합(7/29 확정 목록 대비)이다.
"""
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.accounts.models import Parent, Student, User

from .models import Notification


def make_student(unique_id="3_1234"):
    return Student.objects.create(unique_id=unique_id)


class NotificationSchemaTests(TestCase):
    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(Notification._meta.db_table, "notifications")
        self.assertEqual(Notification._meta.pk.column, "notif_id")

    def test_channel_value_set_follows_design(self):
        # baseline: 카카오알림톡/문자/앱푸시 — 채널 추상화(PRD 6-8)의 값집합
        self.assertEqual(
            set(Notification.Channel.values), {"카카오알림톡", "문자", "앱푸시"}
        )

    def test_status_value_set_and_default(self):
        # baseline: 대기/성공/실패/전달확인, 기본 대기 — 발송내역 조회(3.1.2)
        self.assertEqual(
            set(Notification.Status.values), {"대기", "성공", "실패", "전달확인"}
        )
        notif = Notification.objects.create(
            student=make_student(),
            channel=Notification.Channel.KAKAO,
            type=Notification.Type.GRADE,
        )
        self.assertEqual(notif.status, Notification.Status.PENDING)
        self.assertIsNone(notif.sent_at)
        self.assertIsNone(notif.error_msg)

    def test_type_value_set_is_open(self):
        # 발송 시점 전체 확정 목록은 미결 8-17(2026-07-29 수신 예정) —
        # type 은 choices 를 필드에 바인딩하지 않는 개방 값집합이다.
        # (값 추가 = 상수 추가만, AlterField 마이그레이션조차 없음)
        self.assertIsNone(Notification._meta.get_field("type").choices)
        # 알려진 값 상수는 제공(설계 §1.4 신규 type + baseline)
        known = set(Notification.Type.values)
        self.assertLessEqual(
            {"성적", "영상권한", "결제", "리포트", "클리닉출결", "동보", "노쇼경고"},
            known,
        )

    def test_ref_is_soft_link(self):
        # baseline: ref_type/ref_id 는 유발 원인 soft 링크(FK 아님) —
        # 어떤 도메인이든 값으로 가리킨다(order/exam/clinic …).
        ref_id_field = Notification._meta.get_field("ref_id")
        self.assertFalse(ref_id_field.is_relation)
        self.assertEqual(ref_id_field.get_internal_type(), "BigIntegerField")

    def test_no_vendor_specific_columns(self):
        # key_considerations §4: 채널 추상화 — 솔라피 등 업체 종속 컬럼 금지.
        # 외부 연동 상태는 status/error_msg 중립 컬럼으로만 기록한다.
        field_names = {f.name for f in Notification._meta.get_fields()}
        self.assertFalse(
            {"solapi_message_id", "kakao_template_code", "biztalk_ref"} & field_names,
            "업체 종속 컬럼 금지(채널 중립)",
        )

    def test_partial_indexes_follow_design(self):
        # 설계 §4.5: 대상별 최신순(부분)·재발송 배치(부분) 인덱스
        index_names = {idx.name for idx in Notification._meta.indexes}
        self.assertEqual(
            index_names,
            {"idx_notif_student_sent", "idx_notif_parent_sent", "idx_notif_status"},
        )


class NotificationTargetTests(TestCase):
    """대상 3분기 — student/parent/user 셋 중 정확히 하나만 채운다(앱 레벨 강제)."""

    def setUp(self):
        self.student = make_student()
        self.parent = Parent.objects.create(phone="01012345678")
        self.staff = User.objects.create_user("01011112222", role=User.Role.ADMIN, name="관리자")

    def make_notif(self, **kwargs):
        kwargs.setdefault("channel", Notification.Channel.KAKAO)
        kwargs.setdefault("type", Notification.Type.GRADE)
        return Notification(**kwargs)

    def test_single_target_is_valid(self):
        for target in ({"student": self.student}, {"parent": self.parent}, {"user": self.staff}):
            self.make_notif(**target).full_clean()  # 예외 없어야 함

    def test_no_target_is_invalid(self):
        # DB CHECK 금지 원칙 — 강제는 앱 레벨(clean)
        with self.assertRaises(ValidationError):
            self.make_notif().full_clean()

    def test_multiple_targets_are_invalid(self):
        with self.assertRaises(ValidationError):
            self.make_notif(student=self.student, parent=self.parent).full_clean()

    def test_target_contract_documented(self):
        self.assertIn("하나만", Notification.__doc__)
