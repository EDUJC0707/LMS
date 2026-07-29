"""grades 스모크 테스트 — 도메인 2(성적/OMR/과제) 핵심 계약 검증.

설계 근거: docs/db/lms-db-design-2026-07-15.md 도메인 2, §4.1~§4.3(인덱스),
PRD 3.1.1(성적 처리)·3.1.6(출결 SSOT)·3.2.1(누적 성적표).
핵심 제약(UQ)·값집합·SSOT 계약 위주로 검증한다.
"""
import datetime
from decimal import Decimal

from django.db import IntegrityError
from django.test import TestCase

from apps.accounts.models import Student
from apps.accounts.unique_id import build_unique_id

from .models import (
    AnswerSheet,
    Assignment,
    Attendance,
    ClassSession,
    Exam,
    Question,
    QuestionBankItem,
    QuestionSimilarMap,
    Score,
    SheetAnswer,
    WeaknessCheckPdf,
    WorkbookSubmission,
)


def make_student(unique_id="3_1234"):
    return Student.objects.create(unique_id=unique_id)


def make_session(**kwargs):
    kwargs.setdefault("session_date", datetime.date(2026, 7, 22))
    return ClassSession.objects.create(**kwargs)


def make_exam(**kwargs):
    kwargs.setdefault("name", "오메가 1회")
    kwargs.setdefault("exam_date", datetime.date(2026, 7, 22))
    return Exam.objects.create(**kwargs)


class ClassSessionTests(TestCase):
    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(ClassSession._meta.db_table, "class_sessions")
        self.assertEqual(ClassSession._meta.pk.column, "session_id")

    def test_exam_and_course_week_are_optional(self):
        # 설계: exam_id FK 선택(그날 시험 없으면 NULL), course_week_id NULL
        session = make_session()
        self.assertIsNone(session.exam)
        self.assertIsNone(session.course_week)


class AttendanceTests(TestCase):
    """출결 SSOT(PRD 3.1.6) — 영상/클리닉/캘린더/리포트의 단일 원천."""

    def setUp(self):
        self.session = make_session()
        self.student = make_student()

    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(Attendance._meta.db_table, "attendances")
        self.assertEqual(Attendance._meta.pk.column, "id")

    def test_unique_per_session_and_student(self):
        # 설계: UQ(session_id, student_id) — 회차당 학생 1줄
        Attendance.objects.create(
            session=self.session, student=self.student, status=Attendance.Status.PRESENT
        )
        with self.assertRaises(IntegrityError):
            Attendance.objects.create(
                session=self.session, student=self.student,
                status=Attendance.Status.ABSENT,
            )

    def test_status_value_set_follows_design(self):
        # 2026-07-29 사용자 확정: 출석/결석/결석(동보)/결석(현보) 4종.
        # 결석 3종은 "왔는가"가 아니라 "보강이 어떻게 됐는가"로 갈린다 —
        # 미정(결석) / 동영상 보강(동보) / 현장 보강(현보).
        self.assertEqual(
            set(Attendance.Status.values),
            {"출석", "결석", "결석(동보)", "결석(현보)"},
        )

    def test_status_has_no_late_value(self):
        # 2026-07-29 사용자 확정 — 지각 제거. 시험을 수업 **초반**에 보므로
        # 지각하면 OMR 카드가 안 들어온다. 즉 지각은 출결 값이 아니라 성적이
        # '시험 미제출'(scores.is_taken=False)로 나가는 것으로 드러난다.
        # 별도 값으로 두면 같은 사실이 attendances 와 scores 두 곳에 갈린다.
        self.assertNotIn("지각", Attendance.Status.values)

    def test_status_has_no_withdrawn_value(self):
        # 설계 결정(도메인 1): 퇴원은 students.enrollment_status 에 단일 저장.
        # 회차별 출결과 학생 생애주기 분리 — attendances 에 '퇴원' 값 금지.
        self.assertNotIn("퇴원", Attendance.Status.values)
        self.assertIn("퇴원", Student.EnrollmentStatus.values)

    def test_ssot_contract_documented(self):
        # attendances 가 복습영상 자동지급·클리닉 대상·리포트 대상의 SSOT 라는
        # 계약이 모델 docstring 에 명시되어야 한다(소비 지점의 준거).
        self.assertIn("SSOT", Attendance.__doc__)

    def test_correction_fields_default_empty(self):
        # 설계: exam_taken NULL(잠정), marked_by NULL, updated_at NULL(정정 추적)
        att = Attendance.objects.create(
            session=self.session,
            student=self.student,
            status=Attendance.Status.ABSENT_ONSITE,
        )
        self.assertIsNone(att.exam_taken)
        self.assertIsNone(att.marked_by)
        self.assertIsNone(att.updated_at)
        self.assertIsNotNone(att.created_at)


