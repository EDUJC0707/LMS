"""OMR 판독 영속 서비스 — 엔진 출력을 answer_sheets·sheet_answers 로 (PRD 3.1.1).

엔진(grades.omr)은 장당 둘 중 하나를 내놓는다: **보류**(카드를 못 찾았거나
마킹을 못 믿는다 — `None`) 또는 **판독**(`{문항번호: 칠해진 선택지 튜플}`).
이 모듈은 그 출력을 행으로 만든다. 업로드 뷰·태스크는 게이트·검증만 하고
저장 계약은 전부 여기다(서비스 모듈 원칙 — attendance_admin 선례).

## 답안지의 정체성 = (시험, 스캔 파일)

지면에는 일련번호가 없다. 그래서 정체성은 **내용에서** 와야 한다 — 호출자는
`scan_image_path` 를 페이지 바이트의 내용 주소로 발급한다(예:
`omr/{exam_id}/{sha256(페이지 바이트) 앞 24자}.png`). 그러면:

- **크래시 후 배치 재시도** = 같은 바이트 = 같은 경로 = 같은 행으로 수렴
- **같은 파일을 이름만 바꿔 재업로드**해도 주소가 바이트에서 오므로 수렴
- **같은 지면을 두 번 스캔**하면 바이트가 달라 별개 행이 된다 — 기계가 같은
  종이인지 알 방법이 없으므로 옳다. 두 장이 같은 학생으로 매칭되어 사람 눈에
  걸리는 것이 이 경우의 수렴 지점이다

경합은 `uq_answer_sheets_exam_scan` 이 막는다(get_or_create 가 충돌 시 기존
행을 다시 읽는다).

## 최신 판독이 이기고, 사람이 기계를 이긴다

재판독(엔진 개선·문항 입력 후 재실행)은 **기계 소유 값**을 마지막 판독으로
수렴시킨다. `is_corrected` 는 소유권 이전 표시다 — 켜진 행의 기계 기록 가능
필드는 사람 것이고, 재판독은 그 값을 덮지도 플래그를 끄지도 않는다:

- `AnswerSheet.is_corrected=True` → student·match_status·recognized_* 불변
- `SheetAnswer.is_corrected=True` → marked·result 불변, 행 삭제도 안 함
- `extra_practice_marked` 는 엔진이 아직 읽지 않으므로(card 판형에 추가
  마킹란 격자가 없다) 언제나 건드리지 않는다 — `extra_mark_corrected` 포함

시트 보정과 답 보정은 축이 다르다: 시트 보정은 "누구 것인가"의 확정이므로,
보정된 시트라도 **미보정 문항 행**은 재판독이 계속 갱신한다.

## 보류 = `비정상`

판독 불가 장도 사람이 봐야 하므로 행이 필요하다. 대조 6분기(PRD 3.1.1)에서
"판독 불가로 보류"가 서는 자리는 `비정상` 이고, exam_admin 의 보정 대기 집계
(match_status≠정상 AND is_corrected=false)에 자연히 걸린다 — 여섯 값으로
충분하다. 보류 장에는 인식 식별값도 저장하지 않는다: 보류는 그 장의 연필
통계를 못 믿는다는 판정이라, 같은 통계로 읽은 성명·전화 판독도 못 믿는다
(닫힘 기본값 — key_considerations §5). 이미 판독된 장이 재판독에서 보류로
바뀌면 미보정 문항 행을 걷어낸다 — 기계가 "내 판독을 못 믿겠다"고 한 값을
남겨 두면 안 믿을 데이터가 좋은 데이터처럼 보인다.

## 정답 키 전에는 시트만 — 판독 사본을 두지 않는다

`questions.answer` 는 NOT NULL 이다. 즉 **키 없는 문항 행은 존재할 수 없고**,
문항 행이 없으면 sheet_answers 도 못 만든다(FK). 문항 입력 전에 스캔된 배치는
시트 행(식별·매칭·스캔 경로)만 저장되고, 판독의 원본은 스캔 파일 자체다 —
문항 입력 후 엔진을 다시 돌려 이 함수로 재저장하면 수렴한다(멱등이라 안전).
판독을 JSON 사본으로 들고 있지 않는 이유: sheet_answers 와 두 벌이 되어 보정
뒤 어긋난다(사본 금지 — key_considerations §6, exam_admin 파생값 선례).

## result 는 쓰는 즉시 확정된다 — "채점전" 값이 필요 없다

행을 만들 수 있는 순간에는 키도 항상 손에 있다(위 문단). 무응답·복수마킹은
판독 사실이고, 단일 마킹은 그 자리에서 키와 대조해 정답/오답을 적는다.
scores 는 여기서 만들지 않는다(집계 슬라이스 몫) — exam_admin 의 처리 상태
파생(성적 0건 = 채점전)이 저장 후에도 그대로 참이다. 키가 나중에 정정되면
같은 판독으로 재저장하는 것이 곧 재채점이다(미보정 행만 다시 계산된다).
"""
from django.db import transaction

