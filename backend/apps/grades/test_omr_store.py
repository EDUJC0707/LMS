"""OMR 판독 영속 서비스 테스트 — 멱등 저장·보정 보존 (PRD 3.1.1).

검증 축(계약은 omr_store 모듈 docstring):
- 판정 저장: 빈칸=무응답, 단일=키 대조 즉시 정오, 복수=복수마킹("1,3")
- 멱등: 같은 (exam, scan_image_path) 재저장이 행을 늘리지 않고 수렴한다
- 사람 우선: is_corrected 시트·행은 재판독이 덮지 못한다
- 보류: `비정상` 시트 행만 — 문항 행 없음, 식별값 미저장
- 문항 입력 전: 시트만 저장 → 입력 후 재저장이 채점까지 수렴
- exam_admin 처리 상태 파생(채점전/보정필요/완료)이 저장 후에도 참
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from . import exam_admin, omr_store
from .models import AnswerSheet, Exam, Question, Score, SheetAnswer
from .test_grade_report_api import make_student

#: 표준 판독 — 1번 정답(키 1), 2번 오답(키 3), 3번 빈칸.
READINGS = {1: (1,), 2: (2,), 3: ()}
SCAN = "omr/5/0a1b2c3d4e5f60718293a4b5.png"


class OmrStoreFixtureMixin:
    @classmethod
    def setUpTestData(cls):
        cls.student = make_student("stu-omr-a", "김서연")
        cls.other_student = make_student("stu-omr-b", "이민준")
        cls.exam = Exam.objects.create(
            name="오메가블랙 5회", exam_date=datetime.date(2026, 8, 5), round_no=5
        )
        cls.q1 = Question.objects.create(
            exam=cls.exam, q_number=1, answer="1", points=Decimal("5.0"), unit_major="산염기"
        )
        cls.q2 = Question.objects.create(
            exam=cls.exam, q_number=2, answer="3", points=Decimal("5.0"), unit_major="산염기"
        )
        cls.q3 = Question.objects.create(
            exam=cls.exam, q_number=3, answer="5", points=Decimal("5.0"), unit_major="산화환원"
        )

    def store(self, readings, path=SCAN, **kwargs):
        if readings is not None:
            kwargs.setdefault("student", self.student)
            kwargs.setdefault("match_status", AnswerSheet.MatchStatus.MATCHED)
            kwargs.setdefault("recognized_matching_key", "김서연0001")
            kwargs.setdefault("recognized_name", "김서연")
        return omr_store.store_sheet(self.exam, path, readings, **kwargs)

    def answer(self, sheet, question):
        return SheetAnswer.objects.get(sheet=sheet, question=question)


class StoreVerdictTests(OmrStoreFixtureMixin, TestCase):
    """엔진 출력 → 행 판정 — 판독 사실은 그대로, 단일 마킹은 키 대조."""

    def test_first_store_creates_sheet_and_graded_answers(self):
        sheet, summary = self.store(READINGS)

        self.assertEqual(summary, {
            "created": True,
            "answers_written": 3,
            "answers_kept": 0,
            "answers_removed": 0,
            "missing_questions": [],
            "scored": 5.0,
        })
        self.assertEqual(sheet.exam_id, self.exam.pk)
        self.assertEqual(sheet.student_id, self.student.pk)
        self.assertEqual(sheet.match_status, AnswerSheet.MatchStatus.MATCHED)
        self.assertEqual(sheet.recognized_matching_key, "김서연0001")
        self.assertFalse(sheet.is_corrected)
        a1, a2, a3 = (self.answer(sheet, q) for q in (self.q1, self.q2, self.q3))
        self.assertEqual((a1.marked, a1.result), ("1", SheetAnswer.Result.CORRECT))
        self.assertEqual((a2.marked, a2.result), ("2", SheetAnswer.Result.WRONG))
        self.assertEqual((a3.marked, a3.result), (None, SheetAnswer.Result.BLANK))
        # 추가 마킹란은 엔진이 아직 읽지 않는다 — 기본값 그대로.
        self.assertFalse(a1.extra_practice_marked)
        self.assertFalse(a1.is_corrected)

    def test_multi_mark_is_stored_for_the_human_to_decide(self):
        """복수마킹은 정오를 정하지 않는다 — 겹친 값 전부를 남긴다."""
        sheet, _ = self.store({1: (3, 1), 2: (2,), 3: ()})

        a1 = self.answer(sheet, self.q1)
        self.assertEqual((a1.marked, a1.result), ("1,3", SheetAnswer.Result.MULTI))

    def test_readings_beyond_exam_questions_are_deferred(self):
        """카드 20행 중 시험 문항 밖의 행 — 문항이 없으니 못 적고 보고만."""
        _, summary = self.store({1: (1,), 17: (2,), 18: ()})

        self.assertEqual(summary["answers_written"], 1)
        self.assertEqual(summary["missing_questions"], [17, 18])

    def test_readings_require_match_status(self):
        with self.assertRaises(ValueError):
            omr_store.store_sheet(self.exam, SCAN, READINGS)


class HoldTests(OmrStoreFixtureMixin, TestCase):
    """보류 장 — 사람이 봐야 하므로 행은 남기되 `비정상` 으로."""

    def test_hold_stores_invalid_sheet_without_answers(self):
        sheet, summary = self.store(
            None, student=self.student, match_status=AnswerSheet.MatchStatus.MATCHED,
            recognized_matching_key="김서연0001", recognized_name="김서연",
        )

        self.assertEqual(sheet.match_status, AnswerSheet.MatchStatus.INVALID)
        # 보류는 장 통계를 못 믿는다는 판정 — 같은 통계로 읽은 식별값도 안 싣는다.
        self.assertIsNone(sheet.student)
        self.assertIsNone(sheet.recognized_matching_key)
        self.assertIsNone(sheet.recognized_name)
        self.assertEqual(sheet.answers.count(), 0)
        self.assertEqual(summary["answers_written"], 0)

    def test_hold_reread_drops_machine_rows_but_not_corrected_ones(self):
        """판독됐던 장이 보류로 재판독되면 — 기계 행만 걷어낸다."""
        sheet, _ = self.store(READINGS)
        corrected = self.answer(sheet, self.q2)
        corrected.marked = "3"
        corrected.result = SheetAnswer.Result.CORRECT
        corrected.is_corrected = True
        corrected.save()

        reread, summary = self.store(None)

        self.assertEqual(reread.pk, sheet.pk)
        self.assertEqual(reread.match_status, AnswerSheet.MatchStatus.INVALID)
        self.assertEqual(summary["answers_removed"], 2)
        self.assertEqual(summary["answers_kept"], 1)
        survivor = self.answer(reread, self.q2)
        self.assertEqual((survivor.marked, survivor.result), ("3", SheetAnswer.Result.CORRECT))
        self.assertTrue(survivor.is_corrected)
        self.assertEqual(reread.answers.count(), 1)


class ReuploadTests(OmrStoreFixtureMixin, TestCase):
    """멱등 — 같은 스캔 파일은 몇 번을 저장해도 한 장이다."""

    def test_same_scan_converges_to_one_sheet(self):
        sheet, _ = self.store(READINGS)
        first_pks = set(sheet.answers.values_list("pk", flat=True))

        again, summary = self.store(READINGS)

        self.assertEqual(again.pk, sheet.pk)
        self.assertFalse(summary["created"])
        self.assertEqual(AnswerSheet.objects.count(), 1)
        self.assertEqual(set(again.answers.values_list("pk", flat=True)), first_pks)

    def test_reread_updates_uncorrected_rows(self):
        """엔진이 좋아져 판독이 바뀌면 — 마지막 판독으로 수렴한다."""
        self.store({1: (2,), 2: (2,), 3: ()})

        sheet, _ = self.store(READINGS)

        a1 = self.answer(sheet, self.q1)
        self.assertEqual((a1.marked, a1.result), ("1", SheetAnswer.Result.CORRECT))

    def test_two_scans_of_the_same_page_are_two_sheets(self):
        """물리적으로 두 번 스캔된 지면은 바이트가 달라 두 장이다 — 같은 학생에
        두 장이 걸려 사람 눈에 띄는 것이 수렴 지점(모듈 docstring)."""
        self.store(READINGS, path="omr/5/aaaa.png")
        self.store(READINGS, path="omr/5/bbbb.png")

        self.assertEqual(AnswerSheet.objects.count(), 2)


class CorrectionPreservedTests(OmrStoreFixtureMixin, TestCase):
    """is_corrected = 소유권 이전 — 재판독은 사람 것을 덮지 못한다."""

    def test_corrected_answer_survives_reread(self):
        sheet, _ = self.store(READINGS)
        row = self.answer(sheet, self.q2)
        row.marked = "3"
        row.result = SheetAnswer.Result.CORRECT
        row.is_corrected = True
        row.save()

        _, summary = self.store(READINGS)

        self.assertEqual(summary["answers_kept"], 1)
        self.assertEqual(summary["answers_written"], 2)
        row.refresh_from_db()
        self.assertEqual((row.marked, row.result), ("3", SheetAnswer.Result.CORRECT))
        self.assertTrue(row.is_corrected)

    def test_corrected_sheet_identity_survives_reread(self):
        sheet, _ = self.store(
            READINGS, student=None, match_status=AnswerSheet.MatchStatus.MISMATCH
        )
        sheet.student = self.other_student
        sheet.match_status = AnswerSheet.MatchStatus.MATCHED
        sheet.is_corrected = True
        sheet.save()

        reread, _ = self.store(
            READINGS, student=None, match_status=AnswerSheet.MatchStatus.MISMATCH
        )

        self.assertEqual(reread.student_id, self.other_student.pk)
        self.assertEqual(reread.match_status, AnswerSheet.MatchStatus.MATCHED)
        self.assertTrue(reread.is_corrected)

    def test_corrected_sheet_still_gets_answer_updates(self):
        """시트 보정은 "누구 것인가"의 확정 — 미보정 문항 행은 계속 수렴한다."""
        sheet, _ = self.store({1: (2,), 2: (2,), 3: ()})
        sheet.is_corrected = True
        sheet.save()

        _, summary = self.store(READINGS)

        self.assertEqual(summary["answers_written"], 3)
        a1 = self.answer(sheet, self.q1)
        self.assertEqual((a1.marked, a1.result), ("1", SheetAnswer.Result.CORRECT))


class BeforeQuestionsTests(OmrStoreFixtureMixin, TestCase):
    """문항 입력(=정답 키) 전 스캔 — 시트만 저장, 입력 후 재판독이 채운다."""

    def test_sheet_stored_before_questions_then_converges(self):
        bare_exam = Exam.objects.create(
            name="오메가블랙 6회", exam_date=datetime.date(2026, 8, 12), round_no=6
        )

        sheet, summary = omr_store.store_sheet(
            bare_exam, SCAN, READINGS,
            student=self.student, match_status=AnswerSheet.MatchStatus.MATCHED,
        )

        self.assertEqual(summary["answers_written"], 0)
        self.assertEqual(summary["missing_questions"], [1, 2, 3])
        self.assertEqual(sheet.answers.count(), 0)

        Question.objects.create(
            exam=bare_exam, q_number=1, answer="1", points=Decimal("5.0"), unit_major="산염기"
        )
        Question.objects.create(
            exam=bare_exam, q_number=2, answer="3", points=Decimal("5.0"), unit_major="산염기"
        )

        reread, summary = omr_store.store_sheet(
            bare_exam, SCAN, READINGS,
            student=self.student, match_status=AnswerSheet.MatchStatus.MATCHED,
        )

        self.assertEqual(reread.pk, sheet.pk)
        self.assertEqual(summary["answers_written"], 2)
        self.assertEqual(summary["missing_questions"], [3])
        results = dict(reread.answers.values_list("question__q_number", "result"))
        self.assertEqual(results, {1: SheetAnswer.Result.CORRECT, 2: SheetAnswer.Result.WRONG})

    def test_blank_answer_question_is_deferred_too(self):
        """키가 빈 문항 행(입력 도중 상태)은 없는 것과 같다 — 반쯤 채점하지 않는다."""
        Question.objects.filter(pk=self.q2.pk).update(answer="")

        _, summary = self.store(READINGS)

        self.assertEqual(summary["answers_written"], 2)
        self.assertEqual(summary["missing_questions"], [2])


class ProcessingStatusDerivationTests(OmrStoreFixtureMixin, TestCase):
    """exam_admin 의 파생 3분기가 이 모듈의 쓰기 이후에도 참인가."""

    def exam_row(self):
        rows = exam_admin.build_exam_list()["exams"]
        return next(row for row in rows if row["exam_id"] == self.exam.pk)

    def test_store_never_advances_processing_status(self):
        """정답 키가 없으면 점수가 안 생기고, 그래서 여전히 채점전이다.

        저장 순서가 뒤집혀도(문항 입력 전에 batch 를 스캔) 상태가 거짓말하지
        않는다 — 읽기는 했지만 채점할 기준이 없으면 채점된 것이 아니다.
        """
        Question.objects.filter(exam=self.exam).update(answer="")
        self.store(READINGS)
        hold, _ = self.store(None, path="omr/5/held.png")

        self.assertEqual(self.exam_row()["processing_status"], "채점전")

        # 채점(집계 슬라이스)이 scores 를 만들면 — 미보정 보류 장이 곧 보정필요.
        Score.objects.create(exam=self.exam, student=self.student, total_score=Decimal("10"))
        row = self.exam_row()
        self.assertEqual(row["processing_status"], "보정필요")
        self.assertEqual(row["pending_sheet_count"], 1)

        # 사람이 보류 장을 보정하면 완료로.
        hold.is_corrected = True
        hold.save(update_fields=["is_corrected"])
        self.assertEqual(self.exam_row()["processing_status"], "완료")
