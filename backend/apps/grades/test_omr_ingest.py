"""스캔 묶음 인제스트 — 판독·매칭·저장을 한 번에 (PRD 3.1.1).

실물 스캔은 개인정보라 커밋할 수 없으므로 페이지 공급을 갈아 끼워 검사한다.
**스트림 추출 자체(page_images)는 실물 480쪽으로 검증했다** — pdfimages 가
뽑은 바이트와 md5 가 같다(2026-08-11).
"""
import datetime
from decimal import Decimal
from unittest import mock

import cv2
import numpy as np
from django.test import TestCase

from apps.accounts.models import Student

from . import exam_admin, omr_ingest, omr_store
from .models import AnswerSheet, Exam, Question, Score, SheetAnswer
from .omr import card, normalize
from .omr import sheet as sheet_module
from .test_grade_report_api import make_student

CARD_CORNERS = np.array(
    [[1525.0, 120.0], [1525.0, 2225.0], [115.0, 2225.0], [115.0, 120.0]], dtype=np.float64
)
MARKS = (
    ((115.0, 120.0), (21, 18)),
    ((1525.0, 120.0), (36, 18)),
    ((1525.0, 2225.0), (36, 18)),
    ((115.0, 2225.0), (21, 18)),
)


def synthetic_page(answers):
    """마커 넷 + 답란만 있는 합성 카드 JPEG 바이트.

    빈 칸에도 인쇄 글리프 잉크를 남긴다 — 티 없이 깨끗한 카드를 그리면 줄
    기준선이 바닥으로 떨어져 "격자가 지면 밖" 보호장치가 정상 장에서 터진다.
    """
    image = np.full((2335, 1651), 255, dtype=np.uint8)
    for (cx, cy), (w, h) in MARKS:
        x0, y0 = int(round(cx - w / 2)), int(round(cy - h / 2))
        image[y0 : y0 + h, x0 : x0 + w] = 64
    frame = normalize.CardFrame(CARD_CORNERS)
    for (question, choice), (u, v) in card.answer_cells():
        x, y = frame.to_source(u, v)
        grey = 40 if answers.get(question) == choice else 215
        cv2.ellipse(image, (int(round(x)), int(round(y))), (13, 8), 0, 0, 360, grey, -1)
    return cv2.imencode(".jpg", image)[1].tobytes()


class IngestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.exam = Exam.objects.create(name="8월 미니", exam_date=datetime.date(2026, 8, 11))
        for number in range(1, 17):
            Question.objects.create(
                exam=cls.exam, q_number=number, answer="3", points=Decimal("1.0")
            )
        cls.student = make_student("stu-ingest", "김서연")

    def ingest(self, pages):
        with mock.patch.object(omr_ingest, "page_images", return_value=iter(pages)):
            return omr_ingest.ingest_pdf(self.exam, object(), question_count=16)

    def test_every_page_becomes_a_sheet(self):
        answers = {question: 3 for question in range(1, 17)}
        pages = [synthetic_page(answers), synthetic_page({**answers, 1: 2})]

        summary = self.ingest(pages)

        self.assertEqual(summary["pages"], 2)
        self.assertEqual(summary["read"], 2)
        self.assertEqual(summary["held"], 0)
        self.assertEqual(AnswerSheet.objects.filter(exam=self.exam).count(), 2)

    def test_the_same_pdf_twice_converges(self):
        """중간에 끊겨 다시 올려도 장이 늘지 않는다 — 경로가 내용 주소다."""
        pages = [synthetic_page({question: 3 for question in range(1, 17)})]
        self.ingest(pages)

        self.ingest(list(pages))

        self.assertEqual(AnswerSheet.objects.filter(exam=self.exam).count(), 1)

    def test_an_unreadable_page_is_held_not_guessed(self):
        """카드가 아닌 지면은 답을 지어내지 않고 사람에게 넘긴다."""
        blank = cv2.imencode(".jpg", np.full((2335, 1651), 255, np.uint8))[1].tobytes()

        summary = self.ingest([blank])

        self.assertEqual(summary["held"], 1)
        sheet = AnswerSheet.objects.get(exam=self.exam)
        self.assertEqual(sheet.match_status, AnswerSheet.MatchStatus.INVALID)
        self.assertEqual(sheet.answers.count(), 0)

    def test_a_matched_sheet_gets_a_score(self):
        """명단에 있는 학생이면 그 자리에서 점수까지 난다."""
        Student.objects.filter(pk=self.student.pk).update(matching_key="김서연0001")
        answers = {question: 3 for question in range(1, 17)}
        with mock.patch(
            "apps.grades.omr_ingest.sheet.read_sheet"
        ) as read_sheet:
            reading = mock.Mock(
                held=None,
                answers={q: (3,) for q in range(1, 17)},
                phone="0001",
                matching_key="김서연0001",
            )
            reading.name = "김서연"  # Mock(name=...) 은 속성이 아니라 목 이름이다
            read_sheet.return_value = reading
            summary = self.ingest([synthetic_page(answers)])

        self.assertEqual(summary["matched"], 1)
        score = Score.objects.get(exam=self.exam, student=self.student)
        self.assertEqual(float(score.total_score), 16.0)


