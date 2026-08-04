"""솔라피 어댑터 테스트 — 업체 지식이 이 파일 밖으로 새지 않는지 본다.

키가 없어도 검증할 수 있는 것이 대부분이다: 설정 누락 판정, 채널→메시지 유형
매핑, 알림톡 템플릿 코드 해석, 페이로드 조립. 실제로 막혀 있는 것은 HTTP 한
군데(`_request`)뿐이고, 그 사실 자체도 테스트가 못 박는다.
"""
from django.test import SimpleTestCase, override_settings

from .channels import Message, PermanentChannelError
from .solapi import SolapiAdapter

CONFIGURED = {
    "SOLAPI_API_KEY": "테스트키",
    "SOLAPI_API_SECRET": "테스트시크릿",
    "SOLAPI_SENDER_PHONE": "0212345678",
    "SOLAPI_KAKAO_PFID": "테스트채널",
}


class RecordingSolapiAdapter(SolapiAdapter):
    """HTTP 이음매만 갈아 끼운다 — 이음매가 하나임의 증인."""

    def __init__(self):
        self.payloads = []

    def _request(self, payload):
        self.payloads.append(payload)


def message(
    channel="카카오알림톡",
    type="성적",
    title="성적 안내",
    body="3회차 성적이 등록되었습니다.",
):
    return Message(
        channel=channel, type=type, recipient="01011112222", title=title, body=body
    )


class ConfigurationTests(SimpleTestCase):
    @override_settings(SOLAPI_API_KEY="", SOLAPI_API_SECRET="", SOLAPI_SENDER_PHONE="0212345678")
    def test_missing_api_key_is_permanent_error(self):
        with self.assertRaises(PermanentChannelError) as caught:
            SolapiAdapter().send(message(channel="문자"))
        self.assertIn("키", str(caught.exception))

    @override_settings(**{**CONFIGURED, "SOLAPI_SENDER_PHONE": ""})
    def test_missing_sender_phone_is_permanent_error(self):
        with self.assertRaises(PermanentChannelError) as caught:
            SolapiAdapter().send(message(channel="문자"))
        self.assertIn("발신번호", str(caught.exception))

    @override_settings(**CONFIGURED)
    def test_unsupported_channel_is_permanent_error(self):
        # 앱푸시는 솔라피가 보내는 채널이 아니다 — 다른 어댑터를 물릴 자리다.
        with self.assertRaises(PermanentChannelError) as caught:
            SolapiAdapter().send(message(channel="앱푸시"))
        self.assertIn("앱푸시", str(caught.exception))

    @override_settings(**{**CONFIGURED, "SOLAPI_KAKAO_PFID": ""})
    def test_kakao_without_channel_id_is_permanent_error(self):
        with self.assertRaises(PermanentChannelError):
            SolapiAdapter().send(message())


@override_settings(**CONFIGURED)
class KakaoTemplateTests(SimpleTestCase):
    @override_settings(NOTIFICATION_KAKAO_TEMPLATE_CODES={})
    def test_unregistered_template_is_permanent_error_naming_the_type(self):
        # 8-17 이 안 와서 승인된 템플릿이 아직 없다 — 재시도해도 승인되지 않는다.
        # 사유에 알림 유형이 들어가야 관리자가 무엇이 막혔는지 안다.
        with self.assertRaises(PermanentChannelError) as caught:
            RecordingSolapiAdapter().send(message(type="성적"))
        self.assertIn("성적", str(caught.exception))

    @override_settings(NOTIFICATION_KAKAO_TEMPLATE_CODES={"성적": "TPL_GRADE_001"})
    def test_registered_template_goes_into_the_payload(self):
        adapter = RecordingSolapiAdapter()

        adapter.send(message(type="성적"))

        options = adapter.payloads[0]["message"]["kakaoOptions"]
        self.assertEqual(options["templateId"], "TPL_GRADE_001")
        self.assertEqual(options["pfId"], "테스트채널")

    @override_settings(NOTIFICATION_KAKAO_TEMPLATE_CODES={"성적": "TPL_GRADE_001"})
    def test_sms_channel_needs_no_template(self):
        adapter = RecordingSolapiAdapter()

        adapter.send(message(channel="문자", type="계정발급"))

        self.assertNotIn("kakaoOptions", adapter.payloads[0]["message"])


@override_settings(**CONFIGURED, NOTIFICATION_KAKAO_TEMPLATE_CODES={"성적": "TPL_GRADE_001"})
class PayloadTests(SimpleTestCase):
    def payload_for(self, msg):
        adapter = RecordingSolapiAdapter()
        adapter.send(msg)
        return adapter.payloads[0]["message"]

    def test_recipient_and_sender_are_mapped(self):
        payload = self.payload_for(message())
        self.assertEqual(payload["to"], "01011112222")
        self.assertEqual(payload["from"], "0212345678")

    def test_body_is_the_text(self):
        payload = self.payload_for(message(body="3회차 성적이 등록되었습니다."))
        self.assertEqual(payload["text"], "3회차 성적이 등록되었습니다.")

    def test_kakao_channel_sends_as_alimtalk(self):
        self.assertEqual(self.payload_for(message())["type"], "ATA")

    def test_short_sms_is_sms_type(self):
        payload = self.payload_for(message(channel="문자", body="짧은 문자"))
        self.assertEqual(payload["type"], "SMS")
        self.assertNotIn("subject", payload)

    def test_long_sms_becomes_lms_with_subject(self):
        # 한글 90바이트(EUC-KR)를 넘으면 SMS 로는 못 나간다 — 넘기면 잘리거나 거절된다.
        payload = self.payload_for(message(channel="문자", body="가" * 50, title="성적 안내"))
        self.assertEqual(payload["type"], "LMS")
        self.assertEqual(payload["subject"], "성적 안내")


class HttpSeamTests(SimpleTestCase):
    @override_settings(**CONFIGURED, NOTIFICATION_KAKAO_TEMPLATE_CODES={"성적": "TPL_GRADE_001"})
    def test_http_call_is_not_wired_yet_and_says_so(self):
        # 키 수령 전이다. 설정 누락과 구분되는 사유가 나와야 관리자가 헷갈리지 않는다.
        with self.assertRaises(PermanentChannelError) as caught:
            SolapiAdapter().send(message())
        self.assertIn("연동", str(caught.exception))