class ExamQuestionTests(TestCase):
    def setUp(self):
        self.exam = make_exam()

    def test_exam_table_and_pk_column_follow_design(self):
        self.assertEqual(Exam._meta.db_table, "exams")
        self.assertEqual(Exam._meta.pk.column, "exam_id")

    def test_question_number_unique_per_exam(self):
        # 설계: UQ(exam_id, q_number)
        Question.objects.create(
            exam=self.exam, q_number=1, answer="3", points=Decimal("3.0"),
            unit_major="화학 반응의 규칙성",
        )
        with self.assertRaises(IntegrityError):
            Question.objects.create(
                exam=self.exam, q_number=1, answer="5", points=Decimal("2.0"),
                unit_major="화학 반응의 규칙성",
            )

    def test_question_format_value_set(self):
        # 설계: question_format = 내신형/수능형 (유사문항 조회 대상 DB 선택)
        self.assertEqual(set(Question.Format.values), {"내신형", "수능형"})
        self.assertEqual(Question._meta.db_table, "questions")
        self.assertEqual(Question._meta.pk.column, "question_id")


class AnswerSheetTests(TestCase):
    def setUp(self):
        self.exam = make_exam()

    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(AnswerSheet._meta.db_table, "answer_sheets")
        self.assertEqual(AnswerSheet._meta.pk.column, "sheet_id")

    def test_student_null_until_matched(self):
        # PRD 3.1.1: 매칭(원번+이름 대조) 전 student NULL
        sheet = AnswerSheet.objects.create(
            exam=self.exam, scan_image_path="omr/2026/0722/001.jpg",
            match_status=AnswerSheet.MatchStatus.MISSING,
        )
        self.assertIsNone(sheet.student)
        self.assertFalse(sheet.is_corrected)

    def test_match_status_value_set(self):
        # 설계: 정상/부분/불일치/미존재/중복/비정상 (PRD 3.1.1 대조 6분기)
        self.assertEqual(
            set(AnswerSheet.MatchStatus.values),
            {"정상", "부분", "불일치", "미존재", "중복", "비정상"},
        )

    def test_recognized_unique_id_holds_full_length_unique_id(self):
        """인식 컬럼은 원번이 가질 수 있는 길이를 담아야 한다(2026-07-29 개정).

        원번이 `{이름}{뒷4}` 가 되면서 이름 길이만큼 길어졌다 — 옛 5자리 전제로
        잡힌 폭이면 긴 이름 학생의 답안지 인식 결과를 저장할 수 없다.
        """
        unique_id = build_unique_id("무하마드알리", "01012344821")
        self.assertGreater(len(unique_id), 5)
        sheet = AnswerSheet.objects.create(
            exam=self.exam, scan_image_path="omr/2026/0722/002.jpg",
            match_status=AnswerSheet.MatchStatus.MATCHED,
            recognized_unique_id=unique_id, recognized_name="무하마드알리",
        )
        sheet.refresh_from_db()
        self.assertEqual(sheet.recognized_unique_id, unique_id)


