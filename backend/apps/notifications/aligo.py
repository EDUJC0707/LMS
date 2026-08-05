"""알리고 채널 어댑터 — 업체 지식은 전부 이 파일 안에 있다.

모델도 발송 태스크도 "알리고"를 모른다. 업체 교체는 이런 파일을 하나 더 쓰고
`NOTIFICATION_CHANNEL_BACKENDS` 값을 바꾸는 것이 전부다(`channels.py` 계약).

**같은 업체인데 문자와 알림톡이 서로 다른 API 다.** 여기가 이 파일의 존재 이유이자
제일 틀리기 쉬운 곳이라 표로 못 박는다:

| | 문자 | 알림톡 |
|---|---|---|
| 호스트 | `apis.aligo.in` | `kakaoapi.aligo.in` |
| 인증 파라미터 | `key` · `user_id` | `apikey` · `userid` |
| 수신자 | `receiver` | `receiver_1` (1~500 인덱스) |
| 결과 필드 | `result_code` | `code` |
| **성공 값** | **1** | **0** |

성공 값을 뒤집어 쓰면 **실제로 나간 알림톡이 전부 실패로 기록된다** — 재발송 배치가
그 행을 다시 집어 학부모에게 두 번 간다. 조용히 틀리는 종류의 버그라 테스트가
양쪽을 따로 검증한다(`test_aligo.py`).

**재시도 분류**: 길이 막힌 것(타임아웃·5xx·JSON 아닌 응답)만 `TemporaryChannelError`
다. 업체가 정상 응답으로 거절한 것(음수 코드)은 다시 걸어도 같으므로 영구 실패다 —
번호 오류·템플릿 미승인·잔액 부족이 여기 들어온다. 잔액 부족처럼 나중에 풀릴 수 있는
것도 영구로 두는 이유는, 어차피 재발송 배치가 24시간 창 안에서 다시 집기 때문이다
(`tasks.retry_failed_notifications`).

**발송 실패는 과금되지 않는다**(알리고 자동 환불 — `docs/2026-08-05-알림발송-비용과-
업체선정.md` §7). 그래서 재시도 상한을 낮출 이유가 없다.

**8-17 이 착지하는 자리**: 알림톡은 사전 승인된 템플릿으로만 나간다. 알림 유형 →
템플릿 코드 매핑이 `NOTIFICATION_KAKAO_TEMPLATE_CODES` 이고, 비어 있는 동안 알림톡
발송은 "승인된 템플릿 코드가 없습니다(성적)" 로 실패한다(조용한 성공보다 낫다 —
key_considerations §5).
"""
import requests
from django.conf import settings

from .channels import ChannelAdapter, Message, PermanentChannelError, TemporaryChannelError

SMS_ENDPOINT = "https://apis.aligo.in/send/"
ALIMTALK_ENDPOINT = "https://kakaoapi.aligo.in/akv10/alimtalk/send/"

#: 업체 응답을 기다리는 상한(초). 없으면 워커가 무한정 잡혀 있는다.
REQUEST_TIMEOUT_SECONDS = 10

#: SMS 한 건의 한도. 넘으면 LMS 로 나가야 하고, 그대로 보내면 잘리거나 거절된다.
SMS_BYTE_LIMIT = 90
#: 알리고 문자 제목(LMS/MMS) 길이 한도.
TITLE_BYTE_LIMIT = 44

#: 성공 판정 — 채널마다 필드도 값도 다르다(위 표).
_SMS_SUCCESS = 1
_ALIMTALK_SUCCESS = 0


