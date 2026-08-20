"""클리닉 주기 작업 — 감독 자료 수집 · 시작 5분 전/후 알림.

**이 저장소의 첫 `@shared_task` 다**(2026-08-04). fly.toml·DEPLOY.md 6장이
"워커를 되살리는 트리거 = 첫 태스크 작성 시점" 이라고 적어 뒀는데, 그 조건이
여기서 충족된다. 다만 **배포는 일부러 안 한다**(2026-08-04 사용자 지시) —
코드만 세워 두고 워커·Redis 는 그대로 파킹이다. 켜는 절차는 DEPLOY.md 6장.

그래서 지금 이 태스크를 실제로 부르는 것은 아무것도 없다. 손으로 돌릴 길은
`manage.py collect_clinic_supervision` 로 그대로 남아 있고, 워커가 서는 날
beat 가 같은 일을 대신 부르기 시작한다.

**왜 Celery 인가**(Fly 스케줄 머신을 검토하고 접었다): 스케줄 머신은 월
$0.16 대 $3.32 로 훨씬 싸지만 ① 최소 주기가 매시라 30분을 못 맞추고
② `fly machine run` 이 명령형이라 fly.toml 에 안 잡혀 앱을 다시 세우면
아무도 모르게 사라지고 ③ Fly 를 떠나면 같이 못 간다. beat 일정은 코드에
선언돼 버전 관리되고, 어차피 알림 발송이 워커를 필요로 한다.
"""
import datetime

from celery import shared_task
from django.utils import timezone

from apps.notifications.models import Notification

from . import supervision
from .clinic_admin import CLINIC_REF_TYPE, queue_clinic_notification
from .conferencing import ConferenceError
from .models import ClinicRequest

#: beat 일정이 가리키는 이름. 문자열이 두 곳에서 갈리면 조용히 안 돈다.
COLLECT_TASK_NAME = "apps.clinic.tasks.collect_clinic_supervision"
REMINDER_TASK_NAME = "apps.clinic.tasks.send_clinic_reminders"

#: FLOW 3-7 의 그 5분 — 시작 5분 전과 시작 5분 후.
REMINDER_LEAD = datetime.timedelta(minutes=5)
#: 미참석 알림을 얼마나 늦게까지 부를지. 워커가 밀려 20분 뒤에 도는 날에도
#: 부르는 편이 맞지만(학생은 아직 안 왔다), 몇 시간 뒤는 소음이다.
REMINDER_LOOKBACK = datetime.timedelta(minutes=25)

#: 아직 처리 안 된 클리닉 출결 — 컬럼이 nullable 이라 값이 둘이다.
_UNMARKED = (None, ClinicRequest.AttendanceStatus.UNMARKED)


@shared_task(name=COLLECT_TASK_NAME)
def collect_clinic_supervision():
    """끝난 클리닉의 요약·문서 링크를 거둔다. 결과 건수를 돌려준다.

    **예외를 올리지 않는다.** 어댑터를 아예 못 만드는 경우(설정 누락·갱신 토큰
    만료)는 다음 주기에 그대로 다시 걸리는데, 그때마다 트레이스백을 던지면 워커
    로그가 그것으로 덮여 정작 봐야 할 것이 안 보인다. 개별 클리닉의 실패는
    `supervision.collect` 안에서 이미 건별로 세고 넘어간다.
    """
    try:
        return supervision.collect()
    except ConferenceError as error:
        return {"collected": 0, "waiting": 0, "failed": 0, "error": str(error)}


@shared_task(name=REMINDER_TASK_NAME)
def send_clinic_reminders(now=None):
    """시작 5분 전 · 시작 5분 후 미참석 알림(FLOW 3-7). 건 수를 돌려준다.

    **왜 주기 작업인가.** FLOW 3-7 은 배정 시점에 업체 예약 발송을 걸어 두는
    쪽을 적어 뒀지만, **5분 후 미참석은 예약으로 못 한다** — 보낼지 말지가
    그 시점의 출결(`미처리` 인가)에 달려 있고, 이미 온 학생에게 "참석하지 않고
    계십니다" 가 나가면 안 된다. 취소 하나로 지울 수 있는 종류가 아니다.
    5분 전만 예약으로 빼면 같은 두 문자가 두 경로로 갈라진다. 그래서 둘 다
    여기서 부른다(알리고 키가 오면 5분 전은 예약으로 옮길 수 있다).

    **이미 건 건은 다시 걸지 않는다** — 판정은 (type, ref_type, ref_id) 다.
    주기가 두 번 겹쳐 돌거나 창이 넓어져도 문자는 한 번이다. 조교의 수동
    재발송은 이 판정을 지나지 않는다(`notification_admin.resend` 가 행을
    복제하므로 여기서는 "이미 있다" 로 읽혀 자동 발송이 더 붙지 않는다).
    """
    now = now or timezone.localtime()
    upcoming, absent = [], []
    for request in _approved_on(now.date()):
        start = _start_at(request)
        if now < start <= now + REMINDER_LEAD:
            upcoming.append(request)
        elif (
            now - REMINDER_LEAD - REMINDER_LOOKBACK <= start <= now - REMINDER_LEAD
            and request.attendance_status in _UNMARKED
        ):
            absent.append(request)
    return {
        "reminder": _queue_once(
            Notification.Type.CLINIC_REMINDER, "클리닉 시작 5분 전", upcoming
        ),
        "absent": _queue_once(
            Notification.Type.CLINIC_NOSHOW_CHECK, "클리닉 미참석", absent
        ),
    }


def _approved_on(day):
    """그날 배정된 클리닉. 하루치라 파이썬에서 시각을 조립해도 값싸다.

    날짜·시간이 두 컬럼이라 DB 에서 시작 시각을 만들려면 표현식이 필요한데,
    한 타임 정원이 1 이고 하루 슬롯이 몇 개뿐이라 세어 봐야 한 자릿수다.
    """
    return ClinicRequest.objects.filter(
        status=ClinicRequest.Status.APPROVED, requested_date=day
    ).select_related("student")


def _start_at(request):
    return timezone.make_aware(
        datetime.datetime.combine(request.requested_date, request.requested_time)
    )


def _queue_once(type_, title, requests):
    if not requests:
        return 0
    already = set(
        Notification.objects.filter(
            type=type_,
            ref_type=CLINIC_REF_TYPE,
            ref_id__in=[r.clinic_id for r in requests],
        ).values_list("ref_id", flat=True)
    )
    queued = 0
    for request in requests:
        if request.clinic_id in already:
            continue
        # 받는 사람은 학생뿐이다(FLOW 3-11 #7·#8) — 지금 안 온 사람을 부르는
        # 문자라 학부모에게 갈 일이 아니다.
        queue_clinic_notification(type_, title, request, student=request.student)
        queued += 1
    return queued