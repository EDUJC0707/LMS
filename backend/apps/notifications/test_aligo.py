"""알리고 어댑터 테스트 — 두 엔드포인트가 서로 다르다는 것이 핵심 위험이다.

같은 업체인데 문자와 알림톡이 **호스트·파라미터 이름·성공 코드까지 전부 다르다**:

| | 문자 | 알림톡 |
|---|---|---|
| 호스트 | `apis.aligo.in/send/` | `kakaoapi.aligo.in/akv10/alimtalk/send/` |
| 인증 | `key` · `user_id` | `apikey` · `userid` |
| 결과 필드 | `result_code` | `code` |
| **성공 값** | **1** | **0** |

성공 값을 뒤집어 쓰면 **나간 알림톡이 전부 실패로 기록된다** — 조용히 재발송이
돌고 학부모에게 두 번 간다. 그래서 두 경로의 성공/실패 판정을 따로 못 박는다.
"""
from django.test import SimpleTestCase, override_settings
from requests import RequestException

from .aligo import ALIMTALK_ENDPOINT, SMS_ENDPOINT, AligoAdapter
from .channels import Message, PermanentChannelError, TemporaryChannelError

CONFIGURED = {
    "ALIGO_API_KEY": "테스트키",
    "ALIGO_USER_ID": "테스트계정",
    "ALIGO_SENDER_PHONE": "0212345678",
    "ALIGO_SENDER_KEY": "테스트발신프로필",
    "NOTIFICATION_KAKAO_TEMPLATE_CODES": {"성적": "TPL_GRADE_001"},
}


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text="{}"):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def recorder(response=None, error=None):
    """호출을 기록하는 가짜 전송기 — HTTP 경계 하나만 대신한다."""
    calls = []

    def post(url, data=None, timeout=None):
        calls.append({"url": url, "data": data, "timeout": timeout})
        if error is not None:
            raise error
        return response if response is not None else FakeResponse({"result_code": 1})

    post.calls = calls
    return post


def message(
    channel="카카오알림톡",
    type="성적",
    title="성적 안내",
    body="3회차 성적이 등록되었습니다.",
):
    return Message(
        channel=channel, type=type, recipient="01011112222", title=title, body=body
    )


@override_settings(**CONFIGURED)
class ConfigurationTests(SimpleTestCase):
    @override_settings(ALIGO_API_KEY="")
    def test_missing_api_key_is_permanent(self):
        with self.assertRaises(PermanentChannelError) as caught:
            AligoAdapter(recorder()).send(message(channel="문자"))
        self.assertIn("키", str(caught.exception))

    @override_settings(ALIGO_USER_ID="")
    def test_missing_user_id_is_permanent(self):
        with self.assertRaises(PermanentChannelError):
            AligoAdapter(recorder()).send(message(channel="문자"))

    @override_settings(ALIGO_SENDER_PHONE="")
    def test_missing_sender_phone_is_permanent(self):
        with self.assertRaises(PermanentChannelError) as caught:
            AligoAdapter(recorder()).send(message(channel="문자"))
        self.assertIn("발신번호", str(caught.exception))

    @override_settings(ALIGO_SENDER_KEY="")
    def test_alimtalk_without_sender_key_is_permanent(self):
        with self.assertRaises(PermanentChannelError):
            AligoAdapter(recorder()).send(message())

    @override_settings(NOTIFICATION_KAKAO_TEMPLATE_CODES={})
    def test_unregistered_template_is_permanent_naming_the_type(self):
        # 8-17 대기 중 — 승인 전에는 몇 번을 걸어도 나가지 않는다.
        with self.assertRaises(PermanentChannelError) as caught:
            AligoAdapter(recorder()).send(message(type="성적"))
        self.assertIn("성적", str(caught.exception))

    def test_unsupported_channel_is_permanent(self):
        with self.assertRaises(PermanentChannelError) as caught:
            AligoAdapter(recorder()).send(message(channel="앱푸시"))
        self.assertIn("앱푸시", str(caught.exception))

    def test_nothing_is_sent_when_configuration_is_missing(self):
        # 설정이 비었는데 업체를 부르면 돈만 나가고 실패한다.
        post = recorder()
        with override_settings(ALIGO_API_KEY=""):
            with self.assertRaises(PermanentChannelError):
                AligoAdapter(post).send(message(channel="문자"))
        self.assertEqual(post.calls, [])


@override_settings(**CONFIGURED)
class SmsRequestTests(SimpleTestCase):
    def send(self, msg, response=None):
        post = recorder(response=response)
        AligoAdapter(post).send(msg)
        return post.calls[0]

    def test_sms_goes_to_the_sms_endpoint(self):
        self.assertEqual(self.send(message(channel="문자"))["url"], SMS_ENDPOINT)

    def test_sms_uses_key_and_user_id_parameter_names(self):
        data = self.send(message(channel="문자"))["data"]
        self.assertEqual(data["key"], "테스트키")
        self.assertEqual(data["user_id"], "테스트계정")
        self.assertNotIn("apikey", data)

    def test_sms_carries_sender_recipient_and_body(self):
        data = self.send(message(channel="문자", body="계정이 발급되었습니다."))["data"]
        self.assertEqual(data["sender"], "0212345678")
        self.assertEqual(data["receiver"], "01011112222")
        self.assertEqual(data["msg"], "계정이 발급되었습니다.")

    def test_short_body_is_sent_as_sms(self):
        data = self.send(message(channel="문자", body="짧은 문자"))["data"]
        self.assertEqual(data["msg_type"], "SMS")
        self.assertNotIn("title", data)

    def test_long_body_is_sent_as_lms_with_title(self):
        # 90byte(EUC-KR) 를 넘으면 SMS 로 못 나간다 — 넘기면 잘리거나 거절된다.
        data = self.send(message(channel="문자", body="가" * 50, title="성적 안내"))["data"]
        self.assertEqual(data["msg_type"], "LMS")
        self.assertEqual(data["title"], "성적 안내")

    def test_lms_title_is_truncated_to_the_vendor_limit(self):
        # 알리고 title 은 44byte 다 — 넘기면 요청이 거절된다.
        data = self.send(message(channel="문자", body="가" * 50, title="가" * 40))["data"]
        self.assertLessEqual(len(data["title"].encode("euc-kr", errors="replace")), 44)


