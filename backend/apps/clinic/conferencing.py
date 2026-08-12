"""화상 어댑터 계약 — 업체 교체 가능성의 경계선 (key_considerations §4 "화상").

**여기가 화상 업체가 들어오는 유일한 문이다.** 모델은 `conference_provider` 값과
중립 참조(`conference_ref`)·참가 URL 만 알고, "구글이 어떤 HTTP 를 어떻게 부르는가"
는 이 계약 뒤에 있다. 업체 교체 = `ClinicRequest.ConferenceProvider` 값 추가 +
설정 한 줄이고 스키마는 움직이지 않는다(notifications `channels.py` 와 같은 축).

**어댑터는 ORM 을 모른다.** `create_space()` 는 인자가 없고 돌려주는 것은
`Conference` 하나뿐이다. ClinicRequest 를 넘기면 업체 코드가 우리 모델 구조를
붙들게 되고, 그 순간 "구현체만 교체"가 성립하지 않는다.

**재시도 여부는 예외 종류가 말한다.** 업체 응답 문자열을 호출측이 파싱해 갈리면
업체마다 규칙이 달라진다. 어댑터가 자기 응답을 해석해
`TemporaryConferenceError`(다시 걸어볼 값어치가 있다) /
`PermanentConferenceError`(몇 번을 걸어도 같다)로 번역하는 것이 어댑터의 일이다.

**기본값은 닫힘이다**(key_considerations §5). `CLINIC_CONFERENCE_BACKEND` 가 비면
스페이스 생성은 실패하고, 배정은 **관리자가 링크를 직접 붙여넣는 수동 경로**로만
성립한다(clinic_admin.assign). 미설정을 조용한 성공으로 처리하면 학생에게 빈
안내가 나간다.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.conf import settings
from django.utils.module_loading import import_string


class ConferenceError(Exception):
    """화상 스페이스 생성 실패의 뿌리. 직접 쓰지 말고 아래 둘 중 하나를 고른다."""


class TemporaryConferenceError(ConferenceError):
    """다시 걸면 될 수 있다 — 타임아웃·5xx·rate limit."""


class PermanentConferenceError(ConferenceError):
    """몇 번을 걸어도 같다 — 자격증명 없음·권한 거부·미설정·응답 계약 위반."""


@dataclass(frozen=True)
class Conference:
    """어댑터가 돌려주는 전부 — 모델의 화상 3열과 같은 모양.

    - provider: `ClinicRequest.ConferenceProvider` 값
    - ref: 업체의 **오래 가는** 식별자(구글은 `spaces/{space}`)
    - url: 학생·조교가 누르는 참가 링크
    """

    provider: str
    ref: str
    url: str


@dataclass(frozen=True)
class Supervision:
    """끝난 회의가 남긴 조교 감독 자료 — `ClinicEvaluation` 이 받을 값.

    - transcript_ref/transcript_url: 감독 문서(업체 저장소에 남는 원본)
    - summary: 요약 **본문**. 업체가 요약을 안 주거나 잘라낼 자리를 못 찾으면
      None 이고, 그래도 링크는 남긴다 — 사람이 열어 보면 되기 때문이다.

    **전사 원문은 여기 없다.** 학생 발화를 우리 DB 로 들이지 않는 것이 계약이고
    (PRD 8-1), 그 판단이 어댑터 안에서 이미 끝나 있어야 한다.
    """

    transcript_ref: str
    transcript_url: str
    summary: str | None


class ConferenceAdapter(ABC):
    """화상 스페이스를 실제로 만들고, 끝난 뒤 감독 자료를 거둬 오는 구현체."""

    @abstractmethod
    def create_space(self) -> Conference:
        """새 스페이스 1개. 실패하면 Temporary/PermanentConferenceError 를 던진다."""

    def start_supervision(self, url: str, *, title: str, minutes: int) -> None:
        """감독 기록을 시작시킨다. **기본은 아무것도 하지 않는 것이다.**

        구글은 스페이스를 만들 때 "전사를 켜라"를 실어 보내므로 회의가 시작되면
        저절로 돈다 — 부를 것이 없다. 봇을 회의에 넣어야 하는 업체만 이걸
        구현한다(Fireflies). 그래서 `@abstractmethod` 가 아니다: 필요 없는
        구현체까지 빈 메서드를 쓰게 만들면 계약이 거짓말을 하게 된다.

        `title` 은 나중에 `fetch_supervision(file_as=...)` 이 되찾을 **같은
        문자열**이다. 저장소가 제목을 모르는 업체면 무시해도 된다.
        """
        return None

    @abstractmethod
    def fetch_supervision(self, ref: str, *, file_as: str | None = None) -> "Supervision | None":
        """끝난 회의의 감독 자료. **아직 없으면 None**(실패가 아니다).

        None 이 나오는 경우가 여럿이고 전부 정상이다 — 아무도 안 들어왔거나,
        회의가 방금 끝나 자료가 아직 안 만들어졌거나, 전사가 애초에 돌지
        않았거나(호스트가 웹이 아닌 기기로 들어온 경우). 호출측은 그냥 다음
        차례에 다시 물어본다.

        `file_as` 는 **정리해 두고 싶은 논리 경로**다(`clinic/2026-08/…`).
        저장소가 폴더를 모르는 업체면 무시해도 된다 — 계약은 "가능하면 여기
        두라"이지 "반드시 옮겨라"가 아니다.
        """


def get_adapter() -> ConferenceAdapter:
    """설정된 어댑터 인스턴스. 미설정·경로 오류는 `PermanentConferenceError`.

    캐시하지 않는다 — 생성은 값싸고, 캐시를 두면 설정 교체(운영 롤아웃·테스트
    override)가 조용히 옛 구현체를 계속 쓰는 사고가 난다(channels 선례).
    """
    path = getattr(settings, "CLINIC_CONFERENCE_BACKEND", "")
    if not path:
        raise PermanentConferenceError("화상 제공자가 설정되지 않았습니다.")
    try:
        adapter_class = import_string(path)
    except ImportError as exc:
        raise PermanentConferenceError(f"화상 제공자 구현체를 찾을 수 없습니다: {path}") from exc
    return adapter_class()
