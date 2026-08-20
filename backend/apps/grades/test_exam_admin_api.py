"""관리자 시험 조회 API 5차 슬라이스 테스트 — 성적처리 화면 근거 (PRD 3.1.1).

검증 축:
- 기능 키 게이트(FeatureRequired 성적처리): 프리셋(관리자)·delta(조교 부여)·대표 전권
- 시험 목록: 응시자 수·평균(저장값 우선)·처리 상태(파생값 — 조회 시 계산)
- 시험 상세: 학생별 점수 테이블(점수 내림차순·동점 공동 석차·미응시 후순위),
  문항별 정답률·결과 분포(무응답·복수마킹 — 보정 화면 근거, PRD 마킹 이상 경고)
- 시험 만들기·정답 키 저장, 스캔 묶음 업로드(판독 자체는 Celery 워커의 일)

픽스처·검산 값은 test_grade_report_api.GradeFixtureMixin(모듈 docstring) 공용.
"""
import json
from unittest import mock

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.accounts.features import FeatureKey
from apps.accounts.models import StaffFeatureGrant, User
from apps.curriculum import class_admin
from apps.curriculum.models import CourseWeek

from .models import AnswerSheet, ClassSession, Exam
from .test_grade_report_api import GradeFixtureMixin, make_user

ADMIN_EXAMS = "/api/admin/exams"


class ExamAdminFixtureMixin(GradeFixtureMixin):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = make_user("adm-exam", User.Role.ADMIN, name="관리자")
        cls.owner = make_user("own-exam", User.Role.OWNER, name="대표")
        cls.assistant = make_user("ast-exam", User.Role.ASSISTANT, name="조교")
        cls.granted_assistant = make_user("ast-exam-ok", User.Role.ASSISTANT, name="부여조교")
        StaffFeatureGrant.objects.create(
            user=cls.granted_assistant,
            feature_key=FeatureKey.GRADE_PROCESSING,
            is_granted=True,
        )

    def login_admin(self):
        self.client.force_login(self.admin)

    def detail_url(self, exam):
        return f"{ADMIN_EXAMS}/{exam.pk}"


class ExamAdminAccessTests(ExamAdminFixtureMixin, TestCase):
    """기능 키 게이트 — 성적처리 보유자만(§4 직원 기능 권한)."""

    def test_anonymous_denied(self):
        self.assertEqual(self.client.get(ADMIN_EXAMS).status_code, 403)

    def test_consumer_roles_denied(self):
        for user in (self.student_a.user, self.parent_user):
            self.client.force_login(user)
            self.assertEqual(self.client.get(ADMIN_EXAMS).status_code, 403)
            self.assertEqual(self.client.get(self.detail_url(self.exam2)).status_code, 403)

    def test_assistant_without_feature_denied(self):
        """조교 프리셋에는 성적처리가 없다 — delta 부여 전 차단."""
        self.client.force_login(self.assistant)
        self.assertEqual(self.client.get(ADMIN_EXAMS).status_code, 403)

    def test_assistant_with_delta_allowed(self):
        self.client.force_login(self.granted_assistant)
        self.assertEqual(self.client.get(ADMIN_EXAMS).status_code, 200)

    def test_admin_preset_allowed(self):
        self.login_admin()
        self.assertEqual(self.client.get(ADMIN_EXAMS).status_code, 200)

    def test_owner_allowed(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.detail_url(self.exam2)).status_code, 200)

    def test_detail_is_read_only(self):
        """상세는 조회 전용 — 성적 수정은 보정 화면 몫이다."""
        self.login_admin()
        self.assertEqual(self.client.put(self.detail_url(self.exam2)).status_code, 405)


