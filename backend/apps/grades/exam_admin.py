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

from apps.accounts import student_directory

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
                "kind": exam.kind,
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
            "kind": exam.kind,
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
    (한 쿼리에 두 다:다 조인을 섞으면 집계가 곱으로 증식한다).

    "손봐야 할 장"은 두 가지다: **주인을 못 정한 장**(대조 6분기의 비정상 5종)과
    **못 읽은 줄이 있는 장**. 후자는 대조가 `정상` 이어도 사람이 봐야 한다 —
    안 세면 그 줄이 조용히 무응답처럼 지나간다(2026-08-12 줄 단위 보류 도입).
    """
    sheets = AnswerSheet.objects.filter(is_corrected=False).filter(
        ~Q(match_status=AnswerSheet.MatchStatus.MATCHED)
        | Q(answers__result=SheetAnswer.Result.UNREADABLE)
    ).distinct()
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
            unreadable=Count("pk", filter=Q(result=R.UNREADABLE)),
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
                # 학생이 안 푼 것(무응답)과 기계가 못 읽은 것은 다른 사실이다.
                "unreadable_count": cell.get("unreadable", 0),
                "correct_rate": report.rate(cell.get("correct", 0), answered),
            }
        )
    return rows


# --- 시험 만들기 · 정답 키 입력 (PRD 3.1.1 문항 정보 입력) -------------------


def create_exam(name, exam_date, round_no=None, target_grade=None, kind=None):
    """시험 한 건. 문항은 따로 넣는다 — 시험을 먼저 만들고 키는 나중에 채운다.

    kind 는 **어느 카드가 들어오는지**를 정한다(omr_ingest) — 모의고사는
    문항 없이 자기보고 점수만 오므로 정답 키를 채울 일이 없다.
    """
    return Exam.objects.create(
        name=name,
        exam_date=exam_date,
        round_no=round_no,
        target_grade=target_grade,
        kind=kind or Exam.Kind.MINI,
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


def sheet_rows(exam):
    """보정 화면 목록 — 손봐야 할 장이 먼저 온다.

    `정상`이면서 이미 확정된 장은 볼 일이 없으므로 뒤로 민다. 그 안에서는
    스캔 순서(sheet_id)를 지킨다 — 조교는 종이 묶음을 옆에 두고 넘긴다.
    """
    sheets = (
        AnswerSheet.objects.filter(exam=exam)
        .select_related("student__user")
        .annotate(
            unreadable=Count("answers", filter=Q(answers__result=SheetAnswer.Result.UNREADABLE)),
        )
        .annotate(
            settled=Q(is_corrected=True)
            & Q(match_status=AnswerSheet.MatchStatus.MATCHED)
            & Q(unreadable=0)
        )
        .order_by("settled", "sheet_id")
    )
    return [_sheet_row(sheet) for sheet in sheets]


def sheet_detail(sheet):
    """장 1건 — 문항은 정답 키 전량에 그 장의 판독을 붙인다.

    판독이 없는 문항도 줄을 내놓는다: 보류된 장은 행이 하나도 없고, 그때야말로
    사람이 손으로 채워 넣어야 하는 자리다.

    모의고사 장은 문항이 없어 questions 가 빈 목록이다 — 고칠 것은
    `recognized_score` 한 칸뿐이고, 화면은 그 차이로 갈린다.
    """
    marks = {row.question_id: row for row in sheet.answers.all()}
    questions = []
    for question in Question.objects.filter(exam_id=sheet.exam_id).order_by("q_number"):
        row = marks.get(question.question_id)
        questions.append(
            {
                "q_number": question.q_number,
                "answer": question.answer,
                "points": question.points,
                "marked": row.marked if row else None,
                "result": row.result if row else None,
                "is_corrected": bool(row and row.is_corrected),
            }
        )
    score = Score.objects.filter(exam_id=sheet.exam_id, student_id=sheet.student_id).first()
    return {
        **_sheet_row(sheet),
        "questions": questions,
        "total_score": float(score.total_score) if score else None,
    }


def _unreadable_count(sheet):
    """못 읽은 줄 수. 목록은 annotate 로 미리 세어 오고, 상세는 그 자리에서 센다."""
    counted = getattr(sheet, "unreadable", None)
    if counted is not None:
        return counted
    return sheet.answers.filter(result=SheetAnswer.Result.UNREADABLE).count()


def _sheet_row(sheet):
    return {
        "sheet_id": sheet.sheet_id,
        "match_status": sheet.match_status,
        "is_corrected": sheet.is_corrected,
        "recognized_name": sheet.recognized_name,
        "recognized_matching_key": sheet.recognized_matching_key,
        # 기계가 못 읽은 줄 수. 대조가 `정상` 이어도 이게 있으면 사람이 봐야 한다.
        "unreadable_count": _unreadable_count(sheet),
        # 모의고사(자기보고) 전용. 미니테스트 장에서는 언제나 null 이다.
        "recognized_score": sheet.recognized_score,
        # 그 점수가 버블이 아니라 손글씨 OCR 에서 왔다는 표시. 값만 보면 구분이
        # 안 되므로 화면이 이걸로 배지를 가른다.
        "score_from_handwriting": sheet.score_from_handwriting,
        # 명부와 같은 행 모양으로 낸다 — 보정 화면의 학생 선택기가 명부 API 로
        # 고르는 값과 같아야 "이미 붙은 학생"과 "지금 고른 학생"이 한 자리에 선다.
        "student": None if sheet.student is None else student_directory.row(sheet.student),
    }


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