from .models import AnswerSheet, Exam, Question, Score, SheetAnswer

_MS = AnswerSheet.MatchStatus
_R = SheetAnswer.Result
_I = SheetAnswer.Issue

#: 재판독이 갱신하는 시트 필드 — 시트 보정(is_corrected)이 잠그는 것들.
_SHEET_MACHINE_FIELDS = (
    "student",
    "match_status",
    "recognized_matching_key",
    "recognized_name",
)


def store_sheet(
    exam,
    scan_image_path,
    readings,
    *,
    student=None,
    match_status=None,
    recognized_matching_key=None,
    recognized_name=None,
):
    """엔진 출력 1장 저장 — (sheet, summary). 계약은 모듈 docstring 전체.

    readings 는 `{문항번호: 칠해진 선택지 튜플}` 또는 None(보류). 매칭 결과
    (student·match_status·recognized_*)는 대조 6분기 매처가 넘긴다 — 보류면
    무시하고 `비정상`/None 으로 강제한다.

    summary: created(신규 여부) · answers_written(이번 판독을 반영한 행 수) ·
    answers_kept(보정 잠금으로 보존한 행 수) · answers_removed(걷어낸 기계
    행 수) · missing_questions(문항 행이 없어 미룬 문항번호 — 문항 입력 후
    재판독 대상).
    """
    if readings is None:
        student = None
        match_status = _MS.INVALID
        recognized_matching_key = None
        recognized_name = None
    elif match_status not in _MS.values:
        raise ValueError("판독된 장에는 match_status(대조 6분기)가 필요합니다.")
    with transaction.atomic():
        sheet, created = AnswerSheet.objects.select_for_update().get_or_create(
            exam=exam,
            scan_image_path=scan_image_path,
            defaults={
                "student": student,
                "match_status": match_status,
                "recognized_matching_key": recognized_matching_key,
                "recognized_name": recognized_name,
            },
        )
        if not created and not sheet.is_corrected:
            sheet.student = student
            sheet.match_status = match_status
            sheet.recognized_matching_key = recognized_matching_key
            sheet.recognized_name = recognized_name
            sheet.save(update_fields=_SHEET_MACHINE_FIELDS)
        written, kept, removed, missing = _apply_answers(sheet, exam, readings, created)
        scored = _apply_score(sheet, exam)
    return sheet, {
        "scored": scored,
        "created": created,
        "answers_written": written,
        "answers_kept": kept,
        "answers_removed": removed,
        "missing_questions": missing,
    }


def store_survey(
    exam,
    scan_image_path,
    score,
    *,
    student=None,
    match_status=None,
    recognized_matching_key=None,
    recognized_name=None,
    from_handwriting=False,
):
    """성적 조사 카드 1장 저장 — (sheet, summary). 모의고사(자기보고) 경로다.

    답안 카드와 다른 점은 **담을 것이 점수 하나**라는 것뿐이다. 문항이 없으니
    sheet_answers 도 없고, 채점도 없다 — 학생이 붙으면 그 점수가 곧 성적이다.

    보류(score=None)면 답안 카드와 같이 `비정상`으로 눕힌다. 정체성·멱등·보정
    잠금 계약은 모듈 docstring 그대로다.

    `from_handwriting` 은 그 점수가 버블이 아니라 OCR 에서 왔다는 표시다 —
    조교가 어느 쪽인지 알고 봐야 한다(보정 화면이 이 값으로 표시를 가른다).
    """
    if score is None:
        student = None
        match_status = _MS.INVALID
        recognized_matching_key = None
        recognized_name = None
    elif match_status not in _MS.values:
        raise ValueError("판독된 장에는 match_status(대조 6분기)가 필요합니다.")
    with transaction.atomic():
        sheet, created = AnswerSheet.objects.select_for_update().get_or_create(
            exam=exam,
            scan_image_path=scan_image_path,
            defaults={
                "student": student,
                "match_status": match_status,
                "recognized_matching_key": recognized_matching_key,
                "recognized_name": recognized_name,
                "recognized_score": score,
                "score_from_handwriting": from_handwriting,
            },
        )
        if not created and not sheet.is_corrected:
            sheet.student = student
            sheet.match_status = match_status
            sheet.recognized_matching_key = recognized_matching_key
            sheet.recognized_name = recognized_name
            sheet.recognized_score = score
            sheet.score_from_handwriting = from_handwriting
            sheet.save(
                update_fields=[
                    *_SHEET_MACHINE_FIELDS, "recognized_score", "score_from_handwriting"
                ]
            )
        scored = _apply_survey_score(sheet)
    return sheet, {"created": created, "scored": scored}


