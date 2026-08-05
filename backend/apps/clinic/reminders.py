"""클리닉 시작 전 리마인더 (PRD 3.2.4 · 8-17 대기).

링크는 시작 **5분 전**부터 학생 화면에 뜬다(`booking.CLINIC_LINK_LEAD`). 그런데
그 시각에 학생이 LMS 를 열어 두고 있을 이유가 없다 — 알림이 그 자리를 메운다.

## 왜 6분인가

cron 이 1분마다 도니 최대 1분 늦게 잡힌다. 6분 전부터 대상으로 삼으면 **가장
늦어도 링크가 열리는 5분 전까지는** 나간다. 5분으로 잡으면 1분 늦는 순간 링크가
이미 열려 있는데 알림이 뒤따라오는 모양이 된다.

## 왜 업체 예약 발송이 아닌가

솔라피·알리고 모두 예약 발송을 지원하고, 배정 시점에 한 번 걸어 두면 크론이
아예 필요 없다. 그게 더 정확하다(초 단위). 다만 지금 알림 계약
(`notifications.sending.queue`)에는 **"지금 보내라"만 있고 예약이 없다.**
계약을 늘리는 것은 알림 트랙 소관이라, 그전까지는 매분 도는 배치로 메운다.
예약이 열리면 이 모듈은 통째로 사라지고 `clinic_admin.assign` 이 그 자리를 맡는다.

## 문구는 아직 임시다

카카오 알림톡은 사전 승인된 템플릿으로만 나가고(미결 8-17), 승인된 템플릿의
변수 구성이 정해지면 본문도 그 모양을 따라야 한다. 그래서 문구를 `_body()` 한
곳에만 두었다 — 승인이 나면 고칠 자리가 그 함수 하나다.
"""
import datetime

from django.utils import timezone

from apps.notifications.models import Notification
from apps.notifications.sending import queue

from .models import ClinicRequest

#: 시작 몇 분 전부터 대상으로 삼는가(위 머리말 — 링크 노출 5분 + cron 오차 1분).
REMINDER_LEAD = datetime.timedelta(minutes=6)

#: 알림이 가리키는 대상 종류. `Notification.ref_type` 은 FK 가 아닌 soft 링크다.
REF_TYPE = "clinic"


def due(now):
    """지금 보내야 할 `승인배정` 건 — 이미 보낸 것과 이미 시작한 것은 뺀다.

    **이미 보낸 것을 빼는 것이 이 함수의 핵심이다.** 매분 도는 배치라 중복이
    기본값이고, 알림은 한 번 나가면 되돌릴 수 없다.
    """
    sent = Notification.objects.filter(
        type=Notification.Type.CLINIC_REMINDER, ref_type=REF_TYPE
    ).values_list("ref_id", flat=True)
    candidates = ClinicRequest.objects.filter(
        status=ClinicRequest.Status.APPROVED,
        requested_date__in=(timezone.localdate(now), timezone.localdate(now + REMINDER_LEAD)),
    ).exclude(clinic_id__in=list(sent)).select_related("student")
    # 시작 시각 비교는 파이썬에서 한다 — 날짜·시각이 두 칸에 나뉘어 있어
    # DB 에서 합치려면 표현식이 필요하고, 후보가 하루치라 비용이 없다.
    return [r for r in candidates if now < starts_at(r) <= now + REMINDER_LEAD]


def starts_at(request):
    """클리닉 시작 시각. 날짜·시각 두 칸을 합치는 유일한 자리."""
    return timezone.make_aware(
        datetime.datetime.combine(request.requested_date, request.requested_time)
    )


def send_due(now=None):
    """대상에게 리마인더를 건다. 보낸 건수를 돌려준다.

    한 건이 실패해도 나머지는 계속 간다 — 한 학생의 번호가 비어 있다고 그 시각
    다른 클리닉의 알림까지 멎을 이유가 없다.
    """
    now = now or timezone.now()
    sent = 0
    for request in due(now):
        try:
            queue(
                type=Notification.Type.CLINIC_REMINDER,
                channel=Notification.Channel.KAKAO,
                student=request.student,
                title="클리닉 시작 안내",
                body=_body(request, now),
                ref_type=REF_TYPE,
                ref_id=request.clinic_id,
            )
        except Exception:
            continue
        sent += 1
    return sent


def _body(request, now):
    """알림 본문 — **승인된 템플릿이 오면 고칠 자리는 여기 하나다**(머리말).

    남은 분을 계산해서 넣는다. 창이 5~6분이라 "5분 뒤"로 고정해도 대개 맞지만,
    cron 이 밀리면 틀린 값이 나간다 — 틀린 숫자를 보내느니 세는 편이 낫다.
    """
    minutes = max(1, round((starts_at(request) - now).total_seconds() / 60))
    return f"{minutes}분 뒤 {request.requested_time:%H:%M} 클리닉이 시작됩니다."