class AligoAdapter(ChannelAdapter):
    """카카오 알림톡·문자를 알리고로 내보낸다.

    `http_post` 는 테스트가 HTTP 경계 하나만 갈아 끼우기 위한 자리다 —
    기본값은 `requests.post` 이고 운영에서는 그대로 쓴다.
    """

    def __init__(self, http_post=None):
        self._http_post = http_post or requests.post

    def send(self, message: Message) -> None:
        url, payload = self._build(message)
        body = self._request(url, payload)
        self._raise_for_result(body, url)

    # -- 조립 -------------------------------------------------------------

    def _build(self, message: Message):
        api_key = _required("ALIGO_API_KEY", "알리고 API 키가 설정되지 않았습니다.")
        user_id = _required("ALIGO_USER_ID", "알리고 user_id 가 설정되지 않았습니다.")
        sender = _required("ALIGO_SENDER_PHONE", "알리고 발신번호가 설정되지 않았습니다.")

        if message.channel == "카카오알림톡":
            return ALIMTALK_ENDPOINT, self._alimtalk_payload(message, api_key, user_id, sender)
        if message.channel == "문자":
            return SMS_ENDPOINT, self._sms_payload(message, api_key, user_id, sender)
        raise PermanentChannelError(f"알리고가 보낼 수 없는 채널입니다: {message.channel}")

    def _alimtalk_payload(self, message, api_key, user_id, sender):
        sender_key = _required(
            "ALIGO_SENDER_KEY", "카카오 발신프로필키(senderkey)가 설정되지 않았습니다."
        )
        template = getattr(settings, "NOTIFICATION_KAKAO_TEMPLATE_CODES", {}).get(message.type)
        if not template:
            # 8-17 대기 중. 승인 전에는 몇 번을 걸어도 나가지 않으므로 영구 실패다.
            raise PermanentChannelError(f"승인된 알림톡 템플릿 코드가 없습니다: {message.type}")
        return {
            # 문자 쪽과 파라미터 이름이 다르다(apikey/userid) — 섞으면 인증 오류다.
            "apikey": api_key,
            "userid": user_id,
            "senderkey": sender_key,
            "tpl_code": template,
            "sender": sender,
            "receiver_1": message.recipient,
            "subject_1": message.title,
            "message_1": message.body,
            # 카카오톡이 없는 수신자에게도 닿아야 한다 — 실패 시 문자로 떨어진다.
            "failover": "Y",
            "fsubject_1": message.title,
            "fmessage_1": message.body,
        }

    def _sms_payload(self, message, api_key, user_id, sender):
        payload = {
            "key": api_key,
            "user_id": user_id,
            "sender": sender,
            "receiver": message.recipient,
            "msg": message.body,
            "msg_type": "SMS" if _fits_in_sms(message.body) else "LMS",
        }
        if payload["msg_type"] == "LMS" and message.title:
            payload["title"] = _clip(message.title, TITLE_BYTE_LIMIT)
        return payload

    # -- 전송·해석 ---------------------------------------------------------

    def _request(self, url, payload) -> dict:
        """유일한 HTTP 지점. 길이 막힌 것만 일시 오류로 번역한다."""
        try:
            response = self._http_post(url, data=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            raise TemporaryChannelError(f"알리고 요청 실패: {exc}") from exc
        if response.status_code >= 500:
            raise TemporaryChannelError(f"알리고 서버 오류: HTTP {response.status_code}")
        if response.status_code >= 400:
            raise PermanentChannelError(f"알리고 요청이 거절됐습니다: HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            # 점검 페이지·프록시 오류가 HTML 로 온다 — 나중에 다시 걸면 된다.
            raise TemporaryChannelError("알리고 응답을 해석할 수 없습니다.") from exc

    @staticmethod
    def _raise_for_result(body, url):
        """성공 값이 채널마다 다르다 — 어느 엔드포인트로 보냈는지로 갈린다."""
        if url == ALIMTALK_ENDPOINT:
            code, expected = body.get("code"), _ALIMTALK_SUCCESS
        else:
            code, expected = body.get("result_code"), _SMS_SUCCESS
        if code == expected:
            return
        reason = body.get("message") or f"코드 {code}"
        raise PermanentChannelError(f"알리고 발송 거절: {reason}")


def _required(setting_name, reason):
    value = (getattr(settings, setting_name, "") or "").strip()
    if not value:
        raise PermanentChannelError(reason)
    return value


def _fits_in_sms(text: str) -> bool:
    """EUC-KR 90byte 이내면 SMS. 한글은 2byte 라 45자가 경계다."""
    return _byte_length(text) <= SMS_BYTE_LIMIT


def _clip(text: str, limit: int) -> str:
    """byte 한도에 맞춰 자른다 — 글자 중간에서 끊기지 않게 한 글자씩 줄인다."""
    clipped = text
    while _byte_length(clipped) > limit:
        clipped = clipped[:-1]
    return clipped


def _byte_length(text: str) -> int:
    return len(text.encode("euc-kr", errors="replace"))