#: '안 넘겼음' 과 '넘겼는데 None(주인 해제)' 을 가른다.
UNSET = object()


def correct_sheet(sheet, *, student=UNSET, answers=None, score=UNSET, confirm=False):
    """조교 보정 1장 — 여기서 쓴 값은 재판독이 덮지 않는다(모듈 docstring).

    student 를 넘기면 그 장의 주인이 확정되고 대조 상태는 `정상` 이 된다 —
    기계가 못 고른 것을 사람이 골랐으므로 6분기를 더 볼 것이 없다. answers 는
    `{문항번호: "3"}`(무응답은 "", 복수는 "1,3") 이고, 손댄 문항만 보내면
    된다. 보류 장이라 문항 행이 아예 없어도 여기서 만든다 — 카드를 못 읽은
    지면도 사람은 읽을 수 있다.

    score 는 모의고사(자기보고) 장에서만 쓴다 — 조사 카드에는 문항이 없어
    고칠 것이 점수 한 칸뿐이다.

    confirm 은 "기계 판독이 맞다" 는 확인이다. 값은 그대로 두고 잠금만 건다.

    반환: 재계산된 총점(학생·정답 키가 없어 못 내면 None).
    """
    with transaction.atomic():
        sheet = AnswerSheet.objects.select_for_update().select_related("exam").get(pk=sheet.pk)
        fields = []
        if student is not UNSET:
            sheet.student = student
            sheet.match_status = _MS.MATCHED if student is not None else _MS.INVALID
            fields += ["student", "match_status"]
        if score is not UNSET:
            sheet.recognized_score = score
            # 사람이 적은 값이므로 더 이상 "손글씨에서 읽음"이 아니다.
            sheet.score_from_handwriting = False
            fields += ["recognized_score", "score_from_handwriting"]
        if fields or confirm:
            sheet.is_corrected = True
            sheet.save(update_fields=[*fields, "is_corrected"])
        if answers:
            _write_corrections(sheet, answers)
        if sheet.exam.kind == Exam.Kind.MOCK:
            return _apply_survey_score(sheet)
        return _apply_score(sheet, sheet.exam)


# --- 내부 부품 -----------------------------------------------------------


def _write_corrections(sheet, answers):
    """사람이 적은 문항 값을 잠금(is_corrected)과 함께 올린다."""
    questions = {q.q_number: q for q in Question.objects.filter(exam_id=sheet.exam_id)}
    rows = {row.question_id: row for row in sheet.answers.select_for_update()}
    for q_number, marked in answers.items():
        question = questions.get(q_number)
        if question is None:
            raise ValueError(f"{q_number}번 문항이 이 시험에 없습니다.")
        choices = tuple(int(part) for part in str(marked).split(",") if part.strip())
        value, result, issue = _verdict(choices, question.answer)
        row = rows.get(question.question_id)
        if row is None:
            SheetAnswer.objects.create(
                sheet=sheet, question=question, marked=value,
                result=result, issue_reason=issue, is_corrected=True,
            )
        else:
            row.marked, row.result, row.issue_reason = value, result, issue
            row.is_corrected = True
            row.save(update_fields=["marked", "result", "issue_reason", "is_corrected"])


