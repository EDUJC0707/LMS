"""성적·성적표 조회 서비스 — 학생·학부모 공용 (5차 슬라이스, PRD 3.2.1·3.1.1·§4).

학생(/api/student/grades*)과 학부모(/api/parent/grades*)가 같은 조립 함수를
쓴다 — 성적표 로직 이중 구현 금지(2차 슬라이스 home 선례). 뷰는 역할 게이트·
대상 학생 결정만 하고 페이로드 조립은 전부 여기서 한다.

집계 계약(key_considerations §6 — 계산 파생값 사본 저장 금지):
- 요약 통계(평균·표준편차·최고점·상위30%)는 Exam 캐시 컬럼 **저장값 우선**,
  없으면 scores 를 DB 집계(aggregate)로 조회 시 계산한다. 백분위는
  Score.percentile 저장값 우선, 없으면 응시자 분포 집계. 문항 오답률은
  Question.wrong_rate 저장값 우선, 없으면 sheet_answers 전체 응시자 집계.
  **어느 경로든 계산 결과를 캐시 컬럼에 되쓰지 않는다** (채움은 성적처리
  슬라이스의 몫 — 조회는 순수 읽기).
- 집계는 전부 DB 레벨(aggregate/annotate/values)이다. 파이썬은 집계 결과의
  페이로드 조립(누적 시리즈 나열·비율 나눗셈)만 담당한다.

수치 정의:
- 백분위 = (내 점수 미만 인원 + 동점 인원/2) / 응시 인원 × 100 (표준 정의,
  소수 2자리 — scores.percentile 정밀도와 일치)
- 상위 30% 점수 = 응시 인원 n 의 ceil(n×0.3)번째(내림차순) 점수
- 표준편차 = 모표준편차(응시자 전원이 모집단)
- 정답률·오답률 = 비율×100 소수 1자리. 오답률 분자는 비정답 전부
  (오답·무응답·복수마킹 — 맞히지 못한 응시자 비율)

경계 계약:
- 성적(Score) 행이 없는 시험은 "내 시험"이 아니다 — 상세는 None 반환(뷰가
  404, 시험 존재 비노출 — §4).
- 미응시(is_taken=false)는 목록에서 0점 표기, 상세에서 성적표 없음
  (PRD 3.1.1 — 성적표를 생성하지 않는다).
- 문항 축은 학생의 최신 답안지(재스캔 대비 sheet_id 최대) 기준.
- 오답 학습동선은 result=오답 문항만 — 무응답·복수마킹은 약점체크 대상
  계약(idx_sheet_answers_weak·PRD 3.1.8)과 같은 축으로 오답이 아니다.
- 테마 추이는 해당 시험까지(시험일·id 순)의 응시 회차를 대상으로 테마×회차
  DB 집계 후 누적 시리즈로 나열한다 — 프런트는 그리기만 한다(PRD 3.2.1).
"""
import math
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Max, Min, Q, Sum

from apps.curriculum.models import class_name_of

from . import scoring
from .models import AnswerSheet, Score, SheetAnswer


def build_grades_list(student):
    """목록 응답 — 내 시험(회차순) + 회차별 추이(PRD 3.2.1 성적 현황) 동시 조립.

    exams(표)와 trend(그래프)는 같은 1회 통계 계산을 나눠 담는다 — 표는
    시험명·일자·내 점수·평균·응시 여부, 추이는 본인 점수·백분위·평균·
    상위30%·최고점 5계열.
    """
    scores = list(
        Score.objects.filter(student=student)
        .select_related("exam")
        .order_by("exam__exam_date", "exam__exam_id")
    )
    exams = []
    trend = []
    for score in scores:
        exam = score.exam
        stats = summary_stats(exam)
        my_score = _my_score(score)
        exams.append(
            {
                "exam_id": exam.exam_id,
                "name": exam.name,
                "exam_date": exam.exam_date.isoformat(),
                "round_no": exam.round_no,
                "is_taken": score.is_taken,
                "my_score": my_score,
                "max_score": _full_marks(score),
                "average": stats["average"],
            }
        )
        trend.append(
            {
                "exam_id": exam.exam_id,
                "name": exam.name,
                "exam_date": exam.exam_date.isoformat(),
                "round_no": exam.round_no,
                "is_taken": score.is_taken,
                "my_score": my_score,
                "percentile": _percentile(score),
                "average": stats["average"],
                "top30_score": stats["top30_score"],
                "highest_score": stats["highest_score"],
            }
        )
    return {"student": _student_block(student), "exams": exams, "trend": trend}


