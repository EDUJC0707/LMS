"""감독 자료 수집 — 끝난 클리닉의 요약·문서 링크를 평가에 붙인다 (PRD 3.2.4·8-5).

배정이 스페이스를 뚫고 회의가 전사·요약을 자동으로 남기는 것까지는 이미 돈다.
**여기는 그것을 가져와 `ClinicEvaluation` 에 얹는 자리**다. 이게 없으면
`ai_summary` 는 영원히 빈 칸이고 조교 평가에 근거가 없다.

## 아무 주기로나 돌려도 되게 만든다

한 번 가져온 건은 다시 묻지 않는다(`transcript_url` 이 있으면 대상에서 빠진다).
그래서 30분마다 돌리든 정오에 한 번 더 돌리든 결과가 같다 — 스케줄러를 아직
정하지 않았어도(Celery 미가동) 손으로 돌릴 수 있고, 나중에 무엇이 부르든 상관없다.

## 시한이 둘이다

- **아래쪽**: 회의가 끝나고 자료가 만들어지기까지 몇 분 걸린다(실측 3분).
  `COLLECT_DELAY` 만큼 기다렸다 묻는다 — 너무 일찍 물으면 늘 빈손이다.
- **위쪽**: 회의 기록은 종료 30일 뒤 사라진다(실측 `expireTime`). 그 뒤로는
  스페이스에서 문서로 가는 길이 끊긴다. 그래서 `RECORD_LIFETIME` 밖은 아예
  대상에서 뺀다 — 물어봐야 없다.

기준 시각은 진입점의 `timezone.now()` 하나로 고정한다(booking 선례).
"""
import datetime

from django.db import transaction
from django.utils import timezone

from .conferencing import ConferenceError, get_adapter
from .models import ClinicEvaluation, ClinicRequest

#: 회의가 끝나고 감독 자료가 만들어지기까지의 여유(실측 약 3분 — 열 배로 잡는다).
COLLECT_DELAY = datetime.timedelta(minutes=30)

#: 회의 기록 보존 기간. 이보다 오래된 건은 물어볼 곳이 없다.
RECORD_LIFETIME = datetime.timedelta(days=30)


def pending(now):
    """수집 대상 — 끝난 지 `COLLECT_DELAY` 넘고 `RECORD_LIFETIME` 안쪽인 배정 건.

    이미 가져온 건(`evaluation.transcript_url` 있음)은 빠진다 — 이 한 줄이
    "몇 번을 돌려도 같다"를 만든다.

    **우리가 만든 스페이스만** 대상이다. 관리자가 링크를 손으로 넣은 건은
    `conference_ref` 가 비어 있고, 남의 회의라 가져올 자료가 없다.
    """
    cutoff_new = timezone.localdate(now - COLLECT_DELAY)
    cutoff_old = timezone.localdate(now - RECORD_LIFETIME)
    return (
        ClinicRequest.objects.filter(
            status=ClinicRequest.Status.APPROVED,
            conference_ref__isnull=False,
            requested_date__lte=cutoff_new,
            requested_date__gte=cutoff_old,
        )
        .exclude(evaluation__transcript_url__isnull=False)
        .select_related("student__user")
        .order_by("clinic_id")
    )


def artifact_path(request):
    """저장소에 정리해 둘 경로 — 폴더·날짜는 영문/숫자, **이름만 한글**.

        clinic/2026-08/2026-08-04_1900_김하늘0001

    월을 `2026-08` 로 적는 이유는 정렬이다(`august` 는 8월이 4월 앞에 온다).
    끝 시각은 넣지 않는다 — 슬롯이 이미 정하고 있어서 두 곳에 적으면 언젠가
    어긋난다.

    **이름을 따로 붙이지 않는다.** 원번이 이미 `{이름}{휴대폰 뒷4}` 라서
    (decisions.md §1) 이름은 그 안에 들어 있고, 뒷4가 동명이인을 갈라 준다.
    학생 계정(User)이 아직 없는 예비등록 상태에서도 원번은 있으므로 경로가
    성립한다.
    """
    date = request.requested_date
    return (
        f"clinic/{date:%Y-%m}/{date:%Y-%m-%d}"
        f"_{request.requested_time:%H%M}_{request.student.unique_id}"
    )


def collect(now=None, adapter=None):
    """대상을 훑어 감독 자료를 붙인다. `{수집, 대기, 실패}` 건수를 돌려준다.

    **한 건이 실패해도 나머지는 계속 간다.** 업체가 한 회의에서 이상한 응답을
    주는 것이 그날 전체 수집을 멈출 이유는 없다 — 다음 차례에 다시 시도된다.
    """
    now = now or timezone.now()
    adapter = adapter or get_adapter()
    counts = {"collected": 0, "waiting": 0, "failed": 0}
    for request in pending(now):
        try:
            found = adapter.fetch_supervision(
                request.conference_ref, file_as=artifact_path(request)
            )
        except ConferenceError:
            # 일시적이든 영구적이든 이 건만 건너뛴다. 영구 실패도 다음 차례에
            # 다시 걸리지만, 30일이 지나면 대상에서 빠져 저절로 멎는다.
            counts["failed"] += 1
            continue
        if found is None:
            counts["waiting"] += 1
            continue
        _attach(request, found)
        counts["collected"] += 1
    return counts


def _attach(request, found):
    """평가 행에 감독 자료만 얹는다 — **판정은 건드리지 않는다**.

    관리자가 이미 적어 둔 `overall_result`·항목별 판단 위에 덮어쓰면 사람이 내린
    판단이 배치에 지워진다. get_or_create 로 행만 확보하고 세 칸만 채운다.
    """
    with transaction.atomic():
        evaluation, _ = ClinicEvaluation.objects.get_or_create(clinic=request)
        evaluation.transcript_ref = found.transcript_ref
        evaluation.transcript_url = found.transcript_url
        evaluation.ai_summary = found.summary
        evaluation.evaluated_at = timezone.now()
        evaluation.save(
            update_fields=["transcript_ref", "transcript_url", "ai_summary", "evaluated_at"]
        )
    return evaluation
