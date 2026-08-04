"""솔라피 채널 어댑터 — 업체 지식은 전부 이 파일 안에 있다.

모델도 발송 태스크도 "솔라피"를 모른다. 업체를 갈아 끼우는 일은 이 파일을 하나 더
쓰고 `NOTIFICATION_CHANNEL_BACKENDS` 의 값을 바꾸는 것이 전부다(스키마 불변 —
`channels.py` 계약 참조).

**아직 실제로 보내지 못한다.** 솔라피 API 키가 없어서다. 키가 없는 동안에도
확정할 수 있는 것은 여기서 다 한다 — 설정 누락 판정, 채널→메시지 유형 매핑,
알림톡 템플릿 코드 해석, 페이로드 조립. **막힌 것은 `_request` 하나**이고,
키가 오면 고칠 곳도 거기 하나다.

**8-17 이 착지하는 자리**: 카카오 알림톡은 사전 승인된 템플릿으로만 나간다.
알림 유형 → 승인된 템플릿 코드 매핑이 `NOTIFICATION_KAKAO_TEMPLATE_CODES` 이고,
발송 시점 목록이 확정돼 템플릿을 승인받으면 그 dict 에 줄을 추가하는 것이 전부다.
비어 있는 동안 알림톡 발송은 "템플릿 코드가 없습니다(성적)" 로 실패한다 —
조용히 성공하는 것보다 낫다(안전 기본값은 닫힘, key_considerations §5).

**키가 오면 확인할 것**: `_request` 의 엔드포인트·HMAC 서명 헤더, 그리고
`_build_message` 의 필드명이 솔라피 현행 문서와 맞는지. 페이로드 구조는 공개
문서 기준으로 조립해 뒀지만 실제 응답으로 검증한 적은 없다.
"""
from django.conf import settings

from .channels import ChannelAdapter, Message, PermanentChannelError

#: 솔라피 발송 API. `_request` 를 구현할 때 쓴다.
SEND_ENDPOINT = "https://api.solapi.com/messages/v4/send"

#: 채널 값 → 솔라피 메시지 유형. 문자는 길이로 SMS/LMS 가 갈린다(아래 참조).
KAKAO_MESSAGE_TYPE = "ATA"

#: SMS 한 건의 한도. 초과분은 LMS 로 나가야 하고, 그대로 보내면 잘리거나 거절된다.
SMS_BYTE_LIMIT = 90


class SolapiAdapter(ChannelAdapter):
    """카카오 알림톡·문자를 솔라피로 내보낸다."""

    def send(self, message: Message) -> None:
        self._request(self._build_payload(message))

    # -- 조립 -------------------------------------------------------------

    def _build_payload(self, message: Message) -> dict:
        api_key = getattr(settings, "SOLAPI_API_KEY", "")
        api_secret = getattr(settings, "SOLAPI_API_SECRET", "")
        if not api_key or not api_secret:
            raise PermanentChannelError("솔라피 API 키가 설정되지 않았습니다.")
        sender = getattr(settings, "SOLAPI_SENDER_PHONE", "")
        if not sender:
            raise PermanentChannelError("솔라피 발신번호가 설정되지 않았습니다.")

        if message.channel == "카카오알림톡":
            return {"message": self._kakao_message(message, sender)}
        if message.channel == "문자":
            return {"message": self._sms_message(message, sender)}
        raise PermanentChannelError(f"솔라피가 보낼 수 없는 채널입니다: {message.channel}")

    def _kakao_message(self, message: Message, sender: str) -> dict:
        pf_id = getattr(settings, "SOLAPI_KAKAO_PFID", "")
        if not pf_id:
            raise PermanentChannelError("카카오 채널 ID(pfId)가 설정되지 않았습니다.")
        template_id = getattr(settings, "NOTIFICATION_KAKAO_TEMPLATE_CODES", {}).get(message.type)
        if not template_id:
            # 8-17 대기 중. 승인 전에는 몇 번을 걸어도 나가지 않으므로 영구 실패다.
            raise PermanentChannelError(f"승인된 알림톡 템플릿 코드가 없습니다: {message.type}")
        return {
            "to": message.recipient,
            "from": sender,
            "text": message.body,
            "type": KAKAO_MESSAGE_TYPE,
            "kakaoOptions": {"pfId": pf_id, "templateId": template_id},
        }

    def _sms_message(self, message: Message, sender: str) -> dict:
        payload = {
            "to": message.recipient,
            "from": sender,
            "text": message.body,
            "type": "SMS" if _fits_in_sms(message.body) else "LMS",
        }
        if payload["type"] == "LMS" and message.title:
            payload["subject"] = message.title
        return payload

    # -- HTTP (유일한 미구현 지점) -----------------------------------------

    def _request(self, payload: dict) -> None:
        """솔라피에 발송 요청을 보낸다. **키가 없어 아직 구현되지 않았다.**

        구현할 때 필요한 것:
        - `SEND_ENDPOINT` 로 POST, 본문은 위에서 조립한 `payload`
        - `Authorization: HMAC-SHA256 apiKey=…, date=…, salt=…, signature=…`
          (서명은 `SOLAPI_API_SECRET` 으로 date+salt 를 HMAC-SHA256)
        - HTTP 클라이언트 의존성이 아직 없다 — `requests` 를 pyproject 에 추가한다
        - 응답 해석: 타임아웃·5xx·rate limit → `TemporaryChannelError`,
          그 외 4xx(번호 오류·템플릿 거절 등) → `PermanentChannelError`.
          이 번역이 어댑터의 마지막 일이다. 호출측은 예외 종류만 보고 재시도를
          결정한다(`channels.py` 계약).
        """
        raise PermanentChannelError(
            "솔라피 HTTP 연동이 아직 없습니다 — API 키 수령 후 SolapiAdapter._request 를 구현한다."
        )


def _fits_in_sms(text: str) -> bool:
    """EUC-KR 90바이트 이내면 SMS. 한글은 2바이트라 45자가 경계다."""
    return len(text.encode("euc-kr", errors="replace")) <= SMS_BYTE_LIMIT