class ExamAdminListTests(ExamAdminFixtureMixin, TestCase):
    """GET /api/admin/exams — 응시자 수·평균·처리 상태."""

    def get_list(self):
        self.login_admin()
        res = self.client.get(ADMIN_EXAMS)
        self.assertEqual(res.status_code, 200)
        return res.json()["exams"]

    def test_ordering_latest_first(self):
        rows = self.get_list()
        self.assertEqual(
            [r["exam_id"] for r in rows],
            [self.exam3.pk, self.exam2.pk, self.exam1.pk, self.exam0.pk],
        )

    def test_row_fields_and_derived_status(self):
        """처리 상태는 파생값 — 성적 없음=채점전, 미보정 답안지 존재=보정필요, 그 외=완료."""
        rows = {r["exam_id"]: r for r in self.get_list()}
        self.assertEqual(
            rows[self.exam3.pk],
            {
                "exam_id": self.exam3.pk,
                "name": "오메가블랙 3회",
                "kind": "미니테스트",
                "exam_date": "2026-07-15",
                "round_no": 3,
                "target_grade": None,
                "taker_count": 1,
                "score_count": 2,
                "average": 90.0,
                "processing_status": "보정필요",  # 불일치·미보정 답안지 1건
                "pending_sheet_count": 1,
            },
        )
        e2 = rows[self.exam2.pk]
        self.assertEqual(e2["taker_count"], 4)
        self.assertEqual(e2["score_count"], 4)
        self.assertEqual(e2["average"], 70.0)  # 캐시 없음 → 집계
        # B 의 5번이 복수마킹이라 대조가 `정상` 이어도 사람이 골라야 한다
        # (2026-08-12 이상 축 분리 — 그 전에는 이 장이 완료로 지나갔다).
        self.assertEqual(e2["processing_status"], "보정필요")
        self.assertEqual(e2["pending_sheet_count"], 1)
        e1 = rows[self.exam1.pk]
        self.assertEqual(e1["taker_count"], 1)
        self.assertEqual(e1["average"], 25.0)  # 저장 캐시 우선(실측 20 아님)
        self.assertEqual(e1["processing_status"], "완료")
        e0 = rows[self.exam0.pk]
        self.assertEqual(e0["taker_count"], 0)
        self.assertEqual(e0["score_count"], 0)
        self.assertIsNone(e0["average"])
        self.assertEqual(e0["processing_status"], "채점전")

    def test_query_budget(self):
        self.login_admin()
        # 세션인증 2 + 기능키 1 + 시험·성적 annotate 1 + 보정대기 1 + 익명 장 1
        # + 커리·주차 드롭다운 1. 익명 집계와 주차 목록은 **시험 수와 무관한 한
        # 쿼리씩**이다 — 시험마다 summary_stats 를 부르면 시험 수만큼 늘어난다.
        with self.assertNumQueries(7):
            self.assertEqual(self.client.get(ADMIN_EXAMS).status_code, 200)