class BatchTaskTests(TestCase):
    """업로드는 태스크로 넘어간다 — 뷰는 파일만 놓고 즉시 답한다."""

    @classmethod
    def setUpTestData(cls):
        cls.exam = Exam.objects.create(name="8월 배치", exam_date=datetime.date(2026, 8, 11))
        Question.objects.create(exam=cls.exam, q_number=1, answer="3", points=Decimal("1.0"))

    def test_task_reads_the_stored_pdf_and_cleans_it_up(self):
        """PDF 는 스토리지에 두고 경로만 넘긴다 — 27MB 를 브로커에 싣지 않는다.

        판독이 끝나면 장별 이미지가 이미 다 들어갔으므로 원본은 지운다.
        """
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        from . import tasks

        path = default_storage.save("omr-upload/t/x.pdf", ContentFile(b"%PDF-1.4\n"))
        page = synthetic_page({1: 3})
        with mock.patch.object(omr_ingest, "page_images", return_value=iter([page])):
            summary = tasks.ingest_omr_batch(self.exam.pk, path, 1)

        self.assertEqual(summary["pages"], 1)
        self.assertFalse(default_storage.exists(path))


class MockExamIngestTests(TestCase):
    """모의고사는 지면이 다르다 — 문항이 없고 자기보고 점수만 들어온다."""

    @classmethod
    def setUpTestData(cls):
        cls.exam = Exam.objects.create(
            name="6월 모의평가",
            exam_date=datetime.date(2026, 6, 12),
            kind=Exam.Kind.MOCK,
        )
        cls.student = make_student("stu-mock", "김서연")

    def ingest(self, readings):
        """조사 카드 판독을 갈아 끼운다 — 실물은 개인정보라 커밋할 수 없다."""
        pages = [b"page"] * len(readings)
        with (
            mock.patch.object(omr_ingest, "page_images", return_value=iter(pages)),
            mock.patch("apps.grades.omr_ingest.cv2.imdecode", return_value=None),
            mock.patch(
                "apps.grades.omr_ingest.sheet.read_survey", side_effect=readings
            ),
        ):
            return omr_ingest.ingest_pdf(self.exam, object(), question_count=0)

    def survey(self, score, name=None, phone=None):
        reading = mock.Mock(
            held=None,
            score=score,
            phone=phone,
            matching_key=f"{name}{phone}" if name and phone else None,
        )
        reading.name = name  # Mock(name=...) 은 속성이 아니라 목 이름이다
        return reading

    def test_a_matched_card_becomes_a_score_without_any_questions(self):
        """자기보고 점수가 곧 성적이다 — 셀 문항이 없다."""
        Student.objects.filter(pk=self.student.pk).update(matching_key="김서연0001")

        summary = self.ingest([self.survey(46, "김서연", "0001")])

        self.assertEqual(summary["matched"], 1)
        score = Score.objects.get(exam=self.exam, student=self.student)
        self.assertEqual(float(score.total_score), 46.0)
        # 만점은 조사 카드가 말하지 않는다 — 지어내지 않는다.
        self.assertIsNone(score.max_score)
        self.assertEqual(AnswerSheet.objects.get(exam=self.exam).recognized_score, 46)

    def test_an_unmatched_card_keeps_the_score_for_the_assistant(self):
        """주인을 못 찾아도 판독은 남는다 — 조교가 지면과 대조할 근거다."""
        summary = self.ingest([self.survey(38, "박모름", "0002")])

        self.assertEqual(summary["needs_review"], 1)
        sheet_row = AnswerSheet.objects.get(exam=self.exam)
        self.assertEqual(sheet_row.recognized_score, 38)
        self.assertIsNone(sheet_row.student)
        self.assertFalse(Score.objects.filter(exam=self.exam).exists())

    def unmarked(self):
        """버블이 하나도 없는 장 — 실물 94장 중 34장이 이랬다."""
        return mock.Mock(held=sheet_module.CARD_UNMARKED, score=None)

    def test_holds_are_counted_by_reason(self):
        """"보류 34장"이 아니라 "34명이 버블을 안 칠했다"를 알려 줘야 한다."""
        with (
            mock.patch("apps.grades.omr_ingest.ocr.read_score", return_value=None),
            mock.patch("apps.grades.omr_ingest.sheet.score_box_image", return_value=b"png"),
        ):
            summary = self.ingest([self.unmarked(), self.survey(44, "김서연", "0001")])

        self.assertEqual(summary["held"], 1)
        self.assertEqual(summary["holds"], {sheet_module.CARD_UNMARKED: 1})

    def test_ocr_rescues_a_card_with_only_handwriting(self):
        """마킹이 없어도 손글씨 점수는 남아 있다 — 실물 34장 중 20장을 그렇게 건졌다."""
        with (
            mock.patch("apps.grades.omr_ingest.ocr.read_score", return_value=38) as read,
            mock.patch("apps.grades.omr_ingest.sheet.score_box_image", return_value=b"png"),
        ):
            summary = self.ingest([self.unmarked()])

        read.assert_called_once_with(b"png")
        self.assertEqual(summary["held"], 0)
        self.assertEqual(AnswerSheet.objects.get(exam=self.exam).recognized_score, 38)

    def test_an_ocr_rescued_card_still_needs_a_person_for_the_student(self):
        """점수는 건져도 신원은 없다 — 성명·번호 격자도 비어 있다."""
        with (
            mock.patch("apps.grades.omr_ingest.ocr.read_score", return_value=38),
            mock.patch("apps.grades.omr_ingest.sheet.score_box_image", return_value=b"png"),
        ):
            summary = self.ingest([self.unmarked()])

        self.assertEqual(summary["needs_review"], 1)
        row = AnswerSheet.objects.get(exam=self.exam)
        self.assertIsNone(row.student)
        self.assertIsNone(row.recognized_name)
        self.assertFalse(Score.objects.filter(exam=self.exam).exists())

    def test_an_unreadable_card_stays_held(self):
        """OCR 도 못 읽으면(백지·저신뢰) 그대로 보류다 — 지어내지 않는다."""
        with (
            mock.patch("apps.grades.omr_ingest.ocr.read_score", return_value=None),
            mock.patch("apps.grades.omr_ingest.sheet.score_box_image", return_value=b"png"),
        ):
            summary = self.ingest([self.unmarked()])

        self.assertEqual(summary["held"], 1)
        self.assertIsNone(AnswerSheet.objects.get(exam=self.exam).recognized_score)

    def test_an_assistant_can_correct_the_score(self):
        """조사 카드에서 고칠 것은 점수 한 칸뿐이다(문항이 없다)."""
        Student.objects.filter(pk=self.student.pk).update(matching_key="김서연0001")
        self.ingest([self.survey(46, "김서연", "0001")])
        row = AnswerSheet.objects.get(exam=self.exam)

        omr_store.correct_sheet(row, score=44)

        row.refresh_from_db()
        self.assertEqual(row.recognized_score, 44)
        self.assertTrue(row.is_corrected)
        self.assertEqual(float(Score.objects.get(exam=self.exam).total_score), 44.0)

    def test_an_ocr_score_is_marked_as_handwriting(self):
        """조교가 버블 판독인지 손글씨인지 알고 봐야 한다 — 값만으로는 못 가른다."""
        with (
            mock.patch("apps.grades.omr_ingest.ocr.read_score", return_value=38),
            mock.patch("apps.grades.omr_ingest.sheet.score_box_image", return_value=b"png"),
        ):
            self.ingest([self.unmarked()])

        self.assertTrue(AnswerSheet.objects.get(exam=self.exam).score_from_handwriting)

    def test_a_bubble_score_is_not_marked_as_handwriting(self):
        self.ingest([self.survey(46, "김서연", "0001")])

        self.assertFalse(AnswerSheet.objects.get(exam=self.exam).score_from_handwriting)

    def test_an_assistant_edit_clears_the_handwriting_mark(self):
        """사람이 적은 값은 더 이상 OCR 판독이 아니다."""
        with (
            mock.patch("apps.grades.omr_ingest.ocr.read_score", return_value=38),
            mock.patch("apps.grades.omr_ingest.sheet.score_box_image", return_value=b"png"),
        ):
            self.ingest([self.unmarked()])
        row = AnswerSheet.objects.get(exam=self.exam)

        omr_store.correct_sheet(row, score=41)

        row.refresh_from_db()
        self.assertEqual(row.recognized_score, 41)
        self.assertFalse(row.score_from_handwriting)


