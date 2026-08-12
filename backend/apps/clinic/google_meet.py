"""구글 미트 어댑터 — 업체 지식은 전부 이 파일 안에 있다.

모델도 배정 서비스도 "구글"을 모른다. 업체를 갈아 끼우는 일은 이 파일을 하나 더
쓰고 `CLINIC_CONFERENCE_BACKEND` 를 바꾸는 것이 전부다(스키마 불변 —
`conferencing.py` 계약).

## 왜 서비스 계정이 아니라 갱신 토큰인가

구글 문서: **Meet REST API 는 사용자 인증만 받는다**(service account 는 워크스페이스
도메인 전체 위임을 걸어 사용자를 가장할 때만 성립한다). 우리는 계정 1개로 운영하고
(key_considerations §4 "구글 미트 API 계정 1개") 그 계정이 개인 계정일 수도 있으므로,
**한 번 동의받아 받은 갱신 토큰**을 서버가 들고 매번 액세스 토큰으로 바꿔 쓴다.
동의는 사람이 브라우저에서 한 번 해야 하고, 그 절차는
`manage.py meet_authorize` 가 대신한다.

액세스 토큰을 캐시하지 않는다. 클리닉 배정은 하루에 많아야 수십 건이라 요청
1건당 토큰 요청 1건이 붙어도 비용이 없고, 캐시를 두면 프로세스마다 다른 만료를
들고 도는 문제(gunicorn 워커 다중)를 공짜로 얻는다.

## 스페이스에 거는 두 가지 — 입장 통제와 감독 자료

**`accessType: TRUSTED`** — 링크만 가진 사람은 못 들어오고 노크해야 한다.
조교가 조직 계정으로 먼저 들어가 호스트가 되고 학생을 수락하는 것이 운영
전제다(클리닉은 한 타임 1명뿐이라 계정 1개로 성립 — decisions.md §4).
LMS 가 링크를 시작 5분 전에 그 학생에게만 내리는 것(booking.request_block)과
합쳐 이중 통제가 된다(PRD 6-3 '입장 통제'). `OPEN` 이면 링크가 새는 순간
아무나 1:1 과외 자리에 앉는다.

**`artifactConfig`: 전사 ON · Gemini 요약 ON · 녹화 OFF** — PRD 8-5 확정
(2026-07-17). 미트에는 오디오 전용 녹음이 없어서 전사와 AI 요약이 조교 감독
자료를 대신한다(`ClinicEvaluation.transcript_ref`·`ai_summary` 가 받을 자리).
전사와 요약은 **문서 한 개**에 함께 담긴다(실측: 둘의 document ID 가 같다).
**스페이스를 만들 때 걸어 둔다** — 조교가 회의 중에 버튼을 누르는 것에 기대면
안 눌린 회차가 반드시 나오고, 그 회차는 평가할 근거가 통째로 없다.

**"자동"에 갈래가 셋이라 헷갈리기 쉽다**(2026-08-04 재조사, PRD 8-5):
전사 기능 자체와 **회의별 사전 설정(우리가 쓰는 것)** 은 Business Standard 에서
지원되고, **관리자 콘솔의 조직 전체 자동 설정**만 Business Plus 이상이다.
현 테넌트 `hjcedu.com` 은 Standard 이고 API 는 200 + 되읽기 `ON` 으로 받는다.

발동 조건은 "**전사 권한이 있는 사람이 회의에 입장할 때**"다. 그래서 조교가
**웹 브라우저로, 호스트 계정으로** 들어가야 한다 — 모바일 앱 입장으로는 자동
전사가 시작되지 않는다. 실제 회의로 확인한 적은 아직 없다(미결 8-20).

전사는 회의 종료 후 **30일만** API 로 조회된다(`conferenceRecords.transcripts`).
수집 배치는 아직 없다 — 그때까지는 주최자 드라이브에 남는 문서가 원본이다.

## HTTP 는 표준 라이브러리로 한다

요청이 둘(토큰·스페이스)뿐이고 둘 다 단순 POST 라 의존성을 하나 더 들일 값어치가
없다. 대신 전송을 주입할 수 있게 열어 두어(`transport`) 테스트가 실제 구글을
부르지 않는다.
"""
import datetime
import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

