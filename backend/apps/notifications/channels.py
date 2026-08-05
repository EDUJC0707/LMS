"""알림 채널 어댑터 계약 — 업체 교체 가능성의 경계선 (PRD 6-8, key_considerations §4).

**여기가 업체가 들어오는 유일한 문이다.** 모델은 `channel` 값과 중립 결과
(status/error_msg)만 알고, "솔라피가 어떤 HTTP 를 어떻게 부르는가"는 이 계약
뒤에 있다. 채널 추가 = `Notification.Channel` 값 추가 + 설정 한 줄이고 스키마는
움직이지 않는다.

**어댑터는 ORM 을 모른다.** 받는 것은 `Message` 하나뿐이다. Notification 인스턴스를
그대로 넘기면 업체 코드가 우리 모델 구조를 붙들게 되고, 그 순간 "구현체만 교체"가
성립하지 않는다(어댑터 테스트에 DB 가 필요해지는 것도 같은 증상이다).

**재시도 여부는 예외 종류가 말한다.** 업체 응답 문자열을 호출측이 파싱해 갈리면
업체마다 규칙이 달라져 재시도 정책이 무너진다. 어댑터가 자기 응답을 해석해
`TemporaryChannelError`(다시 걸어볼 값어치가 있다) / `PermanentChannelError`(몇 번을
걸어도 같다)로 번역하는 것이 어댑터의 일이다.

**기본값은 닫힘이다**(key_considerations §5). `NOTIFICATION_CHANNEL_BACKENDS` 가
비어 있으면 발송은 실패하고 사유가 남는다 — 미설정을 조용한 성공으로 처리하면
운영에서 알림이 통째로 증발하고 발송내역에는 성공만 쌓인다.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.conf import settings
from django.utils.module_loading import import_string


class ChannelError(Exception):
    """채널 발송 실패의 뿌리. 직접 쓰지 말고 아래 둘 중 하나를 고른다."""


class TemporaryChannelError(ChannelError):
    """다시 걸면 될 수 있다 — 타임아웃·5xx·rate limit. 태스크가 재시도한다."""


class PermanentChannelError(ChannelError):
    """몇 번을 걸어도 같다 — 번호 오류·템플릿 미승인·키 없음·채널 미설정."""


@dataclass(frozen=True)
class Message:
    """어댑터가 받는 전부 — 중립 발송 요청.

    `type` 을 싣는 이유: 카카오 알림톡은 사전 승인된 템플릿으로만 나가고, 어느
    템플릿인지는 알림 유형에서 정해진다. 그 매핑은 업체 지식이라 어댑터 안에
    있고(여기가 8-17 이 착지하는 자리), 이 계약은 유형이라는 중립 값만 넘긴다.
    """

    channel: str
    type: str
    recipient: str
    title: str
    body: str


class ChannelAdapter(ABC):
    """채널 하나를 실제로 보내는 구현체. 성공은 무반환, 실패는 예외다."""

    @abstractmethod
    def send(self, message: Message) -> None:
        """보낸다. 실패하면 Temporary/PermanentChannelError 를 던진다."""


class FakeChannelAdapter(ChannelAdapter):
    """실제로 보내지 않고 보관만 하는 어댑터 — 로컬 개발·테스트용.

    **운영 기본값이 아니다.** `dev.py` 가 명시적으로 물릴 때만 쓰인다(위 docstring
    의 닫힘 기본값 참조).
    """

    outbox: list[Message] = []

    def send(self, message: Message) -> None:
        FakeChannelAdapter.outbox.append(message)


def get_adapter(channel: str) -> ChannelAdapter:
    """채널 값 → 어댑터 인스턴스. 미설정·경로 오류는 `PermanentChannelError`.

    캐시하지 않는다 — 어댑터 생성은 값싸고, 캐시를 두면 설정 교체(운영 롤아웃·
    테스트 override)가 조용히 옛 구현체를 계속 쓰는 사고가 난다.
    """
    backends = getattr(settings, "NOTIFICATION_CHANNEL_BACKENDS", {})
    path = backends.get(channel)
    if not path:
        raise PermanentChannelError(f"발송 채널이 설정되지 않았습니다: {channel}")
    try:
        adapter_class = import_string(path)
    except ImportError as exc:
        raise PermanentChannelError(f"발송 채널 구현체를 찾을 수 없습니다: {path}") from exc
    return adapter_class()
