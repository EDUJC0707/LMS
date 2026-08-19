"""채널 어댑터 계약 테스트 — 업체 교체 가능성이 핵심 (PRD 6-8, key_considerations §4).

여기서 지키는 것은 하나다: **채널 추가·업체 교체가 설정 한 줄이고 스키마는 안
움직인다.** 그래서 테스트도 "어떤 업체가 붙었나"가 아니라 "설정을 바꾸면 그쪽이
불리나"를 본다.
"""
from django.test import SimpleTestCase, override_settings

from .channels import (
    ChannelAdapter,
    FakeChannelAdapter,
    Message,
    PermanentChannelError,
    TemporaryChannelError,
    get_adapter,
)

FAKE = "apps.notifications.channels.FakeChannelAdapter"
RECORDING = "apps.notifications.test_channels.RecordingAdapter"


class RecordingAdapter(ChannelAdapter):
    """설정만 바꿔 끼우는 다른 업체 자리 — 레지스트리 교체 가능성 증인."""

    sent: list = []

    def send(self, message):
        RecordingAdapter.sent.append(message)


def message(**kwargs):
    kwargs.setdefault("channel", "문자")
    kwargs.setdefault("type", "성적")
    kwargs.setdefault("recipient", "01012345678")
    kwargs.setdefault("title", "제목")
    kwargs.setdefault("body", "본문")
    return Message(**kwargs)


class MessageTests(SimpleTestCase):
    def test_message_carries_no_orm_object(self):
        # 어댑터는 ORM 을 모른다 — 업체 코드가 우리 모델을 붙들면 교체가 어려워진다.
        msg = message()
        self.assertEqual(msg.recipient, "01012345678")
        self.assertEqual(msg.type, "성적")
        for value in (msg.channel, msg.type, msg.recipient, msg.title, msg.body):
            self.assertIsInstance(value, str)


class ChannelRegistryTests(SimpleTestCase):
    def setUp(self):
        FakeChannelAdapter.outbox.clear()
        RecordingAdapter.sent.clear()

    @override_settings(NOTIFICATION_CHANNEL_BACKENDS={"문자": FAKE})
    def test_adapter_resolved_from_settings(self):
        self.assertIsInstance(get_adapter("문자"), FakeChannelAdapter)

    @override_settings(NOTIFICATION_CHANNEL_BACKENDS={"문자": RECORDING})
    def test_same_channel_swaps_implementation_by_settings(self):
        # 업체 교체 = 설정 한 줄. 채널 값도 스키마도 그대로다.
        get_adapter("문자").send(message())
        self.assertEqual(len(RecordingAdapter.sent), 1)
        self.assertEqual(FakeChannelAdapter.outbox, [])

    @override_settings(NOTIFICATION_CHANNEL_BACKENDS={"카카오알림톡": FAKE, "문자": RECORDING})
    def test_channels_resolve_independently(self):
        # 채널 추가 = Channel 값 + 설정 한 줄(스키마 불변).
        self.assertIsInstance(get_adapter("카카오알림톡"), FakeChannelAdapter)
        self.assertIsInstance(get_adapter("문자"), RecordingAdapter)

    @override_settings(NOTIFICATION_CHANNEL_BACKENDS={})
    def test_unconfigured_channel_is_permanent_error(self):
        # 안전 기본값은 닫힘(key_considerations §5) — 미설정이 조용한 성공이 되면
        # 운영에서 알림이 통째로 증발한다. 재시도해도 소용없으니 영구 실패다.
        with self.assertRaises(PermanentChannelError):
            get_adapter("카카오알림톡")

    @override_settings(
        NOTIFICATION_CHANNEL_BACKENDS={"문자": "apps.notifications.channels.없는어댑터"}
    )
    def test_broken_backend_path_is_permanent_error(self):
        with self.assertRaises(PermanentChannelError):
            get_adapter("문자")


class FakeChannelAdapterTests(SimpleTestCase):
    def setUp(self):
        FakeChannelAdapter.outbox.clear()

    def test_fake_records_what_it_was_asked_to_send(self):
        msg = message()
        FakeChannelAdapter().send(msg)
        self.assertEqual(FakeChannelAdapter.outbox, [msg])


class SettingsWiringTests(SimpleTestCase):
    """어느 환경이 어떤 구현체를 쓰는지 — 여기서 틀리면 알림이 통째로 증발한다."""

    def test_base_defaults_to_no_channel_configured(self):
        # 안전 기본값은 닫힘. 새 환경이 아무것도 안 물리면 발송이 실패하고
        # 사유가 남는다 — 조용히 성공하는 것보다 낫다.
        from config.settings import base

        self.assertEqual(base.NOTIFICATION_CHANNEL_BACKENDS, {})

    def test_prod_wires_the_real_vendor_not_the_fake(self):
        # Fake 가 운영에 남으면 발송내역에는 성공만 쌓이고 아무도 못 받는다.
        # `prod` 는 import 만으로 버킷을 요구하고 Sentry 를 켠다 — 되돌려 주는
        # 도구로 읽는다(config.prod_settings_probe).
        from config.prod_settings_probe import prod_settings

        with prod_settings() as prod:
            backends = prod.NOTIFICATION_CHANNEL_BACKENDS
        self.assertEqual(
            set(backends), {"카카오알림톡", "문자"}
        )
        for path in backends.values():
            self.assertIn("aligo", path)  # 업체 확정(decisions.md §3-1)
            self.assertNotIn("Fake", path)

    def test_dev_wires_the_fake_so_local_sending_does_not_leave_the_machine(self):
        from config.settings import dev

        for path in dev.NOTIFICATION_CHANNEL_BACKENDS.values():
            self.assertIn("Fake", path)


class ChannelErrorTests(SimpleTestCase):
    def test_error_kinds_split_retryable_from_final(self):
        # 재시도 여부는 예외 종류가 말한다 — 문자열 파싱으로 갈리면 업체마다 깨진다.
        self.assertTrue(issubclass(TemporaryChannelError, Exception))
        self.assertFalse(issubclass(TemporaryChannelError, PermanentChannelError))
        self.assertFalse(issubclass(PermanentChannelError, TemporaryChannelError))