class RegradeTests(TestCase):
    """정답 키가 바뀌면 이미 채점된 결과도 따라와야 한다."""

    @classmethod
    def setUpTestData(cls):
        cls.exam = Exam.objects.create(name="8월 재채점", exam_date=datetime.date(2026, 8, 12))
        cls.student = make_student("stu-regrade", "김서연")

    def key(self, answer):
        return exam_admin.save_questions(self.exam, [{"q_number": 1, "answer": answer}])

    def sheet_with_mark(self, marked):
        row = AnswerSheet.objects.create(
            exam=self.exam, student=self.student, scan_image_path="omr/x.jpg",
            match_status=AnswerSheet.MatchStatus.MATCHED,
        )
        question = Question.objects.get(exam=self.exam, q_number=1)
        SheetAnswer.objects.create(
            sheet=row, question=question, marked=marked,
            result=SheetAnswer.Result.WRONG,
        )
        return row

    def test_fixing_the_key_rescores_stored_marks(self):
        """조교가 정답을 잘못 넣었다가 고쳤다 — 저장된 정오가 따라와야 한다."""
        self.key("2")
        self.sheet_with_mark("3")

        self.key("3")

        row = SheetAnswer.objects.get(sheet__exam=self.exam)
        self.assertEqual(row.result, SheetAnswer.Result.CORRECT)
        self.assertEqual(float(Score.objects.get(exam=self.exam).total_score), 1.0)

    def test_a_corrected_row_still_follows_the_key(self):
        """보정 잠금은 **판독**의 소유권이다 — 정답 여부는 키가 정한다."""
        self.key("2")
        row = self.sheet_with_mark("3")
        SheetAnswer.objects.filter(sheet=row).update(is_corrected=True)

        self.key("3")

        answer = SheetAnswer.objects.get(sheet=row)
        self.assertEqual(answer.result, SheetAnswer.Result.CORRECT)
        self.assertEqual(answer.marked, "3", "사람이 적은 마킹은 그대로다")


