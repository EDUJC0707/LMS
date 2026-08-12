"""성적 집계 — 미제출 표기 · 백분위 · 석차 (PRD 3.1.1 · 3.2.1).

판독·저장이 끝난 **뒤** 시험 단위로 한 번 도는 층이다. `omr_store` 는 장 하나를
알고 여기는 시험 하나를 안다 — 백분위는 다른 학생을 봐야 나오므로 장 단위로는
낼 수 없다.

## "시험 봤나"의 단일 원천은 `scores.is_taken` 이다 (2026-08-12 확정)

같은 사실이 두 곳에 있었다. `attendances.exam_taken`(담임이 수업 중에 찍는 값)과
`scores.is_taken`(답안지가 들어왔나). **후자가 진실이다** — 시험을 봤다는 것의
관측 가능한 증거가 답안지이고, 담임의 입력은 스캔 전의 예측이다.

그래서 `exam_taken` 을 판정에 쓰지 않는다. 대신 배치 판독이 끝나면 여기서
**답안지가 안 들어온 학생의 성적 행을 `is_taken=False` 로 만든다.** 그 전에는
그 행을 아무도 안 만들어서(시드 제외) 미제출 학생이 성적 화면에 아예 없었다.

명단은 **그 시험을 본 회차의 출결**에서 온다(`class_sessions.exam`). 회차가
안 매여 있으면 명단을 알 수 없으므로 아무것도 만들지 않는다 — 지어내지 않는다.

## 익명 점수 — 누군지는 안 알려주고 점수만 준 학생

조사 카드에 **점수만 있고 성명·번호가 비어 있는 장**이 온다. 학생 입장에서
"평균 내는 데는 보태겠는데 내가 누군지는 알리기 싫다"는 것이고, 자기보고
지면이라 그럴 수 있다.

그 장은 **집계에는 들어가되 학생에게는 안 붙는다.** `scores` 행은 학생 FK 가
NOT NULL 이라 만들 수 없으므로, 평균·백분위의 모집단을 낼 때 **답안지 쪽에서
따로 끌어온다.**

**조교가 확정한 장만 센다**(`is_corrected=True` + 학생 없음). 아직 안 본 장까지
세면 평균이 먼저 나갔다가 조교가 주인을 찾는 순간 바뀐다 — 성적표가 두 번
다른 말을 한다. 확정은 보정 화면의 `확인` 이고, 그러면 보정 대기에서도 빠진다.

## 백분위는 저장값이지만 파생값이다

`report`·`exam_admin` 은 저장된 백분위를 **표시만** 한다(N+1 회피). 그 값을
채우는 것이 여기다. 점수가 하나라도 바뀌면 전원의 백분위가 흔들리므로,
채점이 끝나는 자리마다 통째로 다시 낸다.
"""
from decimal import ROUND_HALF_UP, Decimal

from apps.accounts.models import Student

from .models import AnswerSheet, ClassSession, Score

_CENT = Decimal("0.01")


def anonymous_totals(exam):
    """익명 확정 장의 점수들 — 평균·백분위의 모집단에 함께 들어간다.

    조교가 "주인 없이 이대로" 확정한 장만이다. 미확정 장은 아직 주인이 나올 수
    있으므로 세지 않는다.
    """
    return list(
        AnswerSheet.objects.filter(
            exam=exam, student=None, is_corrected=True, recognized_score__isnull=False
        ).values_list("recognized_score", flat=True)
    )


def finalize_exam(exam):
    """미제출 표기 + 백분위·석차. (미제출 생성 수, 순위 갱신 수).

    채점이 끝나는 자리마다 부른다 — 업로드·재판독·정답 키 수정·보정 저장.
    """
    return mark_missing(exam), rank(exam)


def mark_missing(exam):
    """답안지가 안 들어온 학생에게 `is_taken=False` 성적 행을 만든다.

    이미 성적이 있는 학생은 건드리지 않는다 — 답안지가 왔다는 뜻이다.
    """
    sessions = ClassSession.objects.filter(exam=exam)
    if not sessions.exists():
        # 회차가 안 매여 있으면 "이 시험을 봤어야 할 사람"을 알 수 없다.
        return 0
    roster = set(
        Student.objects.filter(attendances__session__in=sessions).values_list("pk", flat=True)
    )
    submitted = set(
        AnswerSheet.objects.filter(exam=exam)
        .exclude(student=None)
        .values_list("student_id", flat=True)
    )
    scored = set(Score.objects.filter(exam=exam).values_list("student_id", flat=True))
    missing = roster - submitted - scored
    Score.objects.bulk_create(
        [Score(exam=exam, student_id=pk, is_taken=False) for pk in sorted(missing)]
    )
    return len(missing)


def rank(exam):
    """응시자의 백분위·석차 상위 %를 다시 낸다. 미응시는 비운다.

    백분위 = (내 점수 미만 인원 + 동점 인원 / 2) / 응시 인원 × 100.
    동점을 반씩 나누는 표준 백분위 순위다 — 동점자 둘이 서로 다른 값을 받으면
    같은 점수에 다른 등급이 나간다.

    석차 상위 % = 공동 석차 / 응시 인원 × 100. 60점 넷 중 3등이 셋이면 셋 다 같다.
    """
    scores = list(
        Score.objects.filter(exam=exam, is_taken=True, total_score__isnull=False)
    )
    if not scores:
        return 0
    # 익명 장도 **같은 시험을 본 사람**이다. 모집단에서 빼면 남은 학생들의
    # 백분위가 실제보다 높게 나온다.
    totals = sorted(
        [score.total_score for score in scores]
        + [Decimal(total) for total in anonymous_totals(exam)],
        reverse=True,
    )
    size = len(totals)
    changed = []
    for score in scores:
        below = sum(1 for total in totals if total < score.total_score)
        tied = sum(1 for total in totals if total == score.total_score)
        percentile = _cent(Decimal(below + Decimal(tied) / 2) / size * 100)
        # 공동 석차 = 나보다 높은 사람 수 + 1
        above = sum(1 for total in totals if total > score.total_score)
        top_pct = _cent(Decimal(above + 1) / size * 100)
        if (score.percentile, score.rank_top_pct) != (percentile, top_pct):
            score.percentile, score.rank_top_pct = percentile, top_pct
            changed.append(score)
    if changed:
        Score.objects.bulk_update(changed, ["percentile", "rank_top_pct"])

    # 미응시는 순위가 없다 — 남아 있으면 지난 회차 값이 그대로 보인다.
    Score.objects.filter(exam=exam).exclude(pk__in=[s.pk for s in scores]).update(
        percentile=None, rank_top_pct=None
    )
    return len(changed)


def _cent(value):
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)