from .conferencing import (
    Conference,
    ConferenceAdapter,
    ConferenceError,
    PermanentConferenceError,
    Supervision,
    TemporaryConferenceError,
)


def _bare(resource_name):
    """`conferenceRecords/abc` → `abc`. 구글이 이름에 컬렉션을 붙여 준다."""
    return resource_name.rsplit("/", 1)[-1]

#: OAuth2 동의 화면 — 사람이 브라우저에서 한 번 들르는 곳(`meet_authorize`).
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"

#: OAuth2 토큰 교환(갱신 토큰 → 액세스 토큰, 인가 코드 → 갱신 토큰).
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

#: 스페이스 생성. 본문은 비어도 되지만 우리는 설정을 실어 보낸다(위 머리말).
SPACES_ENDPOINT = "https://meet.googleapis.com/v2/spaces"

#: 새 스페이스에 거는 설정 — 왜 이 값들인지는 머리말 참조. 바꾸려면 PRD 6-3·8-5
#: 를 먼저 보고 바꿔라(둘 다 여기로 착지하는 결정이다).
SPACE_CONFIG = {
    "accessType": "TRUSTED",
    "artifactConfig": {
        "recordingConfig": {"autoRecordingGeneration": "OFF"},
        # ~~ON~~ → **OFF**(2026-08-12 전면 교체). 감독 자료는 Fireflies 봇이
        # 만든다. 구글까지 켜 두면 안 쓰는 회의록이 클리닉마다 드라이브에
        # 쌓이고, 학생에게 녹취 안내가 두 번 뜬다. 되살리려면 이 두 줄이다 —
        # 어댑터 토글(`CLINIC_CONFERENCE_BACKEND`)과는 별개 스위치다.
        "transcriptionConfig": {"autoTranscriptionGeneration": "OFF"},
        "smartNotesConfig": {"autoSmartNotesGeneration": "OFF"},
    },
}

#: 동의받는 권한 전부. 하나라도 빠지면 그 기능이 조용히 403 이 되므로 여기가
#: 유일한 목록이고 동의 화면도 이 값을 그대로 쓴다.
#:
#: **`drive` 는 넓다** — 그 계정 드라이브 전부를 읽고 쓴다. 좁히려고 두 번
#: 시도했고 두 번 다 막혔다(2026-08-04 실측):
#:   - `drive.meet.readonly` → 파일 존재·이름은 보이는데 본문이 404
#:   - `drive.readonly`      → 본문은 읽히지만 파일을 옮기고 이름을 바꿀 수 없다
#: 구글에 "미트가 만든 파일만 읽고 쓰기" 라는 권한은 없다(2026-08-04 사용자 결정).
#: 그래서 이 계정 드라이브에 **클리닉 감독 자료 말고 다른 것을 두지 않는 것**이
#: 실질적인 방어선이다 — 권한으로는 더 좁힐 수 없다.
SCOPES = (
    "https://www.googleapis.com/auth/meetings.space.created",
    "https://www.googleapis.com/auth/drive",
    # 감독 봇을 일정에 걸어 두기 위해서다(2026-08-12). 봇을 우리가 시작 시각에
    # 밀어 넣는 대신 캘린더에 클리닉을 올려 두면 업체가 알아서 들어온다.
    # `calendar` 가 아니라 `calendar.events` — 일정 하나를 만들고 고치고 지울 뿐
    # 달력 자체를 만들거나 남의 달력 설정을 건드릴 일이 없다.
    "https://www.googleapis.com/auth/calendar.events",
)

#: 끝난 회의 조회. 스페이스 하나에 회의가 여러 번 열릴 수 있다(모두 나갔다가
#: 다시 들어오면 새 기록이 생긴다) — 그래서 목록이고, 우리는 **가장 긴 것**을 쓴다.
CONFERENCE_RECORDS_ENDPOINT = "https://meet.googleapis.com/v2/conferenceRecords"

#: 드라이브 — 문서 본문 내려받기와 정리(이동·개명).
DRIVE_FILES_ENDPOINT = "https://www.googleapis.com/drive/v3/files"