class SheetAnswerTests(TestCase):
    def setUp(self):
        self.exam = make_exam()
        self.sheet = AnswerSheet.objects.create(
            exam=self.exam, scan_image_path="omr/001.jpg",
            match_status=AnswerSheet.MatchStatus.MATCHED,
        )
        self.question = Question.objects.create(
            exam=self.exam, q_number=1, answer="3", points=Decimal("3.0"),
            unit_major="화학 반응의 규칙성",
        )

    def test_unique_per_sheet_and_question(self):
        # 설계: UQ(sheet_id, question_id)
        SheetAnswer.objects.create(
            sheet=self.sheet, question=self.question, result=SheetAnswer.Result.CORRECT
        )
        with self.assertRaises(IntegrityError):
            SheetAnswer.objects.create(
                sheet=self.sheet, question=self.question,
                result=SheetAnswer.Result.WRONG,
            )

    def test_extra_practice_marks_default_false(self):
        # 설계: 추가 마킹란 2컬럼 NN 기본 false ('더 풀고 싶은 문항' — PRD 3.1.1)
        ans = SheetAnswer.objects.create(
            sheet=self.sheet, question=self.question, result=SheetAnswer.Result.WRONG
        )
        self.assertFalse(ans.extra_practice_marked)
        self.assertFalse(ans.extra_mark_corrected)
        self.assertEqual(SheetAnswer._meta.db_table, "sheet_answers")
        self.assertEqual(SheetAnswer._meta.pk.column, "id")


class ScoreTests(TestCase):
    def setUp(self):
        self.exam = make_exam()
        self.student = make_student()

    def test_unique_per_exam_and_student(self):
        # 설계: UQ(exam_id, student_id) — 한 학생·한 시험당 1줄
        Score.objects.create(exam=self.exam, student=self.student)
        with self.assertRaises(IntegrityError):
            Score.objects.create(exam=self.exam, student=self.student)

    def test_is_taken_defaults_true(self):
        # 설계: is_taken NN 기본 true — 클리닉 대상 판정(출석+응시+평균미달) 축
        score = Score.objects.create(exam=self.exam, student=self.student)
        self.assertTrue(score.is_taken)
        self.assertEqual(Score._meta.db_table, "scores")
        self.assertEqual(Score._meta.pk.column, "score_id")


class AssignmentTests(TestCase):
    def test_unique_per_session_and_student(self):
        # 설계: UQ(session_id, student_id)
        session, student = make_session(), make_student()
        Assignment.objects.create(session=session, student=student, done=True)
        with self.assertRaises(IntegrityError):
            Assignment.objects.create(session=session, student=student, done=False)

    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(Assignment._meta.db_table, "assignments")
        self.assertEqual(Assignment._meta.pk.column, "id")


class QuestionBankTests(TestCase):
    def test_bank_type_value_set(self):
        # 설계: bank_type = 내신형(개념확인)/수능형 — 2종 문제은행
        self.assertEqual(set(QuestionBankItem.BankType.values), {"내신형", "수능형"})

    def test_defaults(self):
        item = QuestionBankItem.objects.create(
            bank_type=QuestionBankItem.BankType.SCHOOL, content_path="bank/0001.png"
        )
        self.assertTrue(item.is_active)
        self.assertIsNone(item.labels)
        self.assertEqual(QuestionBankItem._meta.db_table, "question_bank_items")
        self.assertEqual(QuestionBankItem._meta.pk.column, "bank_item_id")

    def test_similar_map_unique_per_question_and_ordinal(self):
        # 설계: UQ(question_id, ordinal) — 문항당 유사문항 1·2번
        exam = make_exam()
        question = Question.objects.create(
            exam=exam, q_number=1, answer="3", points=Decimal("3.0"),
            unit_major="화학 반응의 규칙성",
        )
        bank1 = QuestionBankItem.objects.create(
            bank_type=QuestionBankItem.BankType.SCHOOL, content_path="bank/0001.png"
        )
        bank2 = QuestionBankItem.objects.create(
            bank_type=QuestionBankItem.BankType.SCHOOL, content_path="bank/0002.png"
        )
        QuestionSimilarMap.objects.create(
            question=question, similar_bank_item=bank1,
            ordinal=QuestionSimilarMap.Ordinal.FIRST,
        )
        with self.assertRaises(IntegrityError):
            QuestionSimilarMap.objects.create(
                question=question, similar_bank_item=bank2,
                ordinal=QuestionSimilarMap.Ordinal.FIRST,
            )

    def test_similar_map_ordinal_choices_1_to_2(self):
        # 설계: ordinal CHECK 1..2 — DB CHECK 금지 원칙이라 앱 레벨 choices 로 강제
        self.assertEqual(set(QuestionSimilarMap.Ordinal.values), {1, 2})
        self.assertEqual(QuestionSimilarMap._meta.db_table, "question_similar_maps")
        self.assertEqual(QuestionSimilarMap._meta.pk.column, "map_id")


