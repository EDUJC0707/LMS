"""화상 어댑터 계약 검증 — 업체가 들어오는 문이 하나인지(key_considerations §4).

notifications 의 `test_channels.py` 와 같은 축이다: 설정이 비면 **닫힘**,
경로가 틀리면 영구 실패, 어댑터는 우리 ORM 을 모른다.
"""
from django.test import SimpleTestCase, override_settings

from .conferencing import (
    Conference,
    ConferenceAdapter,
    PermanentConferenceError,
    get_adapter,
)


class StubAdapter(ConferenceAdapter):
    """테스트용 스탠드인 — 실제 스페이스를 만들지 않는다."""

    def create_space(self):
        return Conference(provider="google_meet", ref="spaces/STUB", url="https://x/stub")

    def fetch_supervision(self, ref, *, file_as=None):
        return None


class GetAdapterTests(SimpleTestCase):
    @override_settings(CLINIC_CONFERENCE_BACKEND="")
    def test_unset_backend_is_closed(self):
        # 안전 기본값은 닫힘(§5) — 미설정을 조용한 성공으로 만들지 않는다
        with self.assertRaises(PermanentConferenceError):
            get_adapter()

    @override_settings(CLINIC_CONFERENCE_BACKEND="apps.clinic.nope.Missing")
    def test_bad_path_is_permanent(self):
        with self.assertRaises(PermanentConferenceError):
            get_adapter()

    @override_settings(CLINIC_CONFERENCE_BACKEND="apps.clinic.test_conferencing.StubAdapter")
    def test_configured_path_is_instantiated(self):
        self.assertIsInstance(get_adapter(), StubAdapter)


class ConferenceValueTests(SimpleTestCase):
    def test_carries_provider_ref_and_url(self):
        # 모델 3열과 같은 모양 — 어댑터가 돌려주는 전부다
        conference = Conference(provider="google_meet", ref="spaces/a", url="https://x/a")
        self.assertEqual(
            (conference.provider, conference.ref, conference.url),
            ("google_meet", "spaces/a", "https://x/a"),
        )

    def test_is_immutable(self):
        conference = Conference(provider="google_meet", ref="spaces/a", url="https://x/a")
        with self.assertRaises(Exception):
            conference.url = "https://x/b"


class StartSupervisionDefaultTests(SimpleTestCase):
    """감독 시작은 **선택 사항**이다 — 구현 안 한 어댑터가 깨지면 안 된다."""

    def test_defaults_to_doing_nothing(self):
        # 구글은 스페이스 설정으로 알아서 전사를 시작한다. 봇을 넣어야 하는
        # 업체만 이걸 구현하고, 나머지는 이 기본값 위에서 그대로 돈다.
        class Bare(ConferenceAdapter):
            def create_space(self):
                return Conference(provider="p", ref="r", url="u")

            def fetch_supervision(self, ref, *, file_as=None):
                return None

        self.assertIsNone(Bare().start_supervision("https://x/a", title="t", minutes=60))

    def test_scheduling_and_cancelling_also_default_to_nothing(self):
        # 예약형(업체가 시작 시각에 알아서 들어옴)을 지원하는 업체만 구현한다.
        class Bare(ConferenceAdapter):
            def create_space(self):
                return Conference(provider="p", ref="r", url="u")

            def fetch_supervision(self, ref, *, file_as=None):
                return None

        bare = Bare()
        self.assertIsNone(
            bare.schedule_supervision(
                "https://x/a", key="clinic1", title="t", starts_at=None, minutes=60
            )
        )
        self.assertIsNone(bare.cancel_supervision("clinic1"))