class ExamAdminDetailTests(ExamAdminFixtureMixin, TestCase):
    """GET /api/admin/exams/{exam_id} — 학생별 점수 테이블 + 문항별 정답률."""

    def get_detail(self, exam):
        self.login_admin()
        res = self.client.get(self.detail_url(exam))
        self.assertEqual(res.status_code, 200)
        return res.json()

    def test_unknown_exam_404(self):
        self.login_admin()
        self.assertEqual(self.client.get(f"{ADMIN_EXAMS}/999999").status_code, 404)

    def test_saving_a_clinic_cut(self):
        """컷은 OMR 쪽에서 넣는다(FLOW 3-3) — 시험 관리 화면이 그 자리다."""
        self.login_admin()

        res = self.client.patch(
            self.detail_url(self.exam2),
            data=json.dumps({"clinic_cutoff": "60"}),
            content_type="application/json",
        )

        self.assertEqual(res.status_code, 200)
        self.assertEqual(float(Exam.objects.get(pk=self.exam2.pk).clinic_cutoff), 60.0)

    def test_clearing_the_cut_leaves_the_average(self):
        self.login_admin()
        Exam.objects.filter(pk=self.exam2.pk).update(clinic_cutoff="60")

        res = self.client.patch(
            self.detail_url(self.exam2),
            data=json.dumps({"clinic_cutoff": ""}),
            content_type="application/json",
        )

        self.assertEqual(res.status_code, 200)
        self.assertIsNone(Exam.objects.get(pk=self.exam2.pk).clinic_cutoff)

    def test_a_negative_cut_is_rejected(self):
        self.login_admin()

        res = self.client.patch(
            self.detail_url(self.exam2),
            data=json.dumps({"clinic_cutoff": "-1"}),
            content_type="application/json",
        )

        self.assertEqual(res.status_code, 400)

    def test_exam_and_stats_blocks(self):
        body = self.get_detail(self.exam2)
        self.assertEqual(
            body["exam"],
            {
                "exam_id": self.exam2.pk,
                "name": "오메가블랙 2회",
                "kind": "미니테스트",
                "full_score": None,  # 미니테스트는 문항 배점의 합이라 안 쓴다
                "exam_date": "2026-07-08",
                "round_no": 2,
                "target_grade": None,
                "notice": "7월 성적표 공지",
                "clinic_cutoff": None,  # 비어 있으면 그 시험 평균으로 가른다
            },
        )
        self.assertEqual(
            body["stats"],
            {
                "taker_count": 4,
                "score_count": 4,
                "average": 70.0,
                "stddev": 10.0,
                "highest_score": 80.0,
                "top30_score": 80.0,
                # B 의 5번 복수마킹 — 매칭은 됐지만 조교가 골라야 한다
                "processing_status": "보정필요",
                "pending_sheet_count": 1,
            },
        )

    def test_student_table_sorted_with_ranks(self):
        """점수 내림차순, 동점 공동 석차(1·1·3·3), 동점 내 student_id 순."""
        students = self.get_detail(self.exam2)["students"]
        self.assertEqual(
            [(s["student_id"], s["total_score"], s["rank"]) for s in students],
            [
                (self.student_b.student_id, 80.0, 1),
                (self.student_c.student_id, 80.0, 1),
                (self.student_a.student_id, 60.0, 3),
                (self.student_d.student_id, 60.0, 3),
            ],
        )
        first = students[0]
        self.assertEqual(first["name"], "이민준")
        self.assertEqual(first["matching_key"], self.student_b.matching_key)
        self.assertEqual(first["max_score"], 100.0)
        self.assertTrue(first["is_taken"])
        self.assertIsNone(first["percentile"])  # 저장 전 — 표시만(계산·저장은 성적처리 슬라이스)

    def test_untaken_student_listed_last_without_rank(self):
        """미응시는 표 하단·석차 없음(PRD 3.1.1 미응시 표기)."""
        students = self.get_detail(self.exam3)["students"]
        self.assertEqual(
            [(s["student_id"], s["total_score"], s["rank"], s["is_taken"]) for s in students],
            [
                (self.student_b.student_id, 90.0, 1, True),
                (self.student_a.student_id, None, None, False),
            ],
        )

    def test_question_stats(self):
        """문항별 정답률·결과 분포 — 보정 화면 근거(전량 조회 시 계산)."""
        rows = self.get_detail(self.exam2)["questions"]
        self.assertEqual(
            [
                (
                    r["q_number"],
                    r["answered_count"],
                    r["correct_count"],
                    r["wrong_count"],
                    r["blank_count"],
                    r["multi_count"],
                    r["correct_rate"],
                )
                for r in rows
            ],
            [
                (1, 4, 3, 1, 0, 0, 75.0),
                (2, 4, 2, 2, 0, 0, 50.0),
                (3, 4, 4, 0, 0, 0, 100.0),
                (4, 4, 3, 1, 0, 0, 75.0),
                (5, 4, 2, 0, 1, 1, 50.0),
            ],
        )
        q1 = rows[0]
        self.assertEqual(q1["question_id"], self.q1.pk)
        self.assertEqual(q1["unit_major"], "산염기")
        self.assertEqual(q1["unit_minor"], "중화")
        self.assertEqual(q1["points"], 20.0)
        self.assertEqual(q1["answer"], "1")

    def test_query_budget(self):
        self.login_admin()
        # 세션인증 2 + 기능키 1 + 시험 annotate 1 + 보정대기 1 + 요약 집계 1
        # + 상위30 1 + 학생별 성적 1 + 문항 1 + 문항 집계 1
        with self.assertNumQueries(10):
            self.assertEqual(self.client.get(self.detail_url(self.exam2)).status_code, 200)


