"""clinic 스모크 테스트 — 도메인 6(클리닉) 핵심 계약 검증.

설계 근거: docs/db/lms-db-design-2026-07-15.md 도메인 6, §4.8(인덱스),
baseline lms-db-spec.html Domain 4, PRD 3.2.4(클리닉 신청).
핵심 제약(UQ)·값집합·자격 판정 참조 계약(grades 원천, 사본 금지) 위주로 검증한다.
"""
import datetime

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from apps.accounts.models import Student, User
from apps.grades.models import Exam

from .models import (
    ClinicEligibility,
    ClinicEvalCriteria,
    ClinicEvaluation,
    ClinicEvaluationItem,
    ClinicRequest,
    ClinicSlot,
)


def make_student(unique_id="3_1234"):
    return Student.objects.create(unique_id=unique_id)


def make_exam(**kwargs):
    kwargs.setdefault("name", "오메가 1회")
    kwargs.setdefault("exam_date", datetime.date(2026, 7, 22))
    return Exam.objects.create(**kwargs)


def make_slot(**kwargs):
    kwargs.setdefault("weekday", 1)  # 월
    kwargs.setdefault("start_time", datetime.time(19, 0))
    kwargs.setdefault("end_time", datetime.time(20, 0))
    return ClinicSlot.objects.create(**kwargs)


class ClinicSlotTests(TestCase):
    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(ClinicSlot._meta.db_table, "clinic_slots")
        self.assertEqual(ClinicSlot._meta.pk.column, "slot_id")

    def test_unique_per_weekday_and_start_time(self):
        # 설계: UQ(weekday, start_time) — 같은 요일·같은 시작시간 슬롯 중복 금지
        make_slot()
        with self.assertRaises(IntegrityError):
            make_slot()

    def test_capacity_defaults_to_one_and_active(self):
        # 설계: capacity NN 기본 1, is_active NN 기본 true
        slot = make_slot()
        self.assertEqual(slot.capacity, 1)
        self.assertTrue(slot.is_active)

    def test_capacity_cannot_be_stored_other_than_one(self):
        # 2026-07-21 회의: 클리닉은 "시간별로 학생 한 명씩" — 정원은 관리자가
        # 정하는 값이 아니라 운영의 고정 사실이므로 DB 가 직접 막는다.
        with self.assertRaises(IntegrityError):
            make_slot(weekday=2, capacity=2)

    def test_capacity_zero_is_also_rejected(self):
        with self.assertRaises(IntegrityError):
            make_slot(weekday=2, capacity=0)

    def test_capacity_validation_rejects_other_than_one(self):
        # 폼·직접 호출 경로(full_clean)에서도 같은 불변식을 잡는다.
        slot = ClinicSlot(
            weekday=2,
            start_time=datetime.time(19, 0),
            end_time=datetime.time(20, 0),
            capacity=3,
        )
        with self.assertRaises(ValidationError):
            slot.full_clean()

    def test_capacity_is_not_editable(self):
        # 관리자 화면·폼에 정원 입력칸이 뜨지 않게 한다(편집 불가 필드).
        self.assertFalse(ClinicSlot._meta.get_field("capacity").editable)

    def test_fixed_capacity_contract_documented(self):
        # 정원 고정의 근거(0721 회의)와 마감 판정 계약이 docstring 에 있어야 한다.
        doc = ClinicSlot.__doc__
        self.assertIn("한 타임 1명", doc)
        self.assertIn("2026-07-21", doc)
        self.assertNotIn("조교 수", doc)


class ClinicRequestTests(TestCase):
    def setUp(self):
        self.student = make_student()

    def make_request(self, **kwargs):
        kwargs.setdefault("student", self.student)
        kwargs.setdefault("requested_date", datetime.date(2026, 7, 27))
        kwargs.setdefault("requested_time", datetime.time(19, 0))
        return ClinicRequest.objects.create(**kwargs)

    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(ClinicRequest._meta.db_table, "clinic_requests")
        self.assertEqual(ClinicRequest._meta.pk.column, "clinic_id")

    def test_status_value_set_includes_cancel(self):
        # 설계 delta: status 값 확장 = 대기/승인배정/미승인/취소
        self.assertEqual(
            set(ClinicRequest.Status.values), {"대기", "승인배정", "미승인", "취소"}
        )

    def test_defaults_follow_design(self):
        # 설계: status 기본 `대기`, slot/exam/cancelled_at/미트링크는 선택
        req = self.make_request()
        self.assertEqual(req.status, ClinicRequest.Status.PENDING)
        self.assertIsNone(req.slot)
        self.assertIsNone(req.exam)
        self.assertIsNone(req.cancelled_at)
        self.assertIsNone(req.meet_url)
        self.assertIsNone(req.assigned_staff)

    def test_attendance_status_value_set(self):
        # baseline: 미처리/출석/결석(=노쇼)
        self.assertEqual(
            set(ClinicRequest.AttendanceStatus.values), {"미처리", "출석", "결석"}
        )

    def test_noshow_and_cancel_contract_documented(self):
        # PRD 3.2.4: 취소는 노쇼로 집계하지 않음. 노쇼 누적 2회 영구 제한의
        # 원천은 students.noshow_count/clinic_banned(사본 금지) — docstring 계약.
        doc = ClinicRequest.__doc__
        self.assertIn("노쇼", doc)
        self.assertIn("취소", doc)
        self.assertIn("noshow_count", doc)

    def test_deadline_and_link_contract_documented(self):
        # 2026-07-29 확정: 클리닉 날짜의 전날까지만 신청·변경·취소(당일 불가).
        # 미트 링크는 시작 5분 전부터 해당 학생에게만 노출·재사용 금지 —
        # 둘 다 앱 레이어 계약이라 docstring 에 남긴다.
        doc = ClinicRequest.__doc__
        self.assertIn("전날", doc)
        self.assertIn("5분", doc)
        # 옛 규칙(당일 오전 8시 마감)이 남아 있으면 안 된다
        self.assertNotIn("8시", doc)


