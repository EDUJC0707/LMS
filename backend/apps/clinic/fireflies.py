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

#: 같은 제목이 몇 개까지 나올 수 있나. 정상은 1이고 2를 넘길 이유가 없다
#: (아래 `fetch_supervision` 의 중복 설명) — 넉넉히 잡아도 이 정도면 충분하다.
TITLE_MATCH_LIMIT = 10

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

#: 제목으로 **서버에서** 거른다. 최근 목록을 끌어와 파이썬에서 훑으면 수집이
#: 며칠 밀렸을 때 그 클리닉이 목록 끝 밖으로 떨어져 나가 영영 못 찾는다.
_BY_TITLE = """
query($title: String, $limit: Int) {
  transcripts(title: $title, limit: $limit) {
    id
    title
    duration
    is_live
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

    def schedule_supervision(self, url, *, key, title, starts_at, minutes):
        """감독 예약 = **연결된 캘린더에 일정 한 건**.

        Fireflies 를 부르지 않는다. 이 업체는 붙어 있는 구글 캘린더를 보고
        시작 시각에 알아서 들어오므로, 예약이란 곧 그 캘린더에 클리닉을 올려
        두는 일이다(계정이 `hjcedu@hjcedu.com` 으로 같다 — 2026-08-12 확인).
        구글 API 지식은 화상 어댑터에 있으니 그쪽에 넘긴다.

        일정 제목이 그대로 **전사 제목**이 되고, 그래서 `fetch_supervision` 의
        `file_as` 와 같은 값이어야 나중에 되찾을 수 있다.
        """
        self.conference.upsert_event(
            key, title=title, url=url, starts_at=starts_at, minutes=minutes
        )

    def cancel_supervision(self, key):
        self.conference.delete_event(key)

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
        # **경로를 통째로 보내면 안 된다.** 업체 필터는 정확 일치가 아니라 단어
        # 검색이고 `/` 는 색인에 없다 — 전체 경로로 물으면 있는 것도 0건으로
        # 돌아온다(2026-08-12 실측). 마지막 조각은 날짜+시각+원번이라 이미
        # 유일하므로 그걸로 좁히고, 전체 제목 확정은 아래에서 우리가 한다.
        data = self._call(
            _BY_TITLE,
            {"title": file_as.rsplit("/", 1)[-1], "limit": TITLE_MATCH_LIMIT},
            "감독 자료를 가져오지 못했습니다",
        )
        rows = [
            r
            for r in data.get("transcripts") or []
            # 서버는 좁히기만 하고 확정은 우리가 한다 — 부분 일치가 남의 요약을
            # 이 학생 평가에 붙이는 것보다 한 차례 더 기다리는 편이 낫다.
            if r.get("title") == file_as and not r.get("is_live")
        ]
        if not rows:
            return None
        # 같은 제목이 둘 나올 수 있다: 학생이 **같은 날 같은 시각**으로 취소하고
        # 다시 잡으면 `artifact_path` 가 글자 그대로 같아진다. 그때는 **가장 긴
        # 것**이 수업이다 — 짧은 쪽은 봇이 들어갔다 튕긴 자국이다(구글 경로가
        # 여러 회의 기록 중 가장 오래 이어진 것을 고르는 것과 같은 규칙).
        row = max(rows, key=lambda r: r.get("duration") or 0)
        return Supervision(
            transcript_ref=row.get("id") or "",
            transcript_url=row.get("transcript_url") or "",
            # 마크다운 그대로 둔다 — 업체가 `- ` 불릿과 `**굵게**` 로 주고,
            # 그 구조가 읽는 데 값을 한다. 별표를 여기서 지우면 화면이 되살릴
            # 방법이 없다. 그리는 것은 화면 몫이다(ClinicManagePage).
            # 빈 요약은 None 이되 링크는 남긴다 — 사람이 열어 보면 된다.
            summary=((row.get("summary") or {}).get("overview") or "").strip() or None,
        )

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
