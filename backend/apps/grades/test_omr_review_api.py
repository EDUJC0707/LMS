"""OMR 보정 화면 API — 조교가 기계를 이기는 자리 (PRD 3.1.1).

검증 축:
- 목록 순서: 손볼 장이 먼저. 확정된 정상 장은 뒤로
- 상세: 정답 키 전량에 판독을 얹는다 — 보류라 행이 없어도 빈 줄이 나온다
- PATCH: 주인 확정·문항 정정·확인. 손댄 것은 `is_corrected` 로 잠기고
  총점은 그 자리에서 다시 난다
- 스캔 이미지는 인증 뒤에서만 흐른다 — 지면에 실명·전화 뒷자리가 있다
"""
import datetime
import json
from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase

from apps.accounts.features import FeatureKey
from apps.accounts.models import StaffFeatureGrant, User

from .models import AnswerSheet, Exam, Question, Score, SheetAnswer
from .test_grade_report_api import make_student, make_user

_MS = AnswerSheet.MatchStatus
_R = SheetAnswer.Result


class SheetReviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user("adm-omr", User.Role.ADMIN, name="관리자")
        cls.outsider = make_user("ast-omr", User.Role.ASSISTANT, name="조교")
        StaffFeatureGrant.objects.create(
            user=make_user("ast-omr-ok", User.Role.ASSISTANT),
            feature_key=FeatureKey.GRADE_PROCESSING,
            is_granted=True,
        )
        cls.student = make_student("stu-omr", "김서연")
        cls.exam = Exam.objects.create(name="8월 미니", exam_date=datetime.date(2026, 8, 11))
        cls.q1 = Question.objects.create(
            exam=cls.exam, q_number=1, answer="3", points=Decimal("10.0")
        )
        cls.q2 = Question.objects.create(
            exam=cls.exam, q_number=2, answer="4", points=Decimal("10.0")
        )
        # 확정된 정상 장 — 조교가 볼 일이 없다
        cls.settled = AnswerSheet.objects.create(
            exam=cls.exam,
            student=cls.student,
            scan_image_path="omr/settled.jpg",
            match_status=_MS.MATCHED,
            is_corrected=True,
        )
        # 이름은 읽혔는데 명단에 없다 — 주인을 사람이 골라야 한다
        cls.orphan = AnswerSheet.objects.create(
            exam=cls.exam,
            scan_image_path="omr/orphan.jpg",
            match_status=_MS.MISSING,
            recognized_name="박모름",
            recognized_matching_key="박모름0002",
        )
        SheetAnswer.objects.create(sheet=cls.orphan, question=cls.q1, marked="3", result=_R.CORRECT)
        SheetAnswer.objects.create(sheet=cls.orphan, question=cls.q2, marked=None, result=_R.BLANK)

    def setUp(self):
        self.client.force_login(self.admin)

    def sheet_url(self, sheet):
        return f"/api/admin/sheets/{sheet.pk}"

    def patch(self, sheet, body):
        return self.client.patch(
            self.sheet_url(sheet), data=json.dumps(body), content_type="application/json"
        )

    def test_needs_review_comes_first(self):
        """조교는 손볼 장부터 본다 — 확정된 정상 장은 목록 뒤로 민다."""
        res = self.client.get(f"/api/admin/exams/{self.exam.pk}/sheets")

        ids = [row["sheet_id"] for row in res.json()["sheets"]]
        self.assertEqual(ids, [self.orphan.pk, self.settled.pk])

    def test_the_payload_says_where_a_score_came_from(self):
        """배지가 이 값으로 갈린다 — 페이로드에 안 실리면 화면에서 조용히 안 뜬다."""
        AnswerSheet.objects.filter(pk=self.orphan.pk).update(
            recognized_score=38, score_from_handwriting=True
        )

        row = next(
            r
            for r in self.client.get(f"/api/admin/exams/{self.exam.pk}/sheets").json()["sheets"]
            if r["sheet_id"] == self.orphan.pk
        )
        detail = self.client.get(self.sheet_url(self.orphan)).json()

        self.assertTrue(row["score_from_handwriting"])
        self.assertTrue(detail["score_from_handwriting"])
        self.assertEqual(detail["recognized_score"], 38)

    def test_detail_lists_every_question_even_without_a_reading(self):
        """보류 장은 행이 하나도 없다 — 그때야말로 손으로 채울 줄이 필요하다."""
        res = self.client.get(self.sheet_url(self.settled))

        rows = res.json()["questions"]
        self.assertEqual([row["q_number"] for row in rows], [1, 2])
        self.assertEqual([row["marked"] for row in rows], [None, None])

    def test_assigning_a_student_settles_the_sheet_and_scores_it(self):
        """기계가 못 고른 주인을 사람이 골랐다 — 6분기를 더 볼 것이 없다."""
        res = self.patch(self.orphan, {"student_id": self.student.pk})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["match_status"], _MS.MATCHED)
        self.assertTrue(res.json()["is_corrected"])
        score = Score.objects.get(exam=self.exam, student=self.student)
        self.assertEqual(float(score.total_score), 10.0)  # 1번만 정답

    def test_correcting_an_answer_rescores_and_locks_the_row(self):
        """조교가 적은 값은 재판독이 덮지 않는다 — 총점도 따라 움직인다."""
        self.patch(self.orphan, {"student_id": self.student.pk})

        res = self.patch(self.orphan, {"answers": {"2": "4"}})

        self.assertEqual(res.status_code, 200)
        row = next(r for r in res.json()["questions"] if r["q_number"] == 2)
        self.assertEqual(
            (row["marked"], row["result"], row["is_corrected"]), ("4", _R.CORRECT, True)
        )
        self.assertEqual(res.json()["total_score"], 20.0)

    def test_a_blank_correction_is_a_value_too(self):
        """빈 문자열은 '못 봤다' 가 아니라 '무응답이 맞다' 는 판정이다."""
        self.patch(self.orphan, {"answers": {"1": ""}})

        row = SheetAnswer.objects.get(sheet=self.orphan, question=self.q1)
        self.assertEqual((row.marked, row.result, row.is_corrected), (None, _R.BLANK, True))

    def test_confirming_locks_without_changing_values(self):
        """기계 판독이 맞다는 확인 — 값도 대조 상태도 그대로, 잠금만 걸린다."""
        res = self.patch(self.orphan, {"confirm": True})

        self.assertEqual(res.status_code, 200)
        self.orphan.refresh_from_db()
        self.assertTrue(self.orphan.is_corrected)
        self.assertEqual(self.orphan.match_status, _MS.MISSING)
        self.assertEqual(self.orphan.answers.get(question=self.q1).marked, "3")

    def test_an_empty_patch_is_refused(self):
        """빈 PATCH 로 잠금이 걸리면 안 본 장이 확인된 장으로 둔갑한다."""
        res = self.patch(self.orphan, {})

        self.assertEqual(res.status_code, 400)
        self.orphan.refresh_from_db()
        self.assertFalse(self.orphan.is_corrected)

    def test_a_mark_off_the_card_is_refused(self):
        """카드는 5지선다다. 6번 마킹은 조교의 오타이지 판독이 아니다."""
        res = self.patch(self.orphan, {"answers": {"1": "6"}})

        self.assertEqual(res.status_code, 400)
        self.assertEqual(SheetAnswer.objects.get(sheet=self.orphan, question=self.q1).marked, "3")

    def test_an_unknown_student_is_refused(self):
        res = self.patch(self.orphan, {"student_id": 9_999_999})

        self.assertEqual(res.status_code, 400)

    def test_the_scan_needs_the_feature_key(self):
        """지면에 실명·전화 뒷자리가 있다 — 링크 하나가 곧 유출 경로다."""
        default_storage.save("omr/orphan.jpg", ContentFile(b"\xff\xd8\xff"))
        self.addCleanup(default_storage.delete, "omr/orphan.jpg")
        url = f"{self.sheet_url(self.orphan)}/scan"

        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(self.admin)
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(b"".join(res.streaming_content), b"\xff\xd8\xff")