class ExamCreateAndKeyTests(ExamAdminFixtureMixin, TestCase):
    """시험 만들기 · 정답 키 입력 — 채점은 키가 있어야 성립한다(PRD 3.1.1)."""

    def key_url(self, exam):
        return f"{ADMIN_EXAMS}/{exam.pk}/questions"

    def test_creates_an_exam_without_questions(self):
        """키는 나중에 채운다 — 시험을 먼저 잡아 둘 수 있어야 한다."""
        self.login_admin()

        res = self.client.post(
            ADMIN_EXAMS,
            data=json.dumps({"name": "8월 미니테스트", "exam_date": "2026-08-12"}),
            content_type="application/json",
        )

        self.assertEqual(res.status_code, 201)
        self.assertTrue(Exam.objects.filter(pk=res.json()["exam_id"]).exists())

    def test_creating_an_exam_on_a_week_attaches_the_classes(self):
        """시험은 커리 주차에 붙고 그 주차를 듣는 반들의 회차가 가리킨다(FLOW 3-3)."""
        self.login_admin()
        klass = class_admin.open_class(
            course_id=None, course_name="2026 여름 N제 2기", total_weeks=3,
            track="수능", subject="통합과학",
            name="목 6.5 대치러셀", start_date="2026-09-03",
        )
        week = CourseWeek.objects.get(course=klass.course, week_no=2)

        res = self.client.post(
            ADMIN_EXAMS,
            data=json.dumps({
                "name": "2주차 미니", "exam_date": "2026-09-10",
                "course_week_id": week.week_id, "clinic_cutoff": "55.5",
            }),
            content_type="application/json",
        )

        self.assertEqual(res.status_code, 201)
        exam = Exam.objects.get(pk=res.json()["exam_id"])
        self.assertEqual(exam.course_week_id, week.week_id)
        self.assertEqual(float(exam.clinic_cutoff), 55.5)
        self.assertEqual(
            ClassSession.objects.get(klass=klass, week_no=2).exam_id, exam.pk
        )

    def test_rejects_a_week_that_already_has_an_exam(self):
        """한 커리 주차 = 시험 하나. 덮으면 앞 시험의 문항이 조용히 사라진다."""
        self.login_admin()
        klass = class_admin.open_class(
            course_id=None, course_name="2026 여름 N제 3기", total_weeks=2,
            track="수능", subject="통합과학",
            name="화 6.5 대치러셀", start_date="2026-09-01",
        )
        week = CourseWeek.objects.get(course=klass.course, week_no=1)
        payload = {"name": "1주차 미니", "exam_date": "2026-09-01", "course_week_id": week.week_id}
        self.client.post(ADMIN_EXAMS, data=json.dumps(payload), content_type="application/json")

        res = self.client.post(
            ADMIN_EXAMS, data=json.dumps(payload), content_type="application/json"
        )

        self.assertEqual(res.status_code, 400)

    def test_rejects_an_exam_without_a_date(self):
        self.login_admin()

        res = self.client.post(
            ADMIN_EXAMS,
            data=json.dumps({"name": "이름만"}),
            content_type="application/json",
        )

        self.assertEqual(res.status_code, 400)

    def put_key(self, exam, questions):
        return self.client.put(
            self.key_url(exam),
            data=json.dumps({"questions": questions}),
            content_type="application/json",
        )

    def test_saves_a_key_without_units(self):
        """단원은 채점에 안 쓴다 — 정답만으로 저장돼야 한다."""
        self.login_admin()

        res = self.put_key(self.exam2, [
            {"q_number": 1, "answer": "4"},
            {"q_number": 2, "answer": "2", "points": 5},
        ])

        self.assertEqual(res.status_code, 200)
        rows = {r["q_number"]: r for r in res.json()["questions"]}
        self.assertEqual(rows[1]["answer"], "4")
        self.assertEqual(float(rows[2]["points"]), 5.0)

    def test_rejects_a_partial_key(self):
        """반쯤 들어간 키는 반쯤 틀린 채점을 만든다 — 전량 검증 후에만 저장."""
        self.login_admin()

        res = self.put_key(self.exam2, [
            {"q_number": 1, "answer": "4"},
            {"q_number": 2, "answer": ""},
        ])

        self.assertEqual(res.status_code, 400)

    def test_units_already_used_come_back_as_options(self):
        """별도 표 없이 쓰던 단원이 후보가 된다 — 대단원 하나에 중단원 여럿."""
        self.login_admin()
        self.put_key(self.exam2, [
            {"q_number": 1, "answer": "1", "unit_major": "물질과 규칙성", "unit_minor": "원소"},
        ])

        units = self.client.get(self.key_url(self.exam2)).json()["units"]

        self.assertIn("원소", units["물질과 규칙성"])


class SheetUploadTests(ExamAdminFixtureMixin, TestCase):
    """스캔 업로드 — 뷰는 파일만 놓고 즉시 답한다(판독은 워커)."""

    def post_pdf(self, exam, question_count):
        pdf = SimpleUploadedFile("batch.pdf", b"%PDF-1.4\n", content_type="application/pdf")
        return self.client.post(
            f"{ADMIN_EXAMS}/{exam.pk}/sheets", {"pdf": pdf, "question_count": question_count}
        )

    def test_hands_the_batch_to_the_worker(self):
        """판독이 요청을 붙잡으면 안 된다 — 스토리지에 놓고 경로만 넘긴다."""
        self.login_admin()

        with mock.patch("apps.grades.tasks.ingest_omr_batch.delay") as delay:
            delay.return_value = mock.Mock(id="task-1")
            res = self.post_pdf(self.exam2, 16)

        self.assertEqual(res.status_code, 202)
        self.assertEqual(res.json()["task_id"], "task-1")
        exam_pk, path, count = delay.call_args.args
        self.assertEqual((exam_pk, count), (self.exam2.pk, 16))
        self.assertTrue(default_storage.exists(path))
        default_storage.delete(path)

    def test_rejects_a_question_count_no_card_can_hold(self):
        """상한은 **제일 큰 판형**이 정한다 — 옛 카드 20, 우리 25문항 카드 25.

        워커에서 죽으면 사용자는 "판독 실패"만 보게 되므로 여기서 막는다.
        21문항은 이제 통과한다: 25문항 카드에 얹으면 된다.
        """
        self.login_admin()

        with mock.patch("apps.grades.tasks.ingest_omr_batch.delay") as delay:
            delay.return_value = mock.Mock(id="task-25")
            ok = self.post_pdf(self.exam2, 25)
        self.assertEqual(ok.status_code, 202)
        default_storage.delete(delay.call_args.args[1])

        with mock.patch("apps.grades.tasks.ingest_omr_batch.delay") as delay:
            res = self.post_pdf(self.exam2, 26)
        self.assertEqual(res.status_code, 400)
        delay.assert_not_called()