class WeaknessCheckPdfTests(TestCase):
    def test_unique_per_exam_and_student_and_default_status(self):
        # 설계: UQ(exam_id, student_id) — 학생·시험당 1건, status 기본 생성대기
        exam, student = make_exam(), make_student()
        pdf = WeaknessCheckPdf.objects.create(exam=exam, student=student)
        self.assertEqual(pdf.status, WeaknessCheckPdf.Status.PENDING)
        self.assertEqual(pdf.status, "생성대기")
        with self.assertRaises(IntegrityError):
            WeaknessCheckPdf.objects.create(exam=exam, student=student)

    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(WeaknessCheckPdf._meta.db_table, "weakness_check_pdfs")
        self.assertEqual(WeaknessCheckPdf._meta.pk.column, "pdf_id")


class WorkbookSubmissionTests(TestCase):
    def test_create_with_optional_session_and_grade(self):
        # 설계: session_id NULL(-- 잠정 매핑키), performance_grade A/B/C NULL
        submission = WorkbookSubmission.objects.create(
            student=make_student(), image_path="workbook/2026/0722/3_1234.jpg"
        )
        self.assertIsNone(submission.session)
        self.assertIsNone(submission.performance_grade)
        self.assertEqual(
            set(WorkbookSubmission.PerformanceGrade.values), {"A", "B", "C"}
        )

    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(WorkbookSubmission._meta.db_table, "workbook_submissions")
        self.assertEqual(WorkbookSubmission._meta.pk.column, "submission_id")

    def test_ocr_columns_null_before_recognition(self):
        # 8-9 결정: 원번 기입칸 OCR 자동 매핑 — 인식 전(수기 플로우 포함) NULL
        submission = WorkbookSubmission.objects.create(
            student=make_student(), image_path="workbook/2026/0722/3_1234.jpg"
        )
        self.assertIsNone(submission.recognized_unique_id)
        self.assertIsNone(submission.recognized_name)
        self.assertIsNone(submission.match_status)

    def test_match_status_value_set(self):
        # answer_sheets 패턴 참조 — OCR 자동매칭/인식실패·불일치/수동확정 분기
        self.assertEqual(
            set(WorkbookSubmission.MatchStatus.values),
            {"자동매칭", "수동확정", "불일치", "인식실패"},
        )

    def test_ocr_recognition_recorded(self):
        submission = WorkbookSubmission.objects.create(
            student=make_student(),
            image_path="workbook/2026/0722/3_1234.jpg",
            recognized_unique_id="3_1234",
            match_status=WorkbookSubmission.MatchStatus.AUTO_MATCHED,
        )
        self.assertEqual(submission.match_status, "자동매칭")


class QuestionGuideVideoTests(TestCase):
    """grades 각주 ① 이행 — guide_video 를 videos.Video FK 로 승격."""

    def test_guide_video_is_fk_to_videos(self):
        from apps.videos.models import Video

        field = Question._meta.get_field("guide_video")
        self.assertEqual(field.related_model, Video)
        self.assertEqual(field.column, "guide_video_id")  # 설계 컬럼명 유지
        self.assertTrue(field.null)

    def test_question_survives_video_deletion(self):
        # 영상 삭제로 문항(채점기준)이 사라지면 안 된다 — SET_NULL
        from apps.videos.models import Video

        exam = make_exam()
        video = Video.objects.create(title="1주차 복습영상")
        question = Question.objects.create(
            exam=exam, q_number=1, answer="3", points=Decimal("3.0"),
            unit_major="화학 반응의 규칙성", guide_video=video,
        )
        video.delete()
        question.refresh_from_db()
        self.assertIsNone(question.guide_video)
