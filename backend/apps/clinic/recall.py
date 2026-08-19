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
  ② **봇 퇴장**. Fireflies 는 봇을 빼는 수단이 아예 없어 조교가 나가도 빈 방에
     앉아 `duration` 을 채웠고 그동안 전사가 안 나왔다. 여기는 사람이 다 나가면
     봇도 따라 나간다.
  ③ **오디오 원본**. 전사 엔진을 우리가 고를 수 있다.

**로비는 봇이 아니라 스페이스 쪽에서 없앴다.** Recall 에 signed-in 봇(조직 계정
으로 로그인해 노크를 건너뛰는 방식)이 있지만, 그건 **새 워크스페이스를 따로
파고 조직 전체 SSO 를 갈아 끼우는** 설정이라 노크 하나를 없애자고 치르기엔
과하다(2026-08-13 검토). 대신 `accessType` 을 `OPEN` 으로 돌려 **아무도 노크하지
않게** 했다 — 봇도 학생도. 그래서 익명 봇으로 충분하고 코드에 자격증명이 없다.

**되찾는 열쇠는 `metadata` 다.** 봇을 만들 때 우리 이름(`clinic{번호}`)을 달아
두고 `metadata__clinic=` 로 조회한다. 그래서 "어느 봇이 그 클리닉 것인지"를
적어 둘 컬럼이 필요 없다.
"""
import datetime
import json
import re

from django.conf import settings

from .conferencing import (
    ConferenceAdapter,
    ConferenceError,
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

#: 참가자 목록에 뜨는 이름. **되찾기는 `metadata` 가 하므로 여기는 자유다** —
#: 내부 경로를 넣었더니 학생 화면에 자기 원번이 붙은 문자열이 앉아 있었다
#: (2026-08-18 실측). 사람이 읽는 자리라 사람 말로 적는다.
BOT_NAME = "JC 만점봇"

#: 업체 쪽 보관 기간(시간). **5일** — 원본은 회의가 끝나면 우리 드라이브로
#: 옮기므로 저쪽은 옮기기가 몇 번 실패해도 될 여유만 있으면 된다.
#: 무료 구간이 7일이라 5일로 잡아 **경계에 붙지 않게** 한다 — 시간대·정산
#: 기준이 어긋나도 요금이 시작되지 않는다.
RETENTION_HOURS = 24 * 5

#: 시작보다 이만큼 일찍 들어간다. 정각에 맞추면 조교·학생이 먼저 들어와
#: 인사하고 문제를 펴는 동안 봇이 없어서 **그 앞부분이 통째로 안 남는다**.
#: 빈 방에 혼자 기다려도 안전하다 — 업체가 "아무도 안 들어오면 나간다"로 잡아
#: 둔 기본값이 1200초(20분)라 이보다 훨씬 길다. 요금은 초 단위 정산이라
#: 10분 × 월 30건 = 5시간, $2.5 정도가 더 든다.
JOIN_EARLY = datetime.timedelta(minutes=10)


def document(file_as, summary, text):
    """감독 문서 본문(HTML). 요약이 먼저, 전사는 **줄 그대로**.

    표로 감싸지 않는다 — 한 줄이 한 발화라 이미 읽히고, 표는 폭이 좁아져
    긴 발화가 접힌다. 시각·화자 표시는 전사가 이미 달고 있다.
    """
    name = file_as.rsplit("/", 1)[-1]
    body = ["<h2>클리닉 감독 기록</h2>", f"<p>{_safe(name)}</p>", "<h3>요약</h3>"]
    if summary:
        # 업체가 `**굵게**` 로 줄 때가 있는데 문서에서는 군더더기다.
        body += [
            f"<p>{_safe(_plain(part))}</p>"
            for part in summary.splitlines()
            if part.strip()
        ]
    else:
        # 없는 것을 빈칸으로 두면 "아직 안 왔나" 와 구분이 안 된다.
        body.append("<p>요약을 만들지 못했습니다.</p>")
    body.append("<h3>전사</h3>")
    lines = [line for line in (text or "").splitlines() if line.strip()]
    body += [f"<p>{_safe(line)}</p>" for line in lines] or ["<p>발화가 없습니다.</p>"]
    return "<html><body>" + "".join(body) + "</body></html>"


def _plain(text):
    """마크다운 굵게 표시를 벗긴다."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text or "")


def _safe(text):
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _download(url):
    """녹음 원본을 받아 온다. 업체가 주는 서명 URL 은 곧 만료되므로 바로 쓴다."""
    import urllib.request

    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def base_url():
    region = getattr(settings, "RECALL_REGION", "") or "ap-northeast-1"
    return f"https://{region}.recall.ai/api/v1"