class ExamCardsTests(ExamAdminFixtureMixin, TestCase):
    """회차 OMR 카드 PDF — 저장하지 않고 그 자리에서 만들어 내려보낸다."""

    def cards_url(self, exam):
        return f"{ADMIN_EXAMS}/{exam.pk}/cards"

    def test_it_returns_a_printable_pdf(self):
        self.login_admin()

        res = self.client.get(self.cards_url(self.exam2))

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/pdf")
        self.assertTrue(res.content.startswith(b"%PDF"))
        # 판형 이름이 한글이라 파일 이름은 RFC5987 로 실린다. 헤더 값 자체가
        # ASCII 로 남아야 `attachment` 가 보이고 브라우저가 내려받는다.
        self.assertTrue(res["Content-Disposition"].startswith("attachment;"))
        self.assertIn("filename*=UTF-8''", res["Content-Disposition"])

    def test_the_question_count_picks_the_layout(self):
        """21문항이면 25문항 카드다 — 20문항 카드에는 안 들어간다."""
        from .omr import layout

        self.assertEqual(layout.for_questions(1).name, "답안20")
        self.assertEqual(layout.for_questions(20).name, "답안20")
        self.assertEqual(layout.for_questions(21).name, "답안25")
        self.assertEqual(layout.for_questions(25).name, "답안25")
        self.assertIsNone(layout.for_questions(26))

    def test_without_an_answer_key_there_is_nothing_to_print(self):
        """문항 수를 모르면 판형을 못 고른다. 지어내면 틀린 카드를 찍는다."""
        self.login_admin()
        exam = Exam.objects.create(
            name="키 없는 회차", exam_date=self.exam2.exam_date, kind=Exam.Kind.MINI
        )

        res = self.client.get(self.cards_url(exam))

        self.assertEqual(res.status_code, 400)


class AnonymousSheetStatsTests(ExamAdminFixtureMixin, TestCase):
    """익명 확정 장은 목록·상세 **양쪽** 모집단에 든다 (decisions.md 「익명 점수」).

    상세만 `scores` 행을 세면 같은 시험에 두 개의 응시자 수가 나간다 — 익명 장은
    학생 FK 가 NOT NULL 이라 `scores` 행이 아예 없기 때문이다.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # exam2 는 4명·60/80/80/60 (합 280, 평균 70). 여기에 90점 익명 한 장.
        cls.anon = AnswerSheet.objects.create(
            exam=cls.exam2,
            scan_image_path="omr/scans/anon.jpg",
            match_status=AnswerSheet.MatchStatus.INVALID,
            recognized_score=90,
            is_corrected=True,
        )

    def stats(self):
        self.login_admin()
        row = next(
            r
            for r in self.client.get(ADMIN_EXAMS).json()["exams"]
            if r["exam_id"] == self.exam2.pk
        )
        detail = self.client.get(self.detail_url(self.exam2)).json()["stats"]
        return row, detail

    def test_list_and_detail_report_the_same_taker_count(self):
        row, detail = self.stats()

        self.assertEqual(row["taker_count"], 5)
        self.assertEqual(detail["taker_count"], row["taker_count"])

    def test_the_taker_count_and_the_average_share_a_population(self):
        """수는 4명인데 평균은 5명치면 화면이 스스로와 모순된다."""
        row, detail = self.stats()

        self.assertEqual(row["average"], 74.0)  # (280+90)/5
        self.assertEqual(detail["average"], 74.0)
        self.assertEqual(detail["taker_count"], 5)

    def test_an_unconfirmed_anonymous_sheet_counts_for_neither(self):
        """조교가 아직 안 본 장까지 세면 주인을 찾는 순간 평균이 바뀐다."""
        AnswerSheet.objects.filter(pk=self.anon.pk).update(is_corrected=False)

        row, detail = self.stats()

        self.assertEqual((row["taker_count"], detail["taker_count"]), (4, 4))
        self.assertEqual((row["average"], detail["average"]), (70.0, 70.0))
