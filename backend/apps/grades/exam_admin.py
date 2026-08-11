"""관리자 시험 조회 서비스 — 성적처리 화면 근거 (5차 슬라이스, PRD 3.1.1).

목록·상세 모두 **조회 전용**이다 — 성적 수정·OMR 업로드는 OMR 인식 엔진과
함께 별도 슬라이스. 처리 상태는 저장 컬럼이 아니라 **파생값**이다(사본 저장
금지 — key_considerations §6):
- 채점전   = 성적(scores) 0건
- 보정필요 = 성적은 있으나 미보정 답안지 존재(match_status≠정상 AND
             is_corrected=false — PRD 3.1.1 대조 6분기의 비정상 5종)
- 완료     = 그 외

요약 통계는 소비자 성적표와 같은 계약(report.summary_stats — 캐시 저장값
우선, 없으면 집계). 학생별 백분위는 **저장값 표시만** 한다 — 학생 수 비례
집계(N+1)를 피하고, 계산·저장은 성적처리 슬라이스의 몫.
"""
from django.db import transaction
from django.db.models import Avg, Count, F, Q

from . import report
from .models import AnswerSheet, Exam, Question, Score, SheetAnswer


def load_exam(exam_id):
    """집계 annotate 포함 시험 1건. 없으면 None."""
    return _exam_queryset().filter(pk=exam_id).first()


def build_exam_list():
    """목록 — 응시자 수·평균·처리 상태(최근 시험 우선)."""
    exams = list(_exam_queryset().order_by("-exam_date", "-exam_id"))
    pending = _pending_sheet_counts()
    return {
        "exams": [
            {
                "exam_id": exam.exam_id,
                "name": exam.name,
                "exam_date": exam.exam_date.isoformat(),
                "round_no": exam.round_no,
                "target_grade": exam.target_grade,
                "taker_count": exam.taker_count,
                "score_count": exam.score_count,
                "average": exam.avg_score if exam.avg_score is not None else exam.computed_avg,
                "processing_status": _processing_status(
                    exam.score_count, pending.get(exam.exam_id, 0)
                ),
                "pending_sheet_count": pending.get(exam.exam_id, 0),
            }
            for exam in exams
        ]
    }


def build_exam_detail(exam):
    """상세 — 학생별 점수 테이블(정렬·석차) + 문항별 정답률(보정 화면 근거)."""
    pending_count = _pending_sheet_counts([exam.exam_id]).get(exam.exam_id, 0)
    stats = report.summary_stats(exam)
    scores = list(
        Score.objects.filter(exam=exam)
        .select_related("student__user")
        .order_by(F("total_score").desc(nulls_last=True), "student_id")
    )
    return {
        "exam": {
            "exam_id": exam.exam_id,
            "name": exam.name,
            "exam_date": exam.exam_date.isoformat(),
            "round_no": exam.round_no,
            "target_grade": exam.target_grade,
            "notice": exam.notice,
        },
        "stats": {
            "taker_count": exam.taker_count,
            "score_count": exam.score_count,
            "average": stats["average"],
            "stddev": stats["stddev"],
            "highest_score": stats["highest_score"],
            "top30_score": stats["top30_score"],
            "processing_status": _processing_status(exam.score_count, pending_count),
            "pending_sheet_count": pending_count,
        },
        "students": _student_rows(scores),
        "questions": _question_stat_rows(exam),
    }


# --- 내부 부품 -----------------------------------------------------------


def _exam_queryset():
    """시험 + 성적 집계 annotate — 목록·상세 공용(scores 단일 조인, 곱 증식 없음)."""
    return Exam.objects.annotate(
        taker_count=Count("scores", filter=Q(scores__is_taken=True)),
        score_count=Count("scores"),
        computed_avg=Avg("scores__total_score", filter=Q(scores__is_taken=True)),
    )


def _pending_sheet_counts(exam_ids=None):
    """시험별 미보정 답안지 수 {exam_id: n} — scores 조인과 분리한 별도 쿼리
    (한 쿼리에 두 다:다 조인을 섞으면 집계가 곱으로 증식한다)."""
    sheets = AnswerSheet.objects.filter(is_corrected=False).exclude(
        match_status=AnswerSheet.MatchStatus.MATCHED
    )
    if exam_ids is not None:
        sheets = sheets.filter(exam_id__in=exam_ids)
    return {
        row["exam_id"]: row["pending"]
        for row in sheets.values("exam_id").annotate(pending=Count("pk"))
    }


def _processing_status(score_count, pending_count):
    """처리 상태 파생 — 모듈 docstring 의 3분기."""
    if not score_count:
        return "채점전"
    if pending_count:
        return "보정필요"
    return "완료"