def build_report(student, exam_id):
    """성적표 상세(PRD 3.2.1 최소 포함 항목). 내 성적 없는 시험은 None(뷰 404)."""
    score = (
        Score.objects.filter(student=student, exam_id=exam_id).select_related("exam").first()
    )
    if score is None:
        return None
    exam = score.exam
    payload = {
        "student": _student_block(student),
        "exam": {
            "exam_id": exam.exam_id,
            "name": exam.name,
            "exam_date": exam.exam_date.isoformat(),
            "round_no": exam.round_no,
            "notice": exam.notice,
        },
        "is_taken": score.is_taken,
    }
    if not score.is_taken:
        # 미응시 — 성적표를 생성하지 않는다(PRD 3.1.1 '성적표 없음')
        payload["report"] = None
        payload["message"] = "성적표 없음"
        return payload
    sheet = (
        AnswerSheet.objects.filter(exam=exam, student=student).order_by("-sheet_id").first()
    )
    stats = summary_stats(exam)
    questions = list(exam.questions.select_related("guide_video").order_by("q_number"))
    my_answers = _my_answers(sheet)
    wrong_rate_rows = _wrong_rate_rows(exam)
    payload["report"] = {
        "summary": {
            "my_score": score.total_score,
            "max_score": _full_marks(score),
            "average": stats["average"],
            "stddev": stats["stddev"],
            "highest_score": stats["highest_score"],
            "top30_score": stats["top30_score"],
            "percentile": _percentile(score),
        },
        "units": _unit_blocks(sheet),
        "questions": _question_rows(questions, my_answers, wrong_rate_rows),
        "wrong_answer_guides": _wrong_guides(questions, my_answers),
        "theme_trends": _theme_trends(student, exam),
    }
    return payload


# --- 공용 통계 부품(관리자 시험 조회가 재사용) ----------------------------


def summary_stats(exam, anonymous=None):
    """평균·표준편차·최고점·상위30% — 캐시 저장값 우선, 빠진 항목만 집계 보충.

    `anonymous` 는 이미 읽어 둔 익명 점수 목록이다(`scoring.anonymous_totals`).
    응시자 수까지 함께 내야 하는 호출자는 그 수를 세려고 어차피 같은 행을
    읽으므로, 넘겨받아 **같은 답안지를 두 번 묻지 않는다.**
    """
    stats = {
        "average": exam.avg_score,
        "stddev": exam.stddev,
        "highest_score": exam.max_score,
        "top30_score": exam.top30_score,
    }
    missing = [key for key, value in stats.items() if value is None]
    if not missing:
        return stats
    taken = exam.scores.filter(is_taken=True, total_score__isnull=False)
    # 익명 장(점수만 주고 신원을 안 밝힌 학생)도 같은 시험을 본 사람이다 —
    # 빼면 평균이 그 학생들 없이 나온다(scoring.anonymous_totals).
    if anonymous is None:
        anonymous = scoring.anonymous_totals(exam)
    totals = sorted(
        [row.total_score for row in taken] + [Decimal(value) for value in anonymous],
        reverse=True,
    )
    computed = _distribution(totals)
    if "top30_score" in missing:
        computed["top30_score"] = _cut_at_top30(totals)
    for key in missing:
        stats[key] = computed.get(key)
    return stats


def rate(numerator, denominator):
    """비율×100 소수 1자리. 표본 없음(분모 0)은 None — 0% 와 구분한다."""
    return round(numerator / denominator * 100, 1) if denominator else None


def _distribution(totals):
    """평균·모표준편차·최고점 — 익명 장까지 담은 목록에서 낸다."""
    if not totals:
        return {"average": None, "stddev": None, "highest_score": None}
    size = len(totals)
    mean = sum(totals) / size
    variance = sum((value - mean) ** 2 for value in totals) / size
    return {
        "average": mean,
        "stddev": Decimal(variance).sqrt(),
        "highest_score": max(totals),
    }


def _cut_at_top30(totals):
    """상위 30% 컷 — 내림차순 목록의 ceil(N x 0.3) 번째 점수."""
    if not totals:
        return None
    position = math.ceil(len(totals) * Decimal("0.3"))
    return totals[max(int(position), 1) - 1]



def _student_block(student):
    """성적표 학생 정보(PRD 3.2.1 — 성명·원번·학교). 홈 블록과 달리 원번을
    포함한다 — 성적표 스펙이 원번 표기를 명시(오배부 대조 축).

    반은 학생 1명분이라 여기서 읽는다(학생 목록이 아니므로 쿼리 1회 고정).
    """
    return {
        "student_id": student.student_id,
        "name": student.user.name if student.user else None,
        "login_id": student.user.login_id if student.user else None,
        "matching_key": student.matching_key,
        "school": student.school,
        "current_class": class_name_of(student),
    }


def _my_score(score):
    """내 점수 표기 — 미응시는 0점(PRD 3.1.1), 응시인데 총점 미산정이면 None."""
    if score.total_score is not None:
        return score.total_score
    return 0 if not score.is_taken else None