#: 캘린더 — 감독 봇이 **시작 시각을 아는 유일한 경로**다. 봇은 붙어 있는 캘린더를
#: 보고 알아서 들어오므로, 클리닉을 여기 올려 두는 것이 곧 예약이다.
#: `primary` = 토큰 주인(`hjcedu@hjcedu.com`)의 기본 캘린더.
CALENDAR_EVENTS_ENDPOINT = (
    "https://www.googleapis.com/calendar/v3/calendars/primary/events"
)

#: 토큰 주인이 누구인지 묻는 자리. 참석자 명단에 넣어야 해서 필요한데, 설정에
#: 또 적으면 토큰과 이메일이 갈릴 수 있다.
#: **캘린더가 아니라 드라이브에 묻는다** — `calendar.events` 로는 캘린더 정보를
#: 못 읽어 403 이고(2026-08-12 실측), 스코프를 하나 더 받으면 재동의가 또 필요하다.
#: `drive` 는 이미 갖고 있다.
DRIVE_ABOUT_ENDPOINT = "https://www.googleapis.com/drive/v3/about?fields=user"

#: 관리자가 배정 버튼을 누른 채 기다리는 시간 — 동기 호출이라 짧게 잡는다.
TIMEOUT_SECONDS = 10

#: 다시 걸어볼 값어치가 있는 상태 코드(그 외 4xx 는 영구).
_RETRYABLE_STATUSES = frozenset({408, 429})


def urllib_transport(method, url, body, headers, timeout):
    """기본 전송 — (status, body bytes). 4xx·5xx 도 예외가 아니라 값으로 돌린다.

    해석은 어댑터의 일이라(`conferencing.py` 계약) 전송은 상태 코드를 그대로
    넘기고 판단하지 않는다.
    """
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