def _student_rows(scores):
    """학생별 점수 테이블 — 점수 내림차순(정렬은 쿼리), 동점 공동 석차(1224).

    석차는 정렬 결과의 표기 번호일 뿐 저장하지 않는다. 미응시·총점 미산정은
    석차 없음(정렬상 하단 — nulls_last).
    """
    rows = []
    rank = None
    previous_total = object()
    position = 0
    for score in scores:
        ranked = score.is_taken and score.total_score is not None
        if ranked:
            position += 1
            if score.total_score != previous_total:
                rank = position
                previous_total = score.total_score
        student = score.student
        rows.append(
            {
                "student_id": score.student_id,
                "name": student.user.name if student.user else None,
                "login_id": student.user.login_id if student.user else None,
                "matching_key": student.matching_key,
                "current_class": student.current_class,
                "total_score": score.total_score,
                "max_score": score.max_score,
                "percentile": score.percentile,  # 저장값 표시만(모듈 docstring)
                "is_taken": score.is_taken,
                "rank": rank if ranked else None,
            }
        )
    return rows


def _question_stat_rows(exam):
    """문항별 정답률 + 결과 분포(무응답·복수마킹 — PRD 마킹 이상 경고 근거).

    보정 화면의 실측 근거이므로 저장 캐시(wrong_rate)가 아니라 현재 답안
    전량 집계를 보여준다(보정 반영 즉시 갱신되는 값이어야 한다).
    """
    R = SheetAnswer.Result
    cells = {
        row["question_id"]: row
        for row in SheetAnswer.objects.filter(question__exam=exam)
        .values("question_id")
        .annotate(
            answered=Count("pk"),
            correct=Count("pk", filter=Q(result=R.CORRECT)),
            wrong=Count("pk", filter=Q(result=R.WRONG)),
            blank=Count("pk", filter=Q(result=R.BLANK)),
            multi=Count("pk", filter=Q(result=R.MULTI)),
        )
    }
    rows = []
    for question in Question.objects.filter(exam=exam).order_by("q_number"):
        cell = cells.get(question.question_id, {})
        answered = cell.get("answered", 0)
        rows.append(
            {
                "question_id": question.question_id,
                "q_number": question.q_number,
                "unit_major": question.unit_major,
                "unit_minor": question.unit_minor,
                "points": question.points,
                "answer": question.answer,
                "answered_count": answered,
                "correct_count": cell.get("correct", 0),
                "wrong_count": cell.get("wrong", 0),
                "blank_count": cell.get("blank", 0),
                "multi_count": cell.get("multi", 0),
                "correct_rate": report.rate(cell.get("correct", 0), answered),
            }
        )
    return rows


# --- 시험 만들기 · 정답 키 입력 (PRD 3.1.1 문항 정보 입력) -------------------


def create_exam(name, exam_date, round_no=None, target_grade=None):
    """시험 한 건. 문항은 따로 넣는다 — 시험을 먼저 만들고 키는 나중에 채운다."""
    return Exam.objects.create(
        name=name, exam_date=exam_date, round_no=round_no, target_grade=target_grade
    )


def save_questions(exam, rows):
    """정답 키 저장 — `[{q_number, answer, points, unit_major, unit_minor}]`.

    문항번호로 upsert 한다. 보내지 않은 문항은 **답안 행이 없을 때만** 지운다 —
    이미 채점된 문항을 지우면 SheetAnswer 가 연쇄 삭제되어 판독 결과가 날아간다.

    배점은 안 주면 1점. 단원은 비워도 된다(채점에 안 쓴다 — models 참조).
    """
    with transaction.atomic():
        seen = []
        for row in rows:
            number = int(row["q_number"])
            Question.objects.update_or_create(
                exam=exam,
                q_number=number,
                defaults={
                    "answer": str(row.get("answer") or "").strip(),
                    "points": row.get("points") or 1,
                    "unit_major": (row.get("unit_major") or "").strip(),
                    "unit_minor": (row.get("unit_minor") or "").strip() or None,
                },
            )
            seen.append(number)
        stale = Question.objects.filter(exam=exam).exclude(q_number__in=seen)
        stale.filter(sheet_answers__isnull=True).delete()
    return question_rows(exam)


def question_rows(exam):
    """문항 목록 — 키 입력 화면이 그대로 쓰는 모양."""
    return [
        {
            "q_number": q.q_number,
            "answer": q.answer,
            "points": q.points,
            "unit_major": q.unit_major,
            "unit_minor": q.unit_minor,
        }
        for q in Question.objects.filter(exam=exam).order_by("q_number")
    ]


def unit_options():
    """이미 쓴 단원들 — 대단원 하나에 중단원 여럿. 별도 표를 두지 않는다.

    쓸수록 채워지고, 새 단원은 그냥 입력하면 다음부터 후보로 뜬다.
    """
    options = {}
    pairs = (
        Question.objects.exclude(unit_major="")
        .values_list("unit_major", "unit_minor")
        .distinct()
    )
    for major, minor in pairs:
        options.setdefault(major, set())
        if minor:
            options[major].add(minor)
    return {major: sorted(minors) for major, minors in sorted(options.items())}
