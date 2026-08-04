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


class ConferenceAdapter(ABC):
    """화상 스페이스를 실제로 만드는 구현체."""

    @abstractmethod
    def create_space(self) -> Conference:
        """새 스페이스 1개. 실패하면 Temporary/PermanentConferenceError 를 던진다."""


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