class RereadTests(TestCase):
    """저장된 스캔으로 다시 판독 — PDF 를 또 올리지 않는다."""

    @classmethod
    def setUpTestData(cls):
        cls.exam = Exam.objects.create(name="8월 재판독", exam_date=datetime.date(2026, 8, 12))

    def test_a_batch_uploaded_before_the_key_can_be_read_again(self):
        """키 없이 먼저 올린 배치 — 키를 넣고 다시 돌리면 그때부터 채점된다."""
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        page = synthetic_page({q: 3 for q in range(1, 17)})
        with mock.patch.object(omr_ingest, "page_images", return_value=iter([page])):
            omr_ingest.ingest_pdf(self.exam, object(), question_count=16)
        # 키가 없어 문항 행이 하나도 안 생긴다(FK — questions.answer 가 NOT NULL)
        self.assertEqual(SheetAnswer.objects.filter(sheet__exam=self.exam).count(), 0)
        path = AnswerSheet.objects.get(exam=self.exam).scan_image_path
        if not default_storage.exists(path):
            default_storage.save(path, ContentFile(page))

        exam_admin.save_questions(
            self.exam, [{"q_number": q, "answer": "3"} for q in range(1, 17)]
        )
        summary = omr_ingest.reread_exam(self.exam, question_count=16)

        self.assertEqual(summary["pages"], 1)
        self.assertEqual(SheetAnswer.objects.filter(sheet__exam=self.exam).count(), 16)

    def test_rereading_does_not_duplicate_sheets(self):
        """저장이 멱등이라 몇 번을 돌려도 장이 안 늘어난다."""
        from django.core.files.base import ContentFile
        from django.core.files.storage import default_storage

        page = synthetic_page({1: 3})
        with mock.patch.object(omr_ingest, "page_images", return_value=iter([page])):
            omr_ingest.ingest_pdf(self.exam, object(), question_count=1)
        path = AnswerSheet.objects.get(exam=self.exam).scan_image_path
        if not default_storage.exists(path):
            default_storage.save(path, ContentFile(page))

        omr_ingest.reread_exam(self.exam, question_count=1)
        omr_ingest.reread_exam(self.exam, question_count=1)

        self.assertEqual(AnswerSheet.objects.filter(exam=self.exam).count(), 1)