class RecallAdapter(ConferenceAdapter):
    """방은 구글에서, 오디오는 Recall 에서, 전사는 주입한 엔진에서."""

    def __init__(
        self,
        transport=None,
        conference=None,
        transcriber=None,
        summariser=None,
        fetcher=None,
    ):
        self.transport = transport or urllib_transport
        # 화상은 위임한다 — 이 클래스는 방을 만들 줄 모르고, 드라이브 보관도
        # 저쪽이 안다(구글 API 지식은 한 곳에 모아 둔다).
        self.conference = conference or GoogleMeetAdapter(transport=transport)
        self._transcriber = transcriber
        self._summariser = summariser
        self._fetcher = fetcher or _download

    def create_space(self):
        return self.conference.create_space()

    # -- 예약 -------------------------------------------------------------

    def schedule_supervision(self, url, *, key, title, starts_at, minutes):
        """시작 시각에 들어오도록 봇을 걸어 둔다.

        **업체 전사를 켜지 않는다.** 오디오만 받아서 CLOVA 로 돌린다 — 켜면
        시간당 요금이 더 붙는데 한국어는 더 나쁘다.
        """
        when = starts_at
        if hasattr(when, "isoformat"):
            when = (when - JOIN_EARLY).isoformat()
        self._call(
            "POST",
            "/bot",
            {
                "meeting_url": url,
                "join_at": when,
                "bot_name": BOT_NAME,
                # 되찾을 이름표. 조회가 `metadata__clinic=` 으로 된다.
                "metadata": {"clinic": key},
                # **키 이름이 틀리면 조용히 무시된다** — `audio_mixed` 로 보냈더니
                # 기본값인 영상으로 녹음돼 있었다(2026-08-18 실측). 영상은 우리가
                # 쓰지 않으므로 명시적으로 끈다(`None` 이 "찍지 마라"다).
                "recording_config": {
                    "audio_mixed_mp3": {},
                    "video_mixed_mp4": None,
                    # 업체 기본값은 **영구 보관**이다. 원본은 우리 드라이브로
                    # 옮기므로 저쪽에 무기한 둘 이유가 없고, 남의 저장소에
                    # 학생 음성이 계속 남는 것도 원하지 않는다.
                    "retention": {"type": "timed", "hours": RETENTION_HOURS},
                },
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
        text = self._transcribe(audio)
        summary = self._summarise(text)
        return Supervision(
            transcript_ref=found.get("id") or "",
            # **업체 주소를 그대로 저장하지 않는다.** 서명된 임시 URL 이라 몇
            # 시간이면 죽고, 업체 보관도 5일이다. 우리 드라이브로 옮긴 문서의
            # 링크를 남긴다 — 그건 안 죽는다.
            transcript_url=self._archive(file_as, text, summary, audio),
            # **DB 에는 요약만.** 학생 발화를 우리 DB 로 들이지 않는 것이
            # 계약이고(PRD 8-1), 원문은 문서 링크로만 닿는다.
            summary=summary,
        )

    def _transcribe(self, audio):
        transcriber = self._transcriber
        if transcriber is None:
            from .clova import transcribe as transcriber
        return transcriber(audio, terms=())

    def _summarise(self, text):
        """감독용 요약. **덤이다** — 실패해도 전사는 이미 남는다.

        요약이 없으면 화면이 "요약을 읽지 못했습니다" 로 말하고 사람이 원문을
        열면 된다. 여기서 터뜨리면 그 회차의 감독 자료가 통째로 사라진다.
        """
        summariser = self._summariser
        if summariser is None:
            from .summary import summarize as summariser
        try:
            return summariser(text)
        except ConferenceError:
            return None

    def _archive(self, file_as, text, summary, audio):
        """전사를 문서로, 녹음을 파일로 우리 드라이브에 남기고 문서 링크를 준다.

        정리할 경로가 없으면(관리자가 손으로 넣은 건 등) 아무것도 안 남기고
        업체 주소를 그대로 돌려준다 — 곧 죽지만 없는 것보다는 낫다.
        """
        if not file_as:
            return audio
        # 사람이 문서를 열었을 때 **요약이 먼저** 보여야 읽는 값어치가 있다.
        # **클리닉 하나에 폴더 하나** — 전사·녹음이 한자리에 모인다.
        link = self.conference.save_document(f"{file_as}/전사", document(file_as, summary, text))
        # 녹음 원본까지 우리 것으로 — **여기는 덤이다.** 전사는 이미 문서로
        # 남았으므로 원본 복사가 실패했다고 수집을 통째로 실패시키지 않는다.
        # 넓게 잡는 이유: 내려받기는 네트워크·만료·디스크 등 업체 예외가 아닌
        # 것으로도 깨지는데, 그 어느 것도 감독 자료를 버릴 사유가 아니다.
        try:
            self.conference.save_bytes(
                f"{file_as}/녹음.mp3", self._fetcher(audio), "audio/mpeg"
            )
        except Exception:  # noqa: BLE001 - 덤이라 무엇이 나든 넘어간다
            pass
        return link

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
        """녹음물 내려받을 주소. 아직 없으면 None.

        **봇 최상위가 아니라 `recordings[]` 안에 있다**(2026-08-18 실측 — 봇에는
        `media_shortcuts` 키 자체가 없다).

        오디오가 없으면 영상으로 물러선다: 설정 키를 틀렸던 기간에 잡힌 회차는
        영상만 있는데, 전사 엔진은 영상에서도 소리를 읽으므로 버릴 이유가 없다.
        """
        for recording in found.get("recordings") or []:
            shortcuts = recording.get("media_shortcuts") or {}
            for kind in ("audio_mixed", "video_mixed"):
                data = (shortcuts.get(kind) or {}).get("data") or {}
                if data.get("download_url"):
                    return data["download_url"]
        return None

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
