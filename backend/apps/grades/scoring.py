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

명단은 **그 시험을 가리키는 회차의 반**에서 온다(`class_sessions.exam` → `klass`).
회차가 안 매여 있으면 명단을 알 수 없으므로 아무것도 만들지 않는다 —
지어내지 않는다. 출결 행이 있는 학생도 함께 센다: 현보로 온 학생은 이 반에
수강이 없지만 그 자리에서 시험을 봤다(FLOW 3-4).

**시험 하나를 반 여럿이 가리킨다**(FLOW 3-3 — 시험은 커리 주차에 붙는다).
그래서 명단은 반마다 따로 세고, **답안지도 성적도 하나 없는 반은 뺀다** —
목반이 목요일에 본 시험을 화반은 다음 화요일에 보므로, 안 가르면 아직 시험을
치지도 않은 반이 그날 통째로 미제출이 된다.

## OMR 이 대조되면 출석이 찍힌다 (2026-08-19)

FLOW 3-2 는 **OMR → 출결표 한 방향**이다. 대조가 `정상` 인 장은 그 학생이
그 자리에 앉아 답안지를 냈다는 물증이므로 출결을 `출석` 으로 올린다 —
조교가 같은 명단을 OMR 에서 한 번, 출결표에서 또 한 번 찍고 있었다.

**사람이 찍은 값은 안 건드린다.** 가르는 근거는 `attendances.marked_by` 다 —
사람이 지나간 행에는 그 사람이 남아 있고, OMR 이 만든 행은 비어 있다. 그래서
조교가 `출석` 을 `결석` 으로 고쳐도, 눌렀던 것을 해제해 `미입력` 로 되돌려도
다시 판독을 돌린 OMR 이 그것을 뒤집지 못한다.

**되돌리지도 않는다.** 재판독으로 어떤 장이 보류가 되어 주인을 잃어도 이미
찍힌 `출석` 은 그대로 둔다 — 출결을 지우면 영상 권한이 회수되고 상담 대기열이
움직인다. 잘못 붙은 출결을 걷는 것은 사람이 할 일이다(파괴적 작업은 수동).

## 익명 점수 — 누군지는 안 알려주고 점수만 준 학생

조사 카드에 **점수만 있고 성명·번호가 비어 있는 장**이 온다. 학생 입장에서
"평균 내는 데는 보태겠는데 내가 누군지는 알리기 싫다"는 것이고, 자기보고
지면이라 그럴 수 있다.

그 장은 **집계에는 들어가되 학생에게는 안 붙는다.** `scores` 행은 학생 FK 가
NOT NULL 이라 만들 수 없으므로, 평균·백분위의 모집단을 낼 때 **답안지 쪽에서
따로 끌어온다.**

**조교가 확정한 장만 센다**(`is_corrected=True` + 학생 없음). 아직 안 본 장까지
세면 평균이 먼저 나갔다가 조교가 주인을 찾는 순간 바뀐다 — 성적표가 두 번
다른 말을 한다. 확정은 보정 화면의 `익명으로 확정` 이고(주인을 고른 장에서는
같은 자리가 `확인` 이다), 그러면 보정 대기에서도 빠진다.

## 클리닉 대상도 여기서 정해진다 (2026-08-19)

판정을 만드는 코드가 시드 말고는 없었다. 신청 화면은 판정이 없는 학생을 403 으로
막으므로(`clinic.booking._ensure_can_book`) 시드 밖에서는 아무도 클리닉을 못 잡는다.
첫 수업에서 시험을 보니 오픈 첫 주에 걸린다.

조건 셋은 FLOW 3-7 이 정한 그대로 — **출석 + 응시 + 평균 미달**. 원천은 전부 밖에
있고(`attendances` · `scores`) 이 표에는 결과와 쓴 기준점만 남는다(모델 계약).

**사람이 판정한 행은 안 건드린다** — `determined_by` 가 차 있으면 넘어간다.
출석을 찍을 때와 같은 축이다.

## 백분위는 저장값이지만 파생값이다

