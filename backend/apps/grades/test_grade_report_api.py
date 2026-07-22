"""성적·성적표 조회 API 5차 슬라이스 테스트 — 학생·학부모 (PRD 3.2.1·3.1.1·§4).

검증 축:
- 역할 게이트(IsStudent/IsParent)·자녀 소유 검증(404 존재 비노출 — 2차 슬라이스 패턴)
- 성적표 최소 포함 항목(PRD 3.2.1): 요약·대단원별·문항 채점표·오답 학습동선·테마 추이
- 집계 계약: 캐시(Exam.avg_score 등 · Score.percentile · Question.wrong_rate)
  **저장값 우선**, 없으면 scores/sheet_answers DB 집계로 조회 시 계산.
  사본 저장 금지 — GET 후 캐시 컬럼이 여전히 NULL 임을 재조회로 검증.
- 미응시: 목록 0점 표기 + 상세 "성적표 없음"(PRD 3.1.1)
- 쿼리 효율: assertNumQueries 상한 고정(N+1 회귀 방지)

검산 픽스처(기대값 전부 손계산과 일치하도록 설계):
- E1(캐시 저장): A 20/40, 실측 평균 20 ↔ 저장 평균 25 — 저장값 우선 검증 축
- E2(캐시 없음): 응시 4명 {A60, B80, C80, D60}
    평균 = 280/4 = 70 · 모표준편차 = √((100+100+100+100)/4) = 10 · 최고 80
    상위30% = ceil(4×0.3)=2번째 점수 = 80
    A 백분위 = (미만 0명 + 동점 2명/2) / 4 × 100 = 25.0
- E3: A 미응시(0점 표기·성적표 없음), B 90 → 평균 90
- E0: A 성적 없음 — 목록 미포함·상세 404(존재 비노출)
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import Parent, ParentStudent, Student, User
from apps.videos.models import Video

from .models import AnswerSheet, Exam, Question, Score, SheetAnswer

PASSWORD = "pw-Secret-77!"
STUDENT_GRADES = "/api/student/grades"
PARENT_GRADES = "/api/parent/grades"


def make_user(login_id, role, name="사용자"):
    return User.objects.create_user(login_id=login_id, password=PASSWORD, name=name, role=role)


def make_student(login_id, name, **extra):
    user = make_user(login_id, User.Role.STUDENT, name=name)
    return Student.objects.create(
        user=user,
        unique_id=f"uid-{login_id}",
        enrollment_status=Student.EnrollmentStatus.REGISTERED,
        **extra,
    )


def make_score(exam, student, total, max_score=Decimal("100"), percentile=None, is_taken=True):
    return Score.objects.create(
        exam=exam,
        student=student,
        total_score=total,
        max_score=max_score,
        percentile=percentile,
        is_taken=is_taken,
    )


def make_sheet(exam, student, results):
    """정상 매칭 답안지 1장 — results: {Question: (result, marked)}."""
    sheet = AnswerSheet.objects.create(
        exam=exam,
        student=student,
        scan_image_path=f"scan/{exam.pk}-{student.pk}.jpg",
        match_status=AnswerSheet.MatchStatus.MATCHED,
    )
    for question, (result, marked) in results.items():
        SheetAnswer.objects.create(sheet=sheet, question=question, result=result, marked=marked)
    return sheet


class GradeFixtureMixin:
    """모듈 docstring 의 검산 픽스처 — 소비자·관리자 테스트 공용."""

    @classmethod
    def setUpTestData(cls):
        R = SheetAnswer.Result
        cls.student_a = make_student(
            "stu-grd-a", "김서연", school="서연고", current_class="고2 B반"
        )
        cls.student_z = make_student("stu-grd-z", "박둘째")
        cls.student_b = make_student("stu-grd-b", "이민준")
        cls.student_c = make_student("stu-grd-c", "최지우")
        cls.student_d = make_student("stu-grd-d", "정하늘")

        cls.parent_user = make_user("par-grd", User.Role.PARENT, name="김학부모")
        parent = Parent.objects.create(user=cls.parent_user, name="김학부모", phone="010-1111-2222")
        ParentStudent.objects.create(parent=parent, student=cls.student_a)
        ParentStudent.objects.create(parent=parent, student=cls.student_z)
        cls.other_parent_user = make_user("par-grd2", User.Role.PARENT)
        other = Parent.objects.create(user=cls.other_parent_user, phone="010-3333-4444")
        ParentStudent.objects.create(parent=other, student=cls.student_b)

        cls.guide_video = Video.objects.create(title="중화반응 개념 강의")

        # E0 — 성적 없음(채점 전): A 목록 미포함·상세 404 근거
        cls.exam0 = Exam.objects.create(
            name="0회 진단", exam_date=datetime.date(2026, 6, 24), round_no=0
        )

        # E1 — 캐시 저장 시험(저장값 우선: 실측 평균 20 ↔ 저장 25, 백분위 실측 50 ↔ 저장 40)
        cls.exam1 = Exam.objects.create(
            name="오메가블랙 1회",
            exam_date=datetime.date(2026, 7, 1),
            round_no=1,
            avg_score=Decimal("25.00"),
            stddev=Decimal("5.00"),
            max_score=Decimal("30.00"),
            top30_score=Decimal("30.00"),
        )
        cls.e1q1 = Question.objects.create(
            exam=cls.exam1, q_number=1, answer="1", points=Decimal("20.0"),
            unit_major="산염기", theme_tag="중화반응",
        )
        cls.e1q2 = Question.objects.create(
            exam=cls.exam1, q_number=2, answer="2", points=Decimal("20.0"),
            unit_major="산화환원", theme_tag="산화수",
        )
        make_score(
            cls.exam1, cls.student_a, Decimal("20.00"),
            max_score=Decimal("40"), percentile=Decimal("40.00"),
        )
        make_sheet(
            cls.exam1, cls.student_a,
            {cls.e1q1: (R.WRONG, "3"), cls.e1q2: (R.CORRECT, "2")},
        )

        # E2 — 캐시 없음(집계 계산): 응시 4명 {A60, B80, C80, D60}
        cls.exam2 = Exam.objects.create(
            name="오메가블랙 2회",
            exam_date=datetime.date(2026, 7, 8),
            round_no=2,
            notice="7월 성적표 공지",
        )
        cls.q1 = Question.objects.create(
            exam=cls.exam2, q_number=1, answer="1", points=Decimal("20.0"),
            unit_major="산염기", unit_minor="중화", theme_tag="중화반응",
            wrong_rate=Decimal("30.00"),  # 저장값(실측 25) — 저장값 우선 검증 축
        )
        cls.q2 = Question.objects.create(
            exam=cls.exam2, q_number=2, answer="2", points=Decimal("20.0"),
            unit_major="산염기", theme_tag="중화반응",
            study_guide="중화반응 개념 강의 복습", guide_video=cls.guide_video,
        )
        cls.q3 = Question.objects.create(
            exam=cls.exam2, q_number=3, answer="3", points=Decimal("20.0"),
            unit_major="산화환원", theme_tag="산화수", study_guide="산화수 규칙 정리",
        )
        cls.q4 = Question.objects.create(
            exam=cls.exam2, q_number=4, answer="4", points=Decimal("20.0"),
            unit_major="산화환원", theme_tag="산화수",
        )
        cls.q5 = Question.objects.create(
            exam=cls.exam2, q_number=5, answer="5", points=Decimal("20.0"),
            unit_major="산화환원",  # 테마 없음 — 테마 추이 제외 축
        )
        make_score(cls.exam2, cls.student_a, Decimal("60.00"))
        make_score(cls.exam2, cls.student_b, Decimal("80.00"))
        make_score(cls.exam2, cls.student_c, Decimal("80.00"))
        make_score(cls.exam2, cls.student_d, Decimal("60.00"))
        make_sheet(
            cls.exam2, cls.student_a,
            {
                cls.q1: (R.CORRECT, "1"),
                cls.q2: (R.WRONG, "4"),
                cls.q3: (R.CORRECT, "3"),
                cls.q4: (R.CORRECT, "4"),
                cls.q5: (R.BLANK, None),
            },
        )
        make_sheet(
            cls.exam2, cls.student_b,
            {
                cls.q1: (R.CORRECT, "1"),
                cls.q2: (R.CORRECT, "2"),
                cls.q3: (R.CORRECT, "3"),
                cls.q4: (R.CORRECT, "4"),
                cls.q5: (R.MULTI, "1,5"),
            },
        )
        make_sheet(
            cls.exam2, cls.student_c,
            {
                cls.q1: (R.WRONG, "2"),
                cls.q2: (R.CORRECT, "2"),
                cls.q3: (R.CORRECT, "3"),
                cls.q4: (R.CORRECT, "4"),
                cls.q5: (R.CORRECT, "5"),
            },
        )
        make_sheet(
            cls.exam2, cls.student_d,
            {
                cls.q1: (R.CORRECT, "1"),
                cls.q2: (R.WRONG, "1"),
                cls.q3: (R.CORRECT, "3"),
                cls.q4: (R.WRONG, "2"),
                cls.q5: (R.CORRECT, "5"),
            },
        )

        # E3 — A 미응시(0점·성적표 없음, PRD 3.1.1), B 만 응시(90)
        cls.exam3 = Exam.objects.create(
            name="오메가블랙 3회", exam_date=datetime.date(2026, 7, 15), round_no=3
        )
        make_score(cls.exam3, cls.student_a, None, is_taken=False)
        make_score(cls.exam3, cls.student_b, Decimal("90.00"))
        # 보정 대기 답안지(관리자 처리상태 판정 근거) — 학생 미대조라 소비자 조회와 무관
        AnswerSheet.objects.create(
            exam=cls.exam3,
            scan_image_path="scan/e3-unknown.jpg",
            match_status=AnswerSheet.MatchStatus.MISMATCH,
        )

    def login_student(self):
        self.client.force_login(self.student_a.user)

    def login_parent(self):
        self.client.force_login(self.parent_user)

    def detail_url(self, exam, base=STUDENT_GRADES):
        return f"{base}/{exam.pk}"


class StudentGradesAccessTests(GradeFixtureMixin, TestCase):
    """역할 게이트 — IsStudent 재사용(1차 슬라이스 부품)."""

    def test_anonymous_denied(self):
        self.assertEqual(self.client.get(STUDENT_GRADES).status_code, 403)
        self.assertEqual(self.client.get(self.detail_url(self.exam2)).status_code, 403)

    def test_parent_role_denied(self):
        self.login_parent()
        self.assertEqual(self.client.get(STUDENT_GRADES).status_code, 403)

    def test_staff_role_denied(self):
        self.client.force_login(make_user("adm-grd-deny", User.Role.ADMIN))
        self.assertEqual(self.client.get(STUDENT_GRADES).status_code, 403)

    def test_write_methods_not_allowed(self):
        self.login_student()
        self.assertEqual(self.client.post(STUDENT_GRADES).status_code, 405)
        self.assertEqual(self.client.put(self.detail_url(self.exam2)).status_code, 405)


class StudentGradeListTests(GradeFixtureMixin, TestCase):
    """GET /api/student/grades — 내 시험 목록(회차순) + 회차별 추이(PRD 3.2.1)."""

    def get_list(self):
        self.login_student()
        res = self.client.get(STUDENT_GRADES)
        self.assertEqual(res.status_code, 200)
        return res.json()

    def test_student_block(self):
        body = self.get_list()
        self.assertEqual(
            body["student"],
            {
                "student_id": self.student_a.student_id,
                "name": "김서연",
                "unique_id": self.student_a.unique_id,
                "school": "서연고",
                "current_class": "고2 B반",
            },
        )

    def test_exam_rows_in_round_order_and_only_mine(self):
        """내 성적이 있는 시험만, 회차(시험일)순 — E0(성적 없음)은 목록에 없다."""
        rows = self.get_list()["exams"]
        self.assertEqual(
            [r["exam_id"] for r in rows],
            [self.exam1.pk, self.exam2.pk, self.exam3.pk],
        )
        self.assertEqual(
            rows[0],
            {
                "exam_id": self.exam1.pk,
                "name": "오메가블랙 1회",
                "exam_date": "2026-07-01",
                "round_no": 1,
                "is_taken": True,
                "my_score": 20.0,
                "max_score": 40.0,
                "average": 25.0,  # 저장 캐시 우선(실측 20 아님)
            },
        )

    def test_computed_stats_when_cache_missing(self):
        """E2 캐시 없음 → scores 집계: 평균 70(280/4)."""
        rows = self.get_list()["exams"]
        e2 = next(r for r in rows if r["exam_id"] == self.exam2.pk)
        self.assertEqual(e2["my_score"], 60.0)
        self.assertEqual(e2["max_score"], 100.0)
        self.assertEqual(e2["average"], 70.0)
        self.assertTrue(e2["is_taken"])

    def test_untaken_exam_marked_zero(self):
        """미응시 = 0점 표기(PRD 3.1.1). 평균은 응시자(B 90) 기준."""
        rows = self.get_list()["exams"]
        e3 = next(r for r in rows if r["exam_id"] == self.exam3.pk)
        self.assertFalse(e3["is_taken"])
        self.assertEqual(e3["my_score"], 0)
        self.assertEqual(e3["average"], 90.0)

    def test_trend_series(self):
        """회차별 추이 — 본인 점수·백분위·평균·상위30%·최고점(PRD 3.2.1 성적 현황)."""
        trend = self.get_list()["trend"]
        self.assertEqual(
            trend,
            [
                {
                    "exam_id": self.exam1.pk,
                    "name": "오메가블랙 1회",
                    "exam_date": "2026-07-01",
                    "round_no": 1,
                    "is_taken": True,
                    "my_score": 20.0,
                    "percentile": 40.0,  # Score 저장값 우선(실측 50 아님)
                    "average": 25.0,
                    "top30_score": 30.0,
                    "highest_score": 30.0,
                },
                {
                    "exam_id": self.exam2.pk,
                    "name": "오메가블랙 2회",
                    "exam_date": "2026-07-08",
                    "round_no": 2,
                    "is_taken": True,
                    "my_score": 60.0,
                    "percentile": 25.0,  # (미만 0 + 동점 2/2)/4×100
                    "average": 70.0,
                    "top30_score": 80.0,  # ceil(4×0.3)=2번째 점수
                    "highest_score": 80.0,
                },
                {
                    "exam_id": self.exam3.pk,
                    "name": "오메가블랙 3회",
                    "exam_date": "2026-07-15",
                    "round_no": 3,
                    "is_taken": False,
                    "my_score": 0,
                    "percentile": None,
                    "average": 90.0,
                    "top30_score": 90.0,
                    "highest_score": 90.0,
                },
            ],
        )

    def test_no_cache_writeback(self):
        """조회 시 계산은 저장하지 않는다(사본 저장 금지 — key_considerations §6)."""
        self.get_list()
        self.exam2.refresh_from_db()
        self.assertIsNone(self.exam2.avg_score)
        self.assertIsNone(self.exam2.top30_score)
        score = Score.objects.get(exam=self.exam2, student=self.student_a)
        self.assertIsNone(score.percentile)

    def test_query_budget(self):
        self.login_student()
        # 세션인증 2 + 학생 1 + 성적목록 1 + E2 집계 1 + E2 상위30 1 + E2 백분위 1
        # + E3 집계 1 + E3 상위30 1 (E1 은 전부 저장값 — 추가 쿼리 0)
        with self.assertNumQueries(9):
            self.assertEqual(self.client.get(STUDENT_GRADES).status_code, 200)


class StudentGradeReportDetailTests(GradeFixtureMixin, TestCase):
    """GET /api/student/grades/{exam_id} — 성적표 상세(PRD 3.2.1 최소 포함 항목)."""

    def get_detail(self, exam):
        self.login_student()
        res = self.client.get(self.detail_url(exam))
        self.assertEqual(res.status_code, 200)
        return res.json()

    def test_not_my_exam_404(self):
        """내 성적이 없는 시험은 404 — 시험 존재 비노출(§4)."""
        self.login_student()
        self.assertEqual(self.client.get(self.detail_url(self.exam0)).status_code, 404)

    def test_unknown_exam_404(self):
        self.login_student()
        self.assertEqual(self.client.get(f"{STUDENT_GRADES}/999999").status_code, 404)

    def test_untaken_exam_has_no_report(self):
        """미응시 → 성적표 없음(PRD 3.1.1) — 블록 없이 표기만."""
        body = self.get_detail(self.exam3)
        self.assertFalse(body["is_taken"])
        self.assertIsNone(body["report"])
        self.assertEqual(body["message"], "성적표 없음")

    def test_student_and_exam_blocks(self):
        """학생 정보(성명·원번·학교) + 시험명·시험일·공지(PRD 3.2.1)."""
        body = self.get_detail(self.exam2)
        self.assertEqual(body["student"]["name"], "김서연")
        self.assertEqual(body["student"]["unique_id"], self.student_a.unique_id)
        self.assertEqual(body["student"]["school"], "서연고")
        self.assertEqual(
            body["exam"],
            {
                "exam_id": self.exam2.pk,
                "name": "오메가블랙 2회",
                "exam_date": "2026-07-08",
                "round_no": 2,
                "notice": "7월 성적표 공지",
            },
        )
        self.assertTrue(body["is_taken"])

    def test_summary_block(self):
        """① 성적 요약 — 캐시 없음 → 집계 계산(모듈 docstring 손계산)."""
        summary = self.get_detail(self.exam2)["report"]["summary"]
        self.assertEqual(
            summary,
            {
                "my_score": 60.0,
                "max_score": 100.0,
                "average": 70.0,
                "stddev": 10.0,
                "highest_score": 80.0,
                "top30_score": 80.0,
                "percentile": 25.0,
            },
        )

    def test_summary_uses_stored_stats_first(self):
        """E1 은 캐시 저장 시험 — 저장값(평균 25·백분위 40)이 실측(20·50)에 우선."""
        summary = self.get_detail(self.exam1)["report"]["summary"]
        self.assertEqual(summary["average"], 25.0)
        self.assertEqual(summary["stddev"], 5.0)
        self.assertEqual(summary["highest_score"], 30.0)
        self.assertEqual(summary["top30_score"], 30.0)
        self.assertEqual(summary["percentile"], 40.0)

    def test_unit_blocks(self):
        """② 대단원별 — 문항 수·정답 수(틀린 수)·내 점수/단원 만점·정답률."""
        units = self.get_detail(self.exam2)["report"]["units"]
        self.assertEqual(
            units,
            [
                {
                    "unit_major": "산염기",
                    "question_count": 2,
                    "correct_count": 1,
                    "wrong_count": 1,
                    "my_points": 20.0,
                    "unit_max_points": 40.0,
                    "correct_rate": 50.0,
                },
                {
                    "unit_major": "산화환원",
                    "question_count": 3,
                    "correct_count": 2,
                    "wrong_count": 1,
                    "my_points": 40.0,
                    "unit_max_points": 60.0,
                    "correct_rate": 66.7,
                },
            ],
        )

    def test_question_rows(self):
        """③ 문항 채점표 — 번호·단원·배점·정답·채점 결과·오답률(저장값 우선)."""
        rows = self.get_detail(self.exam2)["report"]["questions"]
        self.assertEqual(
            rows,
            [
                {
                    "q_number": 1,
                    "unit_major": "산염기",
                    "unit_minor": "중화",
                    "points": 20.0,
                    "answer": "1",
                    "marked": "1",
                    "result": "정답",
                    "wrong_rate": 30.0,  # 저장값 우선(실측 25)
                },
                {
                    "q_number": 2,
                    "unit_major": "산염기",
                    "unit_minor": None,
                    "points": 20.0,
                    "answer": "2",
                    "marked": "4",
                    "result": "오답",
                    "wrong_rate": 50.0,  # A·D 오답 2/4
                },
                {
                    "q_number": 3,
                    "unit_major": "산화환원",
                    "unit_minor": None,
                    "points": 20.0,
                    "answer": "3",
                    "marked": "3",
                    "result": "정답",
                    "wrong_rate": 0.0,
                },
                {
                    "q_number": 4,
                    "unit_major": "산화환원",
                    "unit_minor": None,
                    "points": 20.0,
                    "answer": "4",
                    "marked": "4",
                    "result": "정답",
                    "wrong_rate": 25.0,  # D 오답 1/4
                },
                {
                    "q_number": 5,
                    "unit_major": "산화환원",
                    "unit_minor": None,
                    "points": 20.0,
                    "answer": "5",
                    "marked": None,
                    "result": "무응답",
                    "wrong_rate": 50.0,  # A 무응답 + B 복수마킹 = 비정답 2/4
                },
            ],
        )

    def test_wrong_answer_guides(self):
        """④ 오답 학습동선 — result=오답 문항만(약점체크 대상 계약과 동일 축).

        A 의 Q5 는 무응답이지만 오답이 아니므로 학습동선에 없다. 정답 문항의
        가이드(Q3)도 없다. 가이드 영상은 있으면 함께 내린다.
        """
        guides = self.get_detail(self.exam2)["report"]["wrong_answer_guides"]
        self.assertEqual(
            guides,
            [
                {
                    "q_number": 2,
                    "unit_major": "산염기",
                    "theme_tag": "중화반응",
                    "study_guide": "중화반응 개념 강의 복습",
                    "guide_video": {
                        "video_id": self.guide_video.pk,
                        "title": "중화반응 개념 강의",
                    },
                }
            ],
        )

    def test_theme_trends(self):
        """⑤ 테마별 누적 정답률 추이 — 테마 축 × 회차 누적, 그리기만 하면 되는 형태.

        - 대상 회차: 이 시험까지(E1·E2). E3(이후·미응시)은 제외.
        - Q5(테마 없음)는 집계 제외.
        """
        trends = self.get_detail(self.exam2)["report"]["theme_trends"]
        self.assertEqual(
            trends,
            [
                {
                    "theme": "산화수",
                    "points": [
                        {
                            "exam_id": self.exam1.pk,
                            "name": "오메가블랙 1회",
                            "exam_date": "2026-07-01",
                            "round_no": 1,
                            "correct": 1,
                            "total": 1,
                            "rate": 100.0,
                            "cumulative_correct": 1,
                            "cumulative_total": 1,
                            "cumulative_rate": 100.0,
                        },
                        {
                            "exam_id": self.exam2.pk,
                            "name": "오메가블랙 2회",
                            "exam_date": "2026-07-08",
                            "round_no": 2,
                            "correct": 2,
                            "total": 2,
                            "rate": 100.0,
                            "cumulative_correct": 3,
                            "cumulative_total": 3,
                            "cumulative_rate": 100.0,
                        },
                    ],
                },
                {
                    "theme": "중화반응",
                    "points": [
                        {
                            "exam_id": self.exam1.pk,
                            "name": "오메가블랙 1회",
                            "exam_date": "2026-07-01",
                            "round_no": 1,
                            "correct": 0,
                            "total": 1,
                            "rate": 0.0,
                            "cumulative_correct": 0,
                            "cumulative_total": 1,
                            "cumulative_rate": 0.0,
                        },
                        {
                            "exam_id": self.exam2.pk,
                            "name": "오메가블랙 2회",
                            "exam_date": "2026-07-08",
                            "round_no": 2,
                            "correct": 1,
                            "total": 2,
                            "rate": 50.0,
                            "cumulative_correct": 1,
                            "cumulative_total": 3,
                            "cumulative_rate": 33.3,
                        },
                    ],
                },
            ],
        )

    def test_full_marks_fallback_from_questions(self):
        """만점 저장값이 없으면 문항 배점 합으로 계산(사본 저장 금지)."""
        Score.objects.filter(exam=self.exam2, student=self.student_a).update(max_score=None)
        summary = self.get_detail(self.exam2)["report"]["summary"]
        self.assertEqual(summary["max_score"], 100.0)  # 20×5

    def test_score_without_sheet(self):
        """답안지 없이 성적만 있는 시험 — 요약은 성립, 문항 축은 빈 값으로 닫힘."""
        exam4 = Exam.objects.create(
            name="특별 1회", exam_date=datetime.date(2026, 7, 20), round_no=4
        )
        Question.objects.create(
            exam=exam4, q_number=1, answer="1", points=Decimal("10.0"), unit_major="산염기"
        )
        make_score(exam4, self.student_a, Decimal("10.00"), max_score=Decimal("10"))
        body = self.get_detail(exam4)
        report = body["report"]
        self.assertEqual(report["summary"]["my_score"], 10.0)
        self.assertEqual(report["summary"]["percentile"], 50.0)  # (0+0.5)/1×100
        self.assertEqual(report["units"], [])
        self.assertEqual(len(report["questions"]), 1)
        self.assertIsNone(report["questions"][0]["result"])
        self.assertIsNone(report["questions"][0]["marked"])
        self.assertIsNone(report["questions"][0]["wrong_rate"])  # 응답 표본 없음
        self.assertEqual(report["wrong_answer_guides"], [])

    def test_query_budget(self):
        self.login_student()
        # 세션인증 2 + 학생 1 + 성적·시험 1 + 답안지 1 + 대단원 집계 1 + 문항 1
        # + 내 답안 1 + 오답률 집계 1 + 요약 집계 1 + 상위30 1 + 백분위 1
        # + 추이 성적 1 + 추이 답안지 1 + 추이 집계 1
        with self.assertNumQueries(15):
            self.assertEqual(self.client.get(self.detail_url(self.exam2)).status_code, 200)


class ParentGradesTests(GradeFixtureMixin, TestCase):
    """학부모 성적 조회 — 자녀 소유 검증(2차 슬라이스 패턴)·읽기 전용(PRD 3.4)."""

    def test_anonymous_denied(self):
        self.assertEqual(self.client.get(PARENT_GRADES).status_code, 403)

    def test_student_role_denied(self):
        self.login_student()
        self.assertEqual(self.client.get(PARENT_GRADES).status_code, 403)

    def test_default_child_is_first(self):
        """student_id 생략 → 첫 자녀(student_id 오름차순 — /api/me 드롭다운 순서)."""
        self.login_parent()
        res = self.client.get(PARENT_GRADES)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["student"]["student_id"], self.student_a.student_id)

    def test_child_selection(self):
        """두 번째 자녀 지정 — 성적 없는 자녀는 빈 목록(정상 조회)."""
        self.login_parent()
        res = self.client.get(f"{PARENT_GRADES}?student_id={self.student_z.student_id}")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["student"]["student_id"], self.student_z.student_id)
        self.assertEqual(body["exams"], [])
        self.assertEqual(body["trend"], [])

    def test_other_parents_child_404(self):
        """타인 자녀는 실존해도 404 — 존재 비노출(2차 슬라이스 패턴)."""
        self.login_parent()
        res = self.client.get(f"{PARENT_GRADES}?student_id={self.student_b.student_id}")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["detail"], "찾을 수 없습니다.")

    def test_unknown_student_404(self):
        self.login_parent()
        self.assertEqual(self.client.get(f"{PARENT_GRADES}?student_id=999999").status_code, 404)

    def test_invalid_student_id_400(self):
        self.login_parent()
        self.assertEqual(self.client.get(f"{PARENT_GRADES}?student_id=abc").status_code, 400)

    def test_list_same_as_student_view(self):
        """같은 자녀의 목록은 학생 본인 조회와 동일 페이로드(단일 조립 계약)."""
        self.login_student()
        student_body = self.client.get(STUDENT_GRADES).json()
        self.login_parent()
        parent_body = self.client.get(
            f"{PARENT_GRADES}?student_id={self.student_a.student_id}"
        ).json()
        self.assertEqual(parent_body, student_body)

    def test_detail_same_as_student_view(self):
        self.login_student()
        student_body = self.client.get(self.detail_url(self.exam2)).json()
        self.login_parent()
        parent_body = self.client.get(
            f"{self.detail_url(self.exam2, base=PARENT_GRADES)}"
            f"?student_id={self.student_a.student_id}"
        ).json()
        self.assertEqual(parent_body, student_body)

    def test_detail_other_child_404(self):
        self.login_parent()
        res = self.client.get(
            f"{self.detail_url(self.exam2, base=PARENT_GRADES)}"
            f"?student_id={self.student_b.student_id}"
        )
        self.assertEqual(res.status_code, 404)

    def test_write_methods_not_allowed(self):
        """읽기 전용(PRD 3.4) — GET 외 메서드 차단."""
        self.login_parent()
        self.assertEqual(self.client.post(PARENT_GRADES).status_code, 405)
        self.assertEqual(
            self.client.put(self.detail_url(self.exam2, base=PARENT_GRADES)).status_code, 405
        )