class GoogleMeetAdapter(ConferenceAdapter):
    """클리닉 1건마다 새 미팅 스페이스를 만든다."""

    def __init__(self, transport=None):
        self.transport = transport or urllib_transport

    def create_space(self) -> Conference:
        access_token = self._access_token()
        status, body = self._post(
            SPACES_ENDPOINT,
            json.dumps({"config": SPACE_CONFIG}).encode(),
            {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
        if status != 200:
            raise self._translate(status, body, "화상 스페이스를 만들지 못했습니다")
        payload = self._json(body)
        ref = payload.get("name")
        url = payload.get("meetingUri")
        if not ref or not url:
            # 200 인데 쓸 값이 없다 = 계약 위반. 빈 링크를 저장하면 학생에게
            # 빈 안내가 나간다(조용한 성공 금지 — key_considerations §5).
            raise PermanentConferenceError(
                "화상 응답에 스페이스 이름 또는 참가 링크가 없습니다."
            )
        return Conference(
            provider="google_meet",
            ref=ref,
            url=url,
        )

    # -- 캘린더(감독 예약) --------------------------------------------------

    def upsert_event(self, key, *, title, url, starts_at, minutes):
        """클리닉 일정을 세우거나 덮어쓴다. `key` 가 곧 일정 ID 다.

        **ID 를 우리가 정하는 이유**: 시간이 바뀌었을 때 새 일정을 하나 더
        만들면 봇이 옛 시각에도 들어간다. 클리닉에서 뽑은 이름을 쓰면 덮어쓰기가
        되고, 어느 일정이 그 클리닉 것인지 적어 둘 컬럼도 필요 없다.

        **링크는 글자로 싣는다.** 구글은 캘린더가 `createRequest` 로 **새로
        만든** 미트만 정식 회의 필드(`conferenceData`)에 넣어 주고, 우리처럼
        이미 있는 스페이스 링크는 거기 못 넣는다. 그래서 `location` 과
        `description` 양쪽에 적는다 — 회의록 봇들이 보는 자리가 그 둘이다.
        """
        end = None
        if starts_at is not None and hasattr(starts_at, "isoformat"):
            end = (starts_at + datetime.timedelta(minutes=minutes)).isoformat()
            starts_at = starts_at.isoformat()
        token = self._access_token()
        event = {
            "id": key,
            # **참석자를 비워 두면 안 된다.** 회의록 봇의 참석 규칙은 참석자
            # 도메인을 보고 "내부 회의"를 판정하는데, 비어 있으면 볼 것이 없어
            # 규칙이 걸리지 않는다. 학생은 구글 계정이 아니라(LMS 계정이다)
            # 외부 게스트로 들어오므로 여기 넣을 수 없고, 조직 계정 하나로 족하다.
            "attendees": [{"email": self._account_email(token)}],
            # 일정 제목이 그대로 전사 제목이 된다(되찾는 열쇠).
            "summary": title,
            "location": url,
            "description": url,
            "start": {"dateTime": starts_at},
            "end": {"dateTime": end or starts_at},
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        # **만들기는 POST 다.** PUT 은 이미 있는 일정만 고치고 없으면 404 라,
        # PUT 부터 걸면 새 클리닉의 예약이 통째로 안 걸린다(2026-08-12 실측 —
        # 배정은 성공했는데 캘린더가 비어 있었다).
        status, body = self._send(
            "POST",
            f"{CALENDAR_EVENTS_ENDPOINT}?sendUpdates=none",
            json.dumps(event).encode(),
            headers,
        )
        if status == 409:
            # 이미 있다 = 같은 클리닉의 예약이다(ID 를 우리가 정하므로).
            # 시간이 바뀐 경우라 덮어쓴다 — 하나 더 만들면 봇이 두 번 간다.
            status, body = self._send(
                "PUT",
                f"{CALENDAR_EVENTS_ENDPOINT}/{key}?sendUpdates=none",
                json.dumps(event).encode(),
                headers,
            )
        if status >= 300:
            raise self._translate(status, body, "감독 일정을 걸지 못했습니다")

    def _account_email(self, token):
        """토큰 주인의 이메일.

        설정에 따로 적지 않는다 — 토큰을 다른 계정으로 재발급했는데 이메일만
        옛 값으로 남으면 참석자가 엉뚱한 사람이 되고, 그건 조용히 틀린다.
        """
        if getattr(self, "_email", None):
            return self._email
        status, body = self._send(
            "GET",
            DRIVE_ABOUT_ENDPOINT,
            None,
            {"Authorization": f"Bearer {token}"},
        )
        if status != 200:
            raise self._translate(status, body, "계정을 확인하지 못했습니다")
        self._email = (self._json(body).get("user") or {}).get("emailAddress")
        return self._email

    def delete_event(self, key):
        """걸어 둔 일정을 거둔다. **없으면 성공으로 본다**(멱등).

        취소를 두 번 눌러도, 애초에 예약이 없던 건이어도 조용히 끝나야 한다 —
        404 를 실패로 다루면 취소가 실패하고 학생은 취소되지 않은 화면을 본다.
        """
        token = self._access_token()
        status, body = self._send(
            "DELETE",
            f"{CALENDAR_EVENTS_ENDPOINT}/{key}?sendUpdates=none",
            None,
            {"Authorization": f"Bearer {token}"},
        )
        if status in (200, 204, 404, 410):
            return
        raise self._translate(status, body, "감독 일정을 거두지 못했습니다")

    # -- 감독 자료 수집 ----------------------------------------------------

    def fetch_supervision(self, ref, *, file_as=None):
        """끝난 회의의 요약·문서 링크. 아직 없으면 None(`conferencing` 계약).

        스페이스 하나에 회의 기록이 여러 개일 수 있다 — 모두 나갔다가 다시
        들어오면 새 기록이 열린다. **가장 오래 이어진 것**을 그 클리닉으로 본다:
        조교 인터넷이 끊겨 3초짜리 기록이 하나 생겼다고 그것이 수업일 수는 없다.
        """
        token = self._access_token()
        record = self._longest_record(token, ref)
        if record is None:
            return None
        document, url = self._artifact_document(token, record)
        if document is None:
            return None
        if file_as:
            self._file_meeting(token, document, file_as)
        return Supervision(
            transcript_ref=document,
            transcript_url=url,
            summary=split_summary(self._export_text(token, document)),
        )

    def _longest_record(self, token, space_ref):
        """그 스페이스의 **끝난** 회의 기록 중 가장 긴 것. 없으면 None."""
        query = urllib.parse.urlencode({"filter": f'space.name="{space_ref}"'})
        status, body = self._get(f"{CONFERENCE_RECORDS_ENDPOINT}?{query}", token)
        if status != 200:
            raise self._translate(status, body, "회의 기록을 읽지 못했습니다")
        records = [r for r in self._json(body).get("conferenceRecords", []) if r.get("endTime")]
        if not records:
            return None  # 아무도 안 들어왔거나 아직 회의 중이다
        return max(records, key=lambda r: (r["endTime"], r.get("startTime", "")))

    def _artifact_document(self, token, record):
        """감독 문서의 (id, 링크). 전사와 요약이 같은 문서를 가리킨다(실측).

        요약(smartNotes)을 먼저 본다 — 우리가 쓰는 것이 요약이라서다. 요약이
        없으면 전사 쪽 문서라도 잡는다(둘 다 없으면 아직 안 만들어진 것).
        """
        for kind in ("smartNotes", "transcripts"):
            status, body = self._get(f"{CONFERENCE_RECORDS_ENDPOINT}/{_bare(record['name'])}"
                                     f"/{kind}", token)
            if status != 200:
                continue
            for item in self._json(body).get(kind, []):
                destination = item.get("docsDestination") or {}
                if destination.get("document"):
                    return destination["document"], destination.get("exportUri") or (
                        f"https://docs.google.com/document/d/{destination['document']}/edit"
                    )
        return None, None

    def _export_text(self, token, document):
        """문서를 평문으로 내려받는다. 못 읽으면 빈 문자열 — 링크는 남는다."""
        query = urllib.parse.urlencode({"mimeType": "text/plain"})
        status, body = self._get(f"{DRIVE_FILES_ENDPOINT}/{document}/export?{query}", token)
        return body.decode(errors="replace") if status == 200 else ""

    #: 구글이 회의 산출물을 모아 두는 최상위 폴더. **절대 이름을 바꾸지 않는다** —
    #: 이걸 건드리면 앞으로 만들어지는 모든 회의 산출물이 엉뚱한 데로 들어간다.
    GOOGLE_ROOT_FOLDER = "Google Meet"

    def _file_meeting(self, token, document, file_as):
        """그 회의 폴더를 통째로 우리 구조로 옮기고 이름을 바꾼다.

        **문서가 아니라 폴더를 옮기는 이유**: 구글은 회의마다 폴더를 만들고 그
        안에 산출물을 넣는다. 문서만 꺼내면 빈 폴더가 회의 수만큼 쌓이고, 나중에
        녹화나 출석 리포트를 켜면 그것들은 따라오지 않아 코드를 또 고쳐야 한다.
        폴더째 옮기면 구글이 무엇을 더 넣든 같이 온다.

        **실패해도 수집은 계속된다.** 정리는 편의고 요약·링크가 본론이라,
        폴더를 못 옮겼다고 감독 자료를 버릴 이유가 없다.
        """
        try:
            folder, current_parent = self._meeting_folder(token, document)
            if folder is None:
                return
            *ancestors, name = file_as.split("/")
            destination = None
            for ancestor in ancestors:
                destination = self._folder(token, ancestor, destination)
            query = {"addParents": destination} if destination else {}
            if current_parent:
                query["removeParents"] = current_parent
            self._send(
                "PATCH",
                f"{DRIVE_FILES_ENDPOINT}/{folder}?{urllib.parse.urlencode(query)}",
                json.dumps({"name": name}).encode(),
                {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
        except ConferenceError:
            return

    def _meeting_folder(self, token, document):
        """문서가 든 회의 폴더의 (id, 그 폴더의 부모). 옮기면 안 되는 자리면 (None, None).

        문서가 회의 폴더가 아니라 `Google Meet` 바로 아래 놓여 있으면 손대지
        않는다 — 그건 구글의 공용 폴더라 이름을 바꾸면 이후 회의가 전부 휩쓸린다.
        """
        status, body = self._get(f"{DRIVE_FILES_ENDPOINT}/{document}?fields=parents", token)
        if status != 200:
            return None, None
        parents = self._json(body).get("parents") or []
        if not parents:
            return None, None
        folder = parents[0]
        query = urllib.parse.urlencode({"fields": "name,parents"})
        status, body = self._get(f"{DRIVE_FILES_ENDPOINT}/{folder}?{query}", token)
        if status != 200:
            return None, None
        info = self._json(body)
        if info.get("name") == self.GOOGLE_ROOT_FOLDER:
            return None, None
        grandparents = info.get("parents") or []
        return folder, (grandparents[0] if grandparents else None)

    def _folder(self, token, name, parent):
        """이름으로 폴더를 찾고 없으면 만든다 — 있는 폴더를 또 만들지 않는다."""
        clauses = [
            f"name = '{name}'",
            "mimeType = 'application/vnd.google-apps.folder'",
            "trashed = false",
            f"'{parent}' in parents" if parent else "'root' in parents",
        ]
        query = urllib.parse.urlencode({"q": " and ".join(clauses), "fields": "files(id)"})
        status, body = self._get(f"{DRIVE_FILES_ENDPOINT}?{query}", token)
        if status == 200:
            found = self._json(body).get("files", [])
            if found:
                return found[0]["id"]
        payload = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent:
            payload["parents"] = [parent]
        status, body = self._post(
            DRIVE_FILES_ENDPOINT,
            json.dumps(payload).encode(),
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        if status != 200:
            raise self._translate(status, body, "폴더를 만들지 못했습니다")
        return self._json(body)["id"]

    # -- OAuth -------------------------------------------------------------

    def _access_token(self):
        client_id = (getattr(settings, "GOOGLE_MEET_CLIENT_ID", "") or "").strip()
        client_secret = (getattr(settings, "GOOGLE_MEET_CLIENT_SECRET", "") or "").strip()
        refresh_token = (getattr(settings, "GOOGLE_MEET_REFRESH_TOKEN", "") or "").strip()
        if not (client_id and client_secret and refresh_token):
            raise PermanentConferenceError(
                "구글 미트 자격증명이 설정되지 않았습니다"
                "(GOOGLE_MEET_CLIENT_ID·CLIENT_SECRET·REFRESH_TOKEN)."
            )
        status, body = self._post(
            TOKEN_ENDPOINT,
            urllib.parse.urlencode(
                {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                }
            ).encode(),
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        if status != 200:
            # invalid_grant = 갱신 토큰이 철회·만료됐다. 사람이 다시 동의해야
            # 하므로 재시도로는 절대 풀리지 않는다(meet_authorize 재실행).
            raise self._translate(status, body, "구글 액세스 토큰을 받지 못했습니다")
        token = self._json(body).get("access_token")
        if not token:
            raise PermanentConferenceError("구글 토큰 응답에 access_token 이 없습니다.")
        return token

    # -- 공통 --------------------------------------------------------------

    def _post(self, url, body, headers):
        return self._send("POST", url, body, headers)

    def _get(self, url, token):
        """토큰만 붙는 조회. 감독 자료 수집이 전부 이 경로를 쓴다."""
        return self._send("GET", url, None, {"Authorization": f"Bearer {token}"})

    def _send(self, method, url, body, headers):
        try:
            return self.transport(method, url, body, headers, TIMEOUT_SECONDS)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise TemporaryConferenceError(f"구글에 닿지 못했습니다: {error}") from error

    def _json(self, body):
        try:
            payload = json.loads(body.decode())
        except (ValueError, UnicodeDecodeError) as error:
            raise PermanentConferenceError(f"구글 응답을 읽을 수 없습니다: {error}") from error
        if not isinstance(payload, dict):
            raise PermanentConferenceError("구글 응답 형식이 올바르지 않습니다.")
        return payload

    def _translate(self, status, body, prefix):
        """상태 코드 → 예외 종류. 재시도 정책이 갈리는 유일한 지점이다."""
        detail = body.decode(errors="replace")[:200]
        message = f"{prefix}({status}): {detail}"
        if status in _RETRYABLE_STATUSES or status >= 500:
            return TemporaryConferenceError(message)
        return PermanentConferenceError(message)


# --- 감독 문서에서 요약만 잘라내기 ----------------------------------------

#: 전사가 시작되는 자리. 구글이 요약과 전사를 **문서 하나**에 담기 때문에
#: 여기서 잘라야 학생 발화가 우리 DB 로 넘어오지 않는다(2026-08-04 실측).
#: 한국어 제목(`스크립트`)이 아니라 **이모지**로 찾는 이유 — 계정 언어가 바뀌면
#: 제목은 `Transcript` 가 되지만 이모지는 그대로다.
TRANSCRIPT_MARKER = "📖"

#: 요약 끝에 붙는 구글 안내문. 감독 기록에 설문조사 안내가 남을 이유가 없다.
#: 문구가 바뀌면 걸러지지 않을 뿐 **자르는 위치와는 무관하다** — 여기서 틀려도
#: 전사가 새지는 않는다.
_BOILERPLATE_HINTS = ("Gemini가 작성한 회의록이 정확한지", "설문조사", "도움말을 알아보세요")


def split_summary(document_text):
    """감독 문서 본문 → **요약 부분만**. 잘라낼 자리가 없으면 None.

    표식을 못 찾으면 통째로 돌려주지 않고 None 이다. 통째로 넣는 쪽이 편하지만
    그 순간 전사 원문(학생 발화)이 DB 에 들어간다 — 형식이 바뀌었을 때 조용히
    개인정보를 쌓느니 요약이 비어 있는 편이 낫다(닫힘이 안전 기본값 — §5).
    """
    if not document_text or TRANSCRIPT_MARKER not in document_text:
        return None
    notes = document_text.split(TRANSCRIPT_MARKER, 1)[0]
    kept = [
        line
        for line in notes.splitlines()
        if not any(hint in line for hint in _BOILERPLATE_HINTS)
    ]
    summary = "\n".join(kept).strip().lstrip("﻿").strip()
    return summary or None


# --- 1회성 동의(갱신 토큰 발급) -------------------------------------------
# 여기부터는 운영 중에 돌지 않는다. `manage.py meet_authorize` 가 한 번 부르고,
# 그 결과(갱신 토큰)를 사람이 시크릿에 넣으면 끝이다. 그래도 이 파일에 두는
# 이유는 구글 지식이 두 파일로 갈리지 않게 하기 위해서다(머리말 계약).


def build_consent_url(client_id, redirect_uri):
    """동의 화면 URL. 사람이 이 주소를 열어 계정을 고르고 승인한다.

    `access_type=offline` 이 없으면 갱신 토큰이 아예 오지 않고, `prompt=consent`
    가 없으면 **이미 동의한 계정에서는 두 번째부터** 오지 않는다 — 둘 다 빠뜨리기
    쉬운 자리라 값으로 못 박는다.
    """
    return f"{AUTH_ENDPOINT}?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }
    )


def exchange_code(client_id, client_secret, code, redirect_uri, transport=None):
    """인가 코드 → **갱신 토큰**. 액세스 토큰은 버린다(수명이 한 시간이라 쓸모없다)."""
    post = transport or urllib_transport
    try:
        status, body = post(
            "POST",
            TOKEN_ENDPOINT,
            urllib.parse.urlencode(
                {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                }
            ).encode(),
            {"Content-Type": "application/x-www-form-urlencoded"},
            TIMEOUT_SECONDS,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise TemporaryConferenceError(f"구글에 닿지 못했습니다: {error}") from error
    if status != 200:
        raise PermanentConferenceError(
            f"인가 코드를 토큰으로 바꾸지 못했습니다({status}): "
            f"{body.decode(errors='replace')[:200]}"
        )
    try:
        payload = json.loads(body.decode())
    except (ValueError, UnicodeDecodeError) as error:
        raise PermanentConferenceError(f"구글 응답을 읽을 수 없습니다: {error}") from error
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise PermanentConferenceError(
            "응답에 갱신 토큰이 없습니다 — 이미 동의한 계정입니다. "
            "https://myaccount.google.com/permissions 에서 이 앱의 접근을 지우고 다시 실행하세요."
        )
    return refresh_token
