"""Recall 어댑터 — 회의에서 **오디오만** 떠 오고, 전사는 우리가 고른 엔진이 한다.

**왜 이 조합인가.** 조교가 아이패드를 쓰면 구글 자체 전사가 안 켜진다. 그래서
회의에 들어갈 무언가가 필요한데, 한국어를 제일 잘 받아쓰는 엔진(CLOVA)은
**회의에 못 들어간다**(오디오를 주면 전사해 주는 물건이다). 반대로 회의에
들어가는 업체들은 한국어 정확도 근거가 없다. 그래서 둘을 잘라 붙인다 —
Recall 은 **귀**, CLOVA 는 **받아쓰기**.

**Fireflies 대신 이걸 쓰는 이유는 셋이다**(2026-08-13):

  ① **예약 참가**(`join_at`). Fireflies 는 진행 중인 회의에만 봇을 넣을 수 있어
     캘린더를 세우고 업체가 그걸 보길 기다려야 했다. 여기는 배정하는 순간
     "그 시각에 이 링크로 들어가"를 꽂아 두면 끝이라 **우리 쪽에 도는 것이 없다**.
  ② **조직 계정 로그인**. 봇을 `hjcedu.com` 계정으로 로그인시키면 `TRUSTED` 의
     "조직 멤버는 노크 없이" 에 걸려 **조교가 수락할 것이 없어진다**. Fireflies
     봇은 익명 게스트 고정이라 구조적으로 로비를 못 벗어난다.
     자격증명은 **업체 대시보드에 넣는다** — 요청 필드가 아니라서 코드에 없다.
  ③ **오디오 원본**. 전사 엔진을 우리가 고를 수 있다.

**되찾는 열쇠는 `metadata` 다.** 봇을 만들 때 우리 이름(`clinic{번호}`)을 달아
두고 `metadata__clinic=` 로 조회한다. 그래서 "어느 봇이 그 클리닉 것인지"를
적어 둘 컬럼이 필요 없다.
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

TIMEOUT_SECONDS = 30

#: 다시 걸어볼 값어치가 있는 상태 코드(그 밖의 4xx 는 몇 번을 걸어도 같다).
_RETRYABLE_STATUSES = frozenset({408, 429})

#: 봇이 더 갈 데가 없는 상태. `done` 은 정상 종료, `fatal` 은 실패다.
DONE, FATAL = "done", "fatal"


def base_url():
    region = getattr(settings, "RECALL_REGION", "") or "ap-northeast-1"
    return f"https://{region}.recall.ai/api/v1"


class RecallAdapter(ConferenceAdapter):
    """방은 구글에서, 오디오는 Recall 에서, 전사는 주입한 엔진에서."""

    def __init__(self, transport=None, conference=None, transcriber=None):
        self.transport = transport or urllib_transport
        # 화상은 위임한다 — 이 클래스는 방을 만들 줄 모른다.
        self.conference = conference or GoogleMeetAdapter(transport=transport)
        self._transcriber = transcriber

    def create_space(self):
        return self.conference.create_space()

    # -- 예약 -------------------------------------------------------------

    def schedule_supervision(self, url, *, key, title, starts_at, minutes):
        """시작 시각에 들어오도록 봇을 걸어 둔다.

        **업체 전사를 켜지 않는다.** 오디오만 받아서 CLOVA 로 돌린다 — 켜면
        시간당 요금이 더 붙는데 한국어는 더 나쁘다.
        """
        when = starts_at.isoformat() if hasattr(starts_at, "isoformat") else starts_at
        self._call(
            "POST",
            "/bot",
            {
                "meeting_url": url,
                "join_at": when,
                "bot_name": title,
                # 되찾을 이름표. 조회가 `metadata__clinic=` 으로 된다.
                "metadata": {"clinic": key},
                "recording_config": {"audio_mixed": {}},
            },
            "감독 예약을 걸지 못했습니다",
        )

    def cancel_supervision(self, key):
        """걸어 둔 예약을 거둔다. **없으면 조용히 끝난다**(멱등).

        여기서 터지면 학생의 취소가 실패한다 — 예약이 애초에 없던 건이거나
        취소를 두 번 눌렀을 뿐인데.
        """
        found = self._find(key)
        if found is None:
            return
        self._call("DELETE", f"/bot/{found['id']}/", None, "감독 예약을 거두지 못했습니다")

    # -- 수집 -------------------------------------------------------------

    def fetch_supervision(self, ref, *, file_as=None, key=None):
        """끝난 회의의 오디오를 전사해 돌려준다. 아직이면 None(계약).

        `ref`(구글 스페이스)는 쓰지 않는다 — Recall 은 우리가 붙인 이름표만 안다.
        """
        if not key:
            return None
        found = self._find(key)
        if found is None:
            return None
        state = self._state(found)
        if state == FATAL:
            # 다시 물어도 안 생긴다. 대기로 두면 30일 동안 같은 건을 계속 묻는다.
            raise PermanentConferenceError(f"감독 봇이 실패했습니다({found.get('id')}).")
        if state != DONE:
            return None
        audio = self._audio_url(found)
        if not audio:
            return None
        text = self._transcribe(audio, file_as)
        return Supervision(
            transcript_ref=found.get("id") or "",
            transcript_url=audio,
            summary=text,
        )

    def _transcribe(self, audio, file_as):
        transcriber = self._transcriber
        if transcriber is None:
            from .clova import transcribe as transcriber
        return transcriber(audio, terms=())

    # -- 업체 응답 읽기 ----------------------------------------------------

    def _find(self, key):
        """우리 이름표가 달린 봇 하나. 없으면 None."""
        data = self._call(
            "GET", f"/bot?metadata__clinic={key}", None, "감독 예약을 찾지 못했습니다"
        )
        rows = data.get("results") or []
        return rows[0] if rows else None

    def _state(self, found):
        changes = found.get("status_changes") or []
        return changes[-1].get("code") if changes else None

    def _audio_url(self, found):
        shortcut = (found.get("media_shortcuts") or {}).get("audio_mixed") or {}
        return (shortcut.get("data") or {}).get("download_url")

    # -- HTTP -------------------------------------------------------------

    def _call(self, method, path, body, prefix):
        key = getattr(settings, "RECALL_API_KEY", "")
        if not key:
            raise PermanentConferenceError("Recall API 키가 설정되지 않았습니다.")
        status, raw = self.transport(
            method,
            f"{base_url()}{path}",
            json.dumps(body).encode() if body is not None else None,
            {"Authorization": f"Token {key}", "Content-Type": "application/json"},
            TIMEOUT_SECONDS,
        )
        if status >= 300:
            detail = raw.decode(errors="replace")[:200]
            message = f"{prefix}({status}): {detail}"
            if status in _RETRYABLE_STATUSES or status >= 500:
                raise TemporaryConferenceError(message)
            raise PermanentConferenceError(message)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise PermanentConferenceError(f"{prefix}: 응답을 읽을 수 없습니다.") from exc
