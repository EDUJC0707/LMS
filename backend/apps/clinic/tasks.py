"""클리닉 주기 작업 — 감독 자료 수집.

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
from celery import shared_task

from . import supervision
from .conferencing import ConferenceError

#: beat 일정이 가리키는 이름. 문자열이 두 곳에서 갈리면 조용히 안 돈다.
COLLECT_TASK_NAME = "apps.clinic.tasks.collect_clinic_supervision"
DISPATCH_TASK_NAME = "apps.clinic.tasks.dispatch_clinic_supervision"


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


@shared_task(name=DISPATCH_TASK_NAME)
def dispatch_clinic_supervision():
    """시작한 클리닉에 감독을 걸어 둔다. 결과 건수를 돌려준다.

    **수집과 달리 늦으면 못 만회한다.** 수집은 며칠 뒤에 돌려도 같은 자료를
    가져오지만, 봇은 회의가 도는 동안에만 들어갈 수 있다. 그래서 주기가
    `supervision.DISPATCH_WINDOW` 보다 촘촘해야 하고, 그 관계는 테스트가 잡는다.

    구글 경로에서는 어댑터가 아무것도 하지 않는다(계약 기본값) — 켜 두어도
    해가 없고, 봇이 필요한 업체로 토글하는 순간 살아난다.
    """
    try:
        return supervision.dispatch()
    except ConferenceError as error:
        return {"started": 0, "failed": 0, "error": str(error)}