`report`·`exam_admin` 은 저장된 백분위를 **표시만** 한다(N+1 회피). 그 값을
채우는 것이 여기다. 점수가 하나라도 바뀌면 전원의 백분위가 흔들리므로,
채점이 끝나는 자리마다 통째로 다시 낸다.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from apps.clinic.models import ClinicEligibility

from . import attendance_admin
from .models import AnswerSheet, Attendance, ClassSession, Score

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
    """출석 · 미제출 · 백분위·석차 · 클리닉 대상. (미제출 생성 수, 순위 갱신 수).

    채점이 끝나는 자리마다 부른다 — 업로드·재판독·정답 키 수정·보정 저장.
    순서가 곧 의존이다: 출석을 먼저 찍어야 조교 보정으로 주인이 정해진 장도 같은
    자리에서 출결에 닿고, 미제출 행이 있어야 "봤어야 할 사람" 전원이 클리닉
    판정에 들어오며, 기준점은 그 시험 전체 점수가 다 모인 뒤에야 나온다.
    """
    mark_present(exam)
    missing, ranked = mark_missing(exam), rank(exam)
    mark_clinic_targets(exam)
    return missing, ranked


def mark_present(exam):
    """대조가 `정상` 인 학생을 그 회차 출결 `출석` 으로 올린다. (찍은 수)

    **출결 저장 경로를 그대로 탄다**(`attendance_admin.apply_entries`) — 출결이
    바뀌면 복습영상 지급·상담 대기열이 따라 움직이므로 직접 UPDATE 하면 그게
    다 안 돈다. 입력자(`marked_by`)는 비운다: 사람이 아니라 판독이 찍은 값이고,
    그 빈칸이 곧 "OMR 이 다시 덮어도 되는 자리"의 표시다(모듈 docstring).

    `미입력` 이 기본값이므로(FLOW 3-4) 대조되지 않은 학생은 건드리지 않는다 —
    결석으로 찍으면 그 학부모에게 결석 문자가 나간다.
    """
    sessions = list(ClassSession.objects.filter(exam=exam))
    if not sessions:
        return 0
    matched = set(
        AnswerSheet.objects.filter(exam=exam, match_status=AnswerSheet.MatchStatus.MATCHED)
        .exclude(student=None)
        .values_list("student_id", flat=True)
    )
    if not matched:
        return 0
    marked = 0
    for session in sessions:
        roster_ids = attendance_admin.entry_target_ids(attendance_admin.load_roster(session))
        targets = [sid for sid in roster_ids if sid in matched]
        if not targets:
            continue
        att_map = attendance_admin.load_attendance_map(session, targets)
        entries = [
            {"student_id": sid, "status": Attendance.Status.PRESENT}
            for sid in targets
            if _untouched(att_map.get(sid))
        ]
        if entries:
            attendance_admin.apply_entries(session, entries, None, roster_ids)
            marked += len(entries)
    return marked


def _untouched(att):
    """사람이 손대지 않은 자리인가 — OMR 이 써도 되는 조건(모듈 docstring)."""
    return att is None or (
        att.status == Attendance.Status.UNENTERED and att.marked_by_id is None
    )


def mark_missing(exam):
    """답안지가 안 들어온 학생에게 `is_taken=False` 성적 행을 만든다.

    이미 성적이 있는 학생은 건드리지 않는다 — 답안지가 왔다는 뜻이다.
    **아직 흔적이 없는 반은 통째로 건너뛴다**(모듈 docstring) — 같은 시험을
    다른 요일에 보는 반이 있기 때문이다.
    """
    sessions = list(ClassSession.objects.filter(exam=exam))
    if not sessions:
        # 회차가 안 매여 있으면 "이 시험을 봤어야 할 사람"을 알 수 없다.
        return 0
    submitted = set(
        AnswerSheet.objects.filter(exam=exam)
        .exclude(student=None)
        .values_list("student_id", flat=True)
    )
    scored = set(Score.objects.filter(exam=exam).values_list("student_id", flat=True))
    # 이 시험을 이미 치른 표시 — 들어온 답안지거나 이미 난 성적이다.
    evidence = submitted | scored
    roster = set()
    for session in sessions:
        # 출결 행만 보면 **아무도 안 걸린다** — 조교가 출결표를 열기 전이면 행이
        # 없고, OMR 이 찍은 행은 제출한 학생뿐이라 빼고 나면 남는 것이 없다.
        # 봤어야 할 사람은 그 회차 반의 명단이다(퇴원생 제외 — 입력 대상이 아니다).
        ids = set(attendance_admin.entry_target_ids(attendance_admin.load_roster(session)))
        ids |= set(session.attendances.values_list("student_id", flat=True))
        # **아무 흔적도 없는 반은 아직 안 봤다.** 시험은 커리 주차에 붙으므로
        # (FLOW 3-3) 목반이 목요일에 본 시험을 화반은 다음 화요일에 본다 —
        # 여기서 안 가르면 화반 전원이 그날 미제출로 찍히고, 클리닉 판정까지
        # 따라 돈다.
        if ids & evidence:
            roster |= ids
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