def _apply_answers(sheet, exam, readings, created):
    """문항 행을 이번 판독으로 수렴 — (written, kept, removed, missing).

    행 단위 소유권 규칙(모듈 docstring)만 본다: 미보정 행은 갱신·삭제,
    보정 행은 그대로. 이번 판독에 없는 문항의 미보정 행은 지난 판독의
    잔재이므로 걷어낸다(보류 재판독이면 전부가 그 경우다).
    """
    existing = (
        {}
        if created
        else {answer.question_id: answer for answer in sheet.answers.select_for_update()}
    )
    written = kept = 0
    missing = []
    to_create, to_update = [], []
    if readings:
        questions = {q.q_number: q for q in Question.objects.filter(exam=exam)}
        for q_number in sorted(readings):
            question = questions.get(q_number)
            if question is None or not question.answer.strip():
                # 문항 행이 없다(=키가 없다) — 지금은 못 적고, 문항 입력 후
                # 재판독이 채운다. 카드 20행 중 시험 문항 수 밖의 행도 여기로
                # 떨어진다(영원히 문항이 없으므로 자연 무시).
                missing.append(q_number)
                continue
            marked, result, issue = _verdict(readings[q_number], question.answer)
            row = existing.pop(question.question_id, None)
            if row is None:
                to_create.append(
                    SheetAnswer(
                        sheet=sheet, question=question,
                        marked=marked, result=result, issue_reason=issue,
                    )
                )
                written += 1
            elif row.is_corrected:
                kept += 1
            else:
                written += 1
                if (row.marked, row.result, row.issue_reason) != (marked, result, issue):
                    row.marked, row.result, row.issue_reason = marked, result, issue
                    to_update.append(row)
    kept += sum(1 for row in existing.values() if row.is_corrected)
    stale_ids = [row.pk for row in existing.values() if not row.is_corrected]
    removed = 0
    if stale_ids:
        removed = SheetAnswer.objects.filter(pk__in=stale_ids).delete()[0]
    SheetAnswer.objects.bulk_create(to_create)
    if to_update:
        SheetAnswer.objects.bulk_update(to_update, ["marked", "result", "issue_reason"])
    return written, kept, removed, missing


def _verdict(choices, answer):
    """마킹 튜플 → (marked, result, issue). 축이 둘이다(models.SheetAnswer).

    깨끗한 단일 마킹일 때만 채점이 성립한다 — 그때 result 가 정답/오답이고
    issue 는 없다. 나머지 셋은 **채점이 아니라 사실**이라 result 가 NULL 이고
    issue 가 왜인지 말한다:

    - `무응답` — 학생이 안 풀었다
    - `복수마킹` — 진한 칸이 둘 이상. 어느 쪽이 진짜인지 기계는 안 고른다
      (X 로 지운 것인지 겹쳐 칠한 것인지 못 가른다). "1,3" 으로 둘 다 남긴다
    - `판독불가` — 기계가 못 읽었다. 무응답과 뭉치면 **학생이 안 푼 문항과
      기계가 놓친 문항이 같아 보인다**
    """
    if choices is None:
        return None, None, _I.UNREADABLE
    if not choices:
        return None, None, _I.BLANK
    if len(choices) > 1:
        return ",".join(str(choice) for choice in sorted(choices)), None, _I.MULTI
    marked = str(choices[0])
    return marked, (_R.CORRECT if marked == answer.strip() else _R.WRONG), None


def _apply_score(sheet, exam):
    """문항 행에서 총점을 다시 계산해 올린다. 점수를 낼 수 없으면 None.

    저장값이 아니라 **파생값**이라 매번 다시 센다 — 조교가 한 문항을 고치면
    총점도 따라와야 하고, 두 벌로 두면 반드시 어긋난다(설계 §6 사본 금지).

    학생이 안 붙은 장은 점수를 만들지 않는다. 누구 것인지 모르는 점수는
    성적표에 쓸 데가 없고, 조교가 확정한 뒤 재저장하면 그때 생긴다.
    """
    if sheet.student_id is None:
        return None
    rows = SheetAnswer.objects.filter(sheet=sheet).select_related("question")
    graded = [row for row in rows if row.question.answer]
    if not graded:
        return None
    total = sum(row.question.points for row in graded if row.result == SheetAnswer.Result.CORRECT)
    full = sum(question.points for question in Question.objects.filter(exam=exam))
    Score.objects.update_or_create(
        exam=exam,
        student_id=sheet.student_id,
        defaults={"total_score": total, "max_score": full, "is_taken": True},
    )
    return float(total)


def _apply_survey_score(sheet):
    """자기보고 점수를 그대로 성적으로 올린다. 점수·학생이 없으면 None.

    답안 카드처럼 다시 세지 않는다 — 셀 것이 없다. 지면에 적힌 수가 곧 점수다.

    만점(`max_score`)은 비워 둔다. 조사 카드는 만점을 말하지 않고, 과목마다
    다르다 — 50 이라고 적어 두면 기계가 지어낸 수가 실측처럼 남는다.
    """
    if sheet.student_id is None or sheet.recognized_score is None:
        return None
    Score.objects.update_or_create(
        exam_id=sheet.exam_id,
        student_id=sheet.student_id,
        defaults={"total_score": sheet.recognized_score, "is_taken": True},
    )
    return float(sheet.recognized_score)