@override_settings(**CONFIGURED)
class AlimtalkRequestTests(SimpleTestCase):
    def send(self, msg=None, response=None):
        post = recorder(response=response or FakeResponse({"code": 0}))
        AligoAdapter(post).send(msg or message())
        return post.calls[0]

    def test_alimtalk_goes_to_the_kakao_endpoint(self):
        self.assertEqual(self.send()["url"], ALIMTALK_ENDPOINT)

    def test_alimtalk_uses_apikey_and_userid_parameter_names(self):
        # 문자 쪽과 이름이 다르다 — 섞어 쓰면 인증 오류로 전부 실패한다.
        data = self.send()["data"]
        self.assertEqual(data["apikey"], "테스트키")
        self.assertEqual(data["userid"], "테스트계정")
        self.assertNotIn("key", data)
        self.assertNotIn("user_id", data)

    def test_alimtalk_carries_sender_key_and_template(self):
        data = self.send()["data"]
        self.assertEqual(data["senderkey"], "테스트발신프로필")
        self.assertEqual(data["tpl_code"], "TPL_GRADE_001")
        self.assertEqual(data["sender"], "0212345678")

    def test_alimtalk_uses_indexed_recipient_fields(self):
        data = self.send()["data"]
        self.assertEqual(data["receiver_1"], "01011112222")
        self.assertEqual(data["subject_1"], "성적 안내")
        self.assertEqual(data["message_1"], "3회차 성적이 등록되었습니다.")

    def test_alimtalk_falls_back_to_text_message(self):
        # 카카오톡이 없는 수신자에게도 닿아야 한다 — 실패하면 문자로 떨어진다.
        data = self.send()["data"]
        self.assertEqual(data["failover"], "Y")
        self.assertEqual(data["fsubject_1"], "성적 안내")
        self.assertEqual(data["fmessage_1"], "3회차 성적이 등록되었습니다.")


@override_settings(**CONFIGURED)
class ResultInterpretationTests(SimpleTestCase):
    """성공 값이 채널마다 다르다 — 여기가 이 어댑터에서 제일 틀리기 쉬운 곳이다."""

    def send(self, payload, channel="문자"):
        AligoAdapter(recorder(response=FakeResponse(payload))).send(message(channel=channel))

    def test_sms_result_code_1_is_success(self):
        self.send({"result_code": 1, "message": "success"})  # 예외 없어야 함

    def test_sms_negative_result_code_is_permanent(self):
        with self.assertRaises(PermanentChannelError) as caught:
            self.send({"result_code": -101, "message": "인증오류입니다."})
        self.assertIn("인증오류입니다.", str(caught.exception))

    def test_sms_zero_is_not_success(self):
        # 알림톡의 성공 값(0)을 문자에 적용하면 안 된다.
        with self.assertRaises(PermanentChannelError):
            self.send({"result_code": 0, "message": "실패"})

    def test_alimtalk_code_0_is_success(self):
        self.send({"code": 0, "message": "정상 접수"}, channel="카카오알림톡")

    def test_alimtalk_negative_code_is_permanent(self):
        with self.assertRaises(PermanentChannelError) as caught:
            self.send({"code": -99, "message": "템플릿 불일치"}, channel="카카오알림톡")
        self.assertIn("템플릿 불일치", str(caught.exception))

    def test_alimtalk_one_is_not_success(self):
        # 문자의 성공 값(1)을 알림톡에 적용하면 안 된다.
        with self.assertRaises(PermanentChannelError):
            self.send({"code": 1, "message": "실패"}, channel="카카오알림톡")


@override_settings(**CONFIGURED)
class TransportTests(SimpleTestCase):
    """업체 잘못이 아니라 길이 막힌 것은 재시도 대상이다."""

    def send(self, response=None, error=None):
        AligoAdapter(recorder(response=response, error=error)).send(message(channel="문자"))

    def test_network_failure_is_temporary(self):
        with self.assertRaises(TemporaryChannelError):
            self.send(error=RequestException("timeout"))

    def test_server_error_is_temporary(self):
        with self.assertRaises(TemporaryChannelError):
            self.send(response=FakeResponse({}, status_code=503))

    def test_client_error_is_permanent(self):
        with self.assertRaises(PermanentChannelError):
            self.send(response=FakeResponse({}, status_code=400))

    def test_non_json_body_is_temporary(self):
        # 점검 페이지·프록시 오류가 HTML 로 오는 경우 — 나중에 다시 걸면 된다.
        with self.assertRaises(TemporaryChannelError):
            self.send(response=FakeResponse(None, text="<html>점검중</html>"))

    def test_request_carries_a_timeout(self):
        # 타임아웃이 없으면 워커가 업체 응답을 무한정 기다린다.
        post = recorder()
        AligoAdapter(post).send(message(channel="문자"))
        self.assertIsNotNone(post.calls[0]["timeout"])