def mark_clinic_targets(exam):
    """출석 + 응시 + 평균 미달 → `ClinicEligibility`. (대상자 수)

    미대상도 행을 남긴다 — 사유(`결석`·`미응시`·`평균이상`)가 화면이 "왜 나는
    신청을 못 하나"에 답하는 유일한 값이고, 행이 없는 것과 대상이 아닌 것을
    가르지 못하면 판정이 아직 안 돈 것인지 알 수 없다.

    **출석은 이 시험이 걸린 회차의 `출석` 이다.** 현보로 온 학생은 방문한 반
    회차에 `출석` 이 찍혀 있으므로 그대로 걸리고, 그 반의 점수로 판정된다
    (FLOW 3-4 "클리닉은 이 반의 평균을 따른다") — 따로 갈라 볼 것이 없다.
    """
    scores = list(Score.objects.filter(exam=exam))
    if not scores:
        return 0
    threshold = _threshold(exam, scores)
    if threshold is None:
        return 0
    present = set(
        Attendance.objects.filter(
            session__exam=exam, status=Attendance.Status.PRESENT
        ).values_list("student_id", flat=True)
    )
    decided = set(
        ClinicEligibility.objects.filter(
            exam=exam, determined_by__isnull=False
        ).values_list("student_id", flat=True)
    )
    now = timezone.now()
    targets = 0
    for score in scores:
        if score.student_id in decided:
            continue
        if score.student_id not in present:
            is_target, reason = False, ClinicEligibility.Reason.ABSENT
        elif not score.is_taken or score.total_score is None:
            is_target, reason = False, ClinicEligibility.Reason.NOT_TAKEN
        elif score.total_score >= threshold:
            is_target, reason = False, ClinicEligibility.Reason.ABOVE_AVG
        else:
            is_target, reason = True, None
        ClinicEligibility.objects.update_or_create(
            exam=exam,
            student_id=score.student_id,
            defaults={
                "is_target": is_target,
                "reason": reason,
                "cutoff_score": threshold,
                "determined_at": now,
            },
        )
        targets += is_target
    return targets


def _threshold(exam, scores):
    """평균 미달의 기준점 — **컷이 있으면 그것, 없으면 그 시험 전체 평균**.

    컷은 시험에 미리 넣어 둔다(FLOW 3-3·3-7 — `Exam.clinic_cutoff`). 비어 있을
    때의 평균은 `exam_admin._average` 와 같은 축으로 낸다 — 저장 캐시 우선, 없으면
    응시 점수와 익명 확정 장을 합쳐서. 화면이 보여 주는 평균과 판정에 쓴 기준점이
    갈리면 "평균 아래인데 왜 대상이 아니냐"를 설명할 수 없다.
    """
    if exam.clinic_cutoff is not None:
        return exam.clinic_cutoff
    if exam.avg_score is not None:
        return exam.avg_score
    totals = [s.total_score for s in scores if s.is_taken and s.total_score is not None]
    totals += [Decimal(total) for total in anonymous_totals(exam)]
    # 저장 자리가 소수 둘째 자리까지다 — 여기서 맞춰 두지 않으면 판정에 쓴 값과
    # 행에 남은 값이 갈려 "기준점 56.67 인데 왜 미달이 아니냐"가 된다.
    return _cent(sum(totals) / len(totals)) if totals else None