def _full_marks(score):
    """만점 — Score.max_score 저장값 우선, 없으면 문항 배점 합(저장 안 함)."""
    if score.max_score is not None:
        return score.max_score
    return score.exam.questions.aggregate(total=Sum("points"))["total"]


def _percentile(score):
    """백분위 — 저장값 우선, 없으면 응시자 분포 1회 집계(모듈 docstring 정의).

    폴백은 `scores` 행만 센다 — 익명 장은 빠진다. 저장값을 채우는
    `scoring.rank` 는 익명까지 담으므로 **두 값이 다를 수 있다.** 채점이 끝나는
    자리마다 `finalize_exam` 이 돌아 실서비스에서는 저장값이 늘 있고, 폴백은
    시드·구 데이터만 탄다. 지우지 않는 이유는 그쪽에서 백분위가 통째로 비기
    때문이다(docs/decisions.md 「익명 점수」).
    """
    if score.percentile is not None:
        return score.percentile
    if not score.is_taken or score.total_score is None:
        return None
    dist = score.exam.scores.filter(is_taken=True, total_score__isnull=False).aggregate(
        below=Count("pk", filter=Q(total_score__lt=score.total_score)),
        equal=Count("pk", filter=Q(total_score=score.total_score)),
        total=Count("pk"),
    )
    if not dist["total"]:
        return None
    return round((dist["below"] + dist["equal"] / 2) / dist["total"] * 100, 2)


def _my_answers(sheet):
    """내 답안 {question_id: SheetAnswer} — 채점표·학습동선이 공유(1쿼리)."""
    if sheet is None:
        return {}
    return {answer.question_id: answer for answer in sheet.answers.all()}


def _wrong_rate_rows(exam):
    """문항별 응답·비정답 수 — 전체 응시자 집계(오답률 계산 폴백 소스)."""
    rows = (
        SheetAnswer.objects.filter(question__exam=exam)
        .values("question_id")
        .annotate(
            answered=Count("pk"),
            # NULL 이 ~Q 에 안 걸린다(SQL 3값 논리) — 채점 안 된 줄도 "정답 아님"이다.
            not_correct=Count(
                "pk",
                filter=~Q(result=SheetAnswer.Result.CORRECT) | Q(result__isnull=True),
            ),
        )
    )
    return {row["question_id"]: row for row in rows}


def _unit_blocks(sheet):
    """② 대단원·중단원별 — questions.unit 축 × 내 답안(sheet_answers) DB 집계.

    문항 수·정답 수(틀린 수)·내 점수/단원 만점·정답률. 단원 순서는 시험지
    구성 순(단원 첫 문항 번호). 답안지가 없으면 빈 리스트(축 성립 불가).

    **중단원은 대단원 안에 중첩한다**(FLOW 4-3 "대단원·중단원에서 어디가
    무너지는지"). 같은 배열에 섞어 평탄하게 내면 `units` 를 세는 쪽이 조용히
    두 번 센다. 중단원이 비어 있는 문항은 행을 만들지 않는다 — 대단원 합계에
    이미 들어 있으므로 잃는 숫자가 없고, `미분류` 같은 이름을 지어내지 않는다.
    """
    if sheet is None:
        return []
    majors = [_unit_payload(row) for row in _unit_rows(sheet, "question__unit_major")]
    minors = defaultdict(list)
    for row in _unit_rows(sheet, "question__unit_major", "question__unit_minor"):
        minor = row["question__unit_minor"]
        if not minor:  # NULL 도 빈 문자열도 "중단원 없음"이다
            continue
        minors[row["question__unit_major"]].append(_unit_payload(row) | {"unit_minor": minor})
    for block in majors:
        block["minors"] = minors[block["unit_major"]]
    return majors


def _unit_rows(sheet, *group_fields):
    """단원 축 집계 1회 — 대단원과 중단원이 같은 숫자 집합을 쓴다."""
    return (
        SheetAnswer.objects.filter(sheet=sheet)
        .values(*group_fields)
        .annotate(
            question_count=Count("pk"),
            correct_count=Count("pk", filter=Q(result=SheetAnswer.Result.CORRECT)),
            my_points=Sum("question__points", filter=Q(result=SheetAnswer.Result.CORRECT)),
            unit_max_points=Sum("question__points"),
            first_q=Min("question__q_number"),
        )
        .order_by("first_q")
    )


def _unit_payload(row):
    """집계 행 → 응답 한 줄. 파이썬은 조립만 한다(모듈 docstring)."""
    return {
        "unit_major": row["question__unit_major"],
        "question_count": row["question_count"],
        "correct_count": row["correct_count"],
        "wrong_count": row["question_count"] - row["correct_count"],
        "my_points": row["my_points"] if row["my_points"] is not None else 0,
        "unit_max_points": row["unit_max_points"],
        "correct_rate": rate(row["correct_count"], row["question_count"]),
    }


