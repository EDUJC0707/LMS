"""Fireflies 어댑터 — 조교가 아이패드로 호스트할 때의 감독 자료 경로.

**왜 있나.** 구글의 전사·요약은 컴퓨터·안드로이드에서만 켜진다(아이폰·아이패드에는
버튼 자체가 없다 — `docs/2026-08-12-아이패드-전사-대안조사.md`). 조교가 아이패드를
쓰려면 사람 기기와 무관하게 기록을 남길 것이 필요하고, 그게 회의에 직접 들어오는
봇이다.

**이건 화상 업체가 아니다.** 방과 링크는 여전히 구글이 만든다 — 그래서
`create_space()` 는 화상 어댑터에 그대로 넘긴다. 이 클래스가 갈아 끼우는 것은
**감독 자료를 어디서 얻는가** 하나뿐이고, 그래서 `CLINIC_CONFERENCE_BACKEND` 를
이 경로로 바꾸는 것만으로 토글이 된다. 구글 코드는 지우지 않는다(2026-08-12 지시).

**구글과 결정적으로 다른 점 — 예약이 없다.** 구글은 스페이스를 만들 때 "전사를
켜라"를 실어 보내면 회의가 시작될 때 알아서 돈다. Fireflies 의 `addToLiveMeeting`
은 이름 그대로 **진행 중인 회의에만** 봇을 넣는다. 그래서 시작 시각 근처에
누군가 불러 줘야 하고, 그 일은 `supervision.dispatch` 가 맡는다.

**되찾는 열쇠는 제목이다.** 봇 투입 응답은 `success` 뿐이라 전사 ID 를 그 자리에서
받지 못한다. 그래서 넣을 때 제목에 `supervision.artifact_path` 를 실어 두고,
수집할 때 그 제목으로 목록에서 찾는다. 두 곳이 같은 문자열을 써야 성립하므로
`fetch_supervision` 의 `file_as` 와 `start_supervision` 의 `title` 은 **같은 값**이다.
"""
import json

from django.conf import settings

from .conferencing import (
    ConferenceAdapter,
    PermanentConferenceError,
    Supervision,
    TemporaryConferenceError,
)
from .google_meet import GoogleMeetAdapter, urllib_transport

GRAPHQL_ENDPOINT = "https://api.fireflies.ai/graphql"

TIMEOUT_SECONDS = 10

#: 다시 걸어볼 값어치가 있는 상태 코드(그 밖의 4xx 는 몇 번을 걸어도 같다).
_RETRYABLE_STATUSES = frozenset({408, 429})

#: `duration` 이 받는 범위. 밖으로 나가면 요청 전체가 거절된다.
MIN_MINUTES, MAX_MINUTES = 15, 120

#: 수집 때 훑는 최근 전사 개수. 20분 주기로 도는데 클리닉은 한 타임에 하나라
#: 넉넉하다 — 이보다 밀릴 정도면 수집이 멈춰 있었다는 뜻이고 그건 다른 문제다.
RECENT_LIMIT = 50

_DISPATCH = """
mutation($link: String!, $title: String, $language: String, $minutes: Int) {
  addToLiveMeeting(
    meeting_link: $link
    title: $title
    language: $language
    duration: $minutes
  ) { success }
}
"""

_RECENT = """
query($limit: Int) {
  transcripts(limit: $limit) {
    id
    title
    transcript_url
    summary { overview }
  }
}
"""


class FirefliesAdapter(ConferenceAdapter):
    """방은 구글에서, 감독 자료는 Fireflies 에서."""

    def __init__(self, transport=None, conference=None):
        self.transport = transport or urllib_transport
        # 화상은 위임한다 — 이 클래스는 방을 만들 줄 모른다.
        self.conference = conference or GoogleMeetAdapter(transport=transport)

    def create_space(self):
        return self.conference.create_space()

    def start_supervision(self, url, *, title, minutes):
        """진행 중인 회의에 봇을 넣는다. 실패는 예외로 알린다."""
        self._call(
            _DISPATCH,
            {
                "link": url,
                "title": title,
                "language": "ko",
                "minutes": max(MIN_MINUTES, min(MAX_MINUTES, minutes)),
            },
            "감독 봇을 넣지 못했습니다",
        )

    def fetch_supervision(self, ref, *, file_as=None):
        """우리가 붙인 제목으로 전사를 되찾는다. 아직 없으면 None(계약).

        `ref`(스페이스 이름)는 쓰지 않는다 — Fireflies 는 구글 스페이스를 모르고
        우리가 준 제목만 안다. 그래서 제목이 없는 건(관리자가 링크를 손으로 넣어
        봇을 넣은 적이 없는 건)은 물어볼 것이 없다.
        """
        if not file_as:
            return None
        data = self._call(_RECENT, {"limit": RECENT_LIMIT}, "감독 자료를 가져오지 못했습니다")
        for row in data.get("transcripts") or []:
            if row.get("title") != file_as:
                continue
            return Supervision(
                transcript_ref=row.get("id") or "",
                transcript_url=row.get("transcript_url") or "",
                # 요약이 비면 None 이되 링크는 남긴다 — 사람이 열어 보면 된다.
                summary=((row.get("summary") or {}).get("overview") or "").strip() or None,
            )
        return None

    # -- HTTP -------------------------------------------------------------

    def _call(self, query, variables, prefix):
        key = getattr(settings, "FIREFLIES_API_KEY", "")
        if not key:
            raise PermanentConferenceError("Fireflies API 키가 설정되지 않았습니다.")
        status, body = self.transport(
            "POST",
            GRAPHQL_ENDPOINT,
            json.dumps({"query": query, "variables": variables}).encode(),
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            TIMEOUT_SECONDS,
        )
        if status != 200:
            detail = body.decode(errors="replace")[:200]
            message = f"{prefix}({status}): {detail}"
            if status in _RETRYABLE_STATUSES or status >= 500:
                raise TemporaryConferenceError(message)
            raise PermanentConferenceError(message)
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise PermanentConferenceError(f"{prefix}: 응답을 읽을 수 없습니다.") from exc
        # GraphQL 은 실패를 200 에 담아 보낸다. 상태 코드만 보면 성공으로 읽히고
        # 그 자리에서 빈 값이 저장된다(조용한 성공 금지 — key_considerations §5).
        if payload.get("errors"):
            raise PermanentConferenceError(f"{prefix}: {payload['errors']}")
        return payload.get("data") or {}
