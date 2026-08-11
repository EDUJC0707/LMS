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

from . import omr_ingest
from .models import AnswerSheet, Exam, Question, Score
from .omr import card, normalize
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