def _question_rows(questions, my_answers, wrong_rate_rows):
    """③ 문항 채점표 — 번호·단원·배점·정답·내 마킹·채점 결과·오답률."""
    rows = []
    for question in questions:
        answer_row = my_answers.get(question.question_id)
        rows.append(
            {
                "q_number": question.q_number,
                "unit_major": question.unit_major,
                "unit_minor": question.unit_minor,
                "points": question.points,
                "answer": question.answer,
                "marked": answer_row.marked if answer_row else None,
                "result": answer_row.result if answer_row else None,
                # 채점 결과와 축이 다르다 — 복수마킹·무응답은 result 가 없다.
                "issue_reason": answer_row.issue_reason if answer_row else None,
                "wrong_rate": _wrong_rate(question, wrong_rate_rows),
            }
        )
    return rows


def _wrong_rate(question, wrong_rate_rows):
    """문항 오답률 — 저장값(Question.wrong_rate) 우선, 없으면 전체 응시자 집계."""
    if question.wrong_rate is not None:
        return question.wrong_rate
    row = wrong_rate_rows.get(question.question_id)
    if row is None:
        return None
    return rate(row["not_correct"], row["answered"])


def _wrong_guides(questions, my_answers):
    """④ 오답 문항 학습동선 — result=오답 문항의 학습가이드(PRD 3.2.1 신설).

    무응답·복수마킹은 제외한다(약점체크 대상 계약과 동일 축 — 모듈 docstring).
    틀린 문항이 없으면 빈 리스트(표시하지 않음). 가이드 영상은 있으면 함께.
    """
    guides = []
    for question in questions:
        answer_row = my_answers.get(question.question_id)
        if answer_row is None or answer_row.result != SheetAnswer.Result.WRONG:
            continue
        guides.append(
            {
                "q_number": question.q_number,
                "unit_major": question.unit_major,
                "theme_tag": question.theme_tag,
                "study_guide": question.study_guide,
                "guide_video": (
                    {
                        "video_id": question.guide_video.video_id,
                        "title": question.guide_video.title,
                    }
                    if question.guide_video
                    else None
                ),
            }
        )
    return guides


def _theme_trends(student, exam):
    """⑤ 테마별 누적 정답률 추이 — theme_tag 축 × 회차 누적(PRD 3.2.1 신설).

    대상 회차 = 이 시험까지(시험일·id 순)의 내 응시 회차. 테마×회차 셀은 DB
    집계 1회로 얻고, 회차 순서를 따라 누적 분자·분모를 이어붙여 시리즈를
    만든다(누적 나열은 조립이지 집계가 아니다). 테마 없는 문항은 제외.
    """
    included = list(
        Score.objects.filter(student=student, is_taken=True)
        .filter(
            Q(exam__exam_date__lt=exam.exam_date)
            | Q(exam__exam_date=exam.exam_date, exam__exam_id__lte=exam.exam_id)
        )
        .select_related("exam")
        .order_by("exam__exam_date", "exam__exam_id")
    )
    exam_ids = [row.exam_id for row in included]
    latest_sheets = (
        AnswerSheet.objects.filter(student=student, exam_id__in=exam_ids)
        .values("exam_id")
        .annotate(latest_sheet_id=Max("sheet_id"))
    )
    sheet_ids = [row["latest_sheet_id"] for row in latest_sheets]
    cells = (
        SheetAnswer.objects.filter(sheet_id__in=sheet_ids, question__theme_tag__isnull=False)
        .values("question__theme_tag", "sheet__exam_id")
        .annotate(
            total=Count("pk"),
            correct=Count("pk", filter=Q(result=SheetAnswer.Result.CORRECT)),
        )
    )
    by_theme = defaultdict(dict)
    for cell in cells:
        by_theme[cell["question__theme_tag"]][cell["sheet__exam_id"]] = cell
    trends = []
    for theme in sorted(by_theme):
        cumulative_correct = 0
        cumulative_total = 0
        points = []
        for row in included:
            cell = by_theme[theme].get(row.exam_id)
            if cell is None:
                continue  # 그 회차에 이 테마 문항 없음 — 점 없음
            cumulative_correct += cell["correct"]
            cumulative_total += cell["total"]
            points.append(
                {
                    "exam_id": row.exam_id,
                    "name": row.exam.name,
                    "exam_date": row.exam.exam_date.isoformat(),
                    "round_no": row.exam.round_no,
                    "correct": cell["correct"],
                    "total": cell["total"],
                    "rate": rate(cell["correct"], cell["total"]),
                    "cumulative_correct": cumulative_correct,
                    "cumulative_total": cumulative_total,
                    "cumulative_rate": rate(cumulative_correct, cumulative_total),
                }
            )
        trends.append({"theme": theme, "points": points})
    return trends