class ClinicEligibilityTests(TestCase):
    def setUp(self):
        self.exam = make_exam()
        self.student = make_student()

    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(ClinicEligibility._meta.db_table, "clinic_eligibilities")
        self.assertEqual(ClinicEligibility._meta.pk.column, "eligibility_id")

    def test_unique_per_exam_and_student(self):
        # 설계: UQ(exam_id, student_id) — 시험·학생당 판정 1건
        ClinicEligibility.objects.create(exam=self.exam, student=self.student)
        with self.assertRaises(IntegrityError):
            ClinicEligibility.objects.create(exam=self.exam, student=self.student)

    def test_defaults_follow_design(self):
        # 설계: is_target NN 기본 false(닫힘이 안전 기본값), cutoff/사유/판정자 NULL
        elig = ClinicEligibility.objects.create(exam=self.exam, student=self.student)
        self.assertFalse(elig.is_target)
        self.assertIsNone(elig.cutoff_score)
        self.assertIsNone(elig.reason)
        self.assertIsNone(elig.determined_by)
        self.assertIsNone(elig.determined_at)

    def test_reason_value_set_follows_design(self):
        # 설계: 미대상 사유 = 결석/미응시/평균이상
        self.assertEqual(
            set(ClinicEligibility.Reason.values), {"결석", "미응시", "평균이상"}
        )

    def test_no_source_copy_columns(self):
        # 컨벤션: 출석·응시는 grades(Attendance/Score)가 원천 — 사본 컬럼 금지.
        # 이 표에는 판정 "결과"만 남긴다(is_target/reason/cutoff_score).
        field_names = {f.name for f in ClinicEligibility._meta.get_fields()}
        self.assertNotIn("exam_taken", field_names)
        self.assertNotIn("attendance_status", field_names)
        self.assertNotIn("is_taken", field_names)

    def test_source_reference_contract_documented(self):
        # 자격 3조건(출석+응시+평균미달)의 참조·계산 경로가 docstring 계약으로
        # 명시되어야 한다(원천: attendances / scores.is_taken / exams.avg_score).
        doc = ClinicEligibility.__doc__
        self.assertIn("attendances", doc)
        self.assertIn("is_taken", doc)
        self.assertIn("avg_score", doc)


class ClinicEvaluationTests(TestCase):
    def setUp(self):
        self.student = make_student()
        self.request = ClinicRequest.objects.create(
            student=self.student,
            requested_date=datetime.date(2026, 7, 27),
            requested_time=datetime.time(19, 0),
        )

    def test_criteria_table_and_defaults(self):
        self.assertEqual(ClinicEvalCriteria._meta.db_table, "clinic_eval_criteria")
        self.assertEqual(ClinicEvalCriteria._meta.pk.column, "criteria_id")
        criteria = ClinicEvalCriteria.objects.create(item="개념 설명이 정확한가")
        self.assertTrue(criteria.is_active)

    def test_evaluation_table_and_pk_column(self):
        self.assertEqual(ClinicEvaluation._meta.db_table, "clinic_evaluations")
        self.assertEqual(ClinicEvaluation._meta.pk.column, "eval_id")

    def test_one_evaluation_per_clinic(self):
        # baseline: 평가는 클리닉 1건당 1개(1:1)
        ClinicEvaluation.objects.create(clinic=self.request)
        with self.assertRaises(IntegrityError):
            ClinicEvaluation.objects.create(clinic=self.request)

    def test_evaluation_defaults(self):
        # baseline: needs_review NN 기본 false(부적격 → 관리자 확인 흐름), 나머지 선택
        ev = ClinicEvaluation.objects.create(clinic=self.request)
        self.assertFalse(ev.needs_review)
        self.assertIsNone(ev.recording_path)
        self.assertIsNone(ev.overall_result)

    def test_item_unique_per_eval_and_criteria(self):
        # baseline: UNIQUE(eval_id, criteria_id)
        ev = ClinicEvaluation.objects.create(clinic=self.request)
        criteria = ClinicEvalCriteria.objects.create(item="시간을 준수했는가")
        ClinicEvaluationItem.objects.create(
            evaluation=ev, criteria=criteria, result=ClinicEvaluationItem.Result.MET
        )
        with self.assertRaises(IntegrityError):
            ClinicEvaluationItem.objects.create(
                evaluation=ev, criteria=criteria,
                result=ClinicEvaluationItem.Result.UNMET,
            )

    def test_item_result_value_set(self):
        # baseline: 충족/미충족(AI 판단), admin_override 로 관리자 수정
        self.assertEqual(set(ClinicEvaluationItem.Result.values), {"충족", "미충족"})


class StaffAssignmentTests(TestCase):
    def test_assigned_staff_is_user_fk(self):
        # 배정 조교는 users FK(직원 계정) — 승인+배정(담당 지정)의 근거
        staff = User.objects.create_user("01011112222", role=User.Role.ASSISTANT, name="조교A")
        req = ClinicRequest.objects.create(
            student=make_student(),
            requested_date=datetime.date(2026, 7, 27),
            requested_time=datetime.time(19, 0),
            assigned_staff=staff,
            status=ClinicRequest.Status.APPROVED,
        )
        self.assertEqual(req.assigned_staff.role, User.Role.ASSISTANT)
