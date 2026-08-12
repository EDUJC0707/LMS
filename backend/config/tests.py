"""config 레벨(설정·루트 URL) 테스트 — Sentry 연결과 개인정보 차단 계약.

`manage.py test apps` 는 apps 아래만 돈다. 이 파일은 `manage.py test apps config`
또는 `make test`(pytest 는 backend/ 전체를 수집) 로 실행된다.
"""
import importlib
import logging
import os
from unittest import mock

import sentry_sdk
from django.test import Client, SimpleTestCase, override_settings

from config.observability import init_sentry

# 형식만 유효한 가짜 DSN — 이벤트를 실제로 보내지 않으므로 붙지 않는 호스트를 쓴다.
FAKE_DSN = "https://publickey@o0.ingest.example.invalid/1"
TOKEN = "8Qw3-tEst-tOken"


class SentryInitTests(SimpleTestCase):
    """DSN 유무가 곧 on/off 다 — 그리고 켜졌을 때 개인정보가 실려 나가면 안 된다."""

    def tearDown(self):
        client = sentry_sdk.get_client()
        if client.is_active():
            client.close(timeout=0.0)
        sentry_sdk.get_global_scope().set_client(None)

    def test_no_dsn_leaves_sdk_off(self):
        # DSN 이 없는데 init 이 불리면 켜진 줄 알고 지나간다 — 가드가 사라지는 것을 막는다.
        self.assertFalse(init_sentry(""))
        self.assertFalse(sentry_sdk.get_client().is_active())

    def test_dsn_turns_sdk_on(self):
        self.assertTrue(init_sentry(FAKE_DSN))
        self.assertTrue(sentry_sdk.get_client().is_active())

    def test_malformed_dsn_does_not_break_boot(self):
        # 시크릿 오타 하나로 부팅이 죽으면 안 된다(관측 도구 때문에 서비스가 내려간다).
        # 대신 조용히 넘기지 않고 경고를 남긴다 — "켠 줄 알았는데 안 켜짐"이 최악이다.
        with self.assertLogs("config.observability", level=logging.WARNING):
            self.assertFalse(init_sentry("이건-dsn-이-아니다"))
        self.assertFalse(sentry_sdk.get_client().is_active())

    def test_active_client_collects_no_pii(self):
        # 학생 이름·전화번호가 요청 본문과 스택 프레임 지역변수로 새어 나간다.
        # send_default_pii 만으로는 둘 다 막히지 않는다(본문은 max_request_body_size,
        # 지역변수는 include_local_variables 소관).
        init_sentry(FAKE_DSN)
        options = sentry_sdk.get_client().options
        self.assertFalse(options["send_default_pii"])
        self.assertEqual(options["max_request_body_size"], "never")
        self.assertFalse(options["include_local_variables"])

    def test_release_is_tagged_on_events(self):
        # 이게 없으면 "어제 500 났는데 그게 어느 배포냐"에 답할 수 없다.
        init_sentry(FAKE_DSN, release="9f1c2ab")
        self.assertEqual(sentry_sdk.get_client().options["release"], "9f1c2ab")



class ProdSettingsSentryTests(SimpleTestCase):
    """운영 설정이 실제로 Sentry 를 켜는가 — prod.py 에서 호출이 빠지면 조용히 안 켜진다."""

    def tearDown(self):
        client = sentry_sdk.get_client()
        if client.is_active():
            client.close(timeout=0.0)
        sentry_sdk.get_global_scope().set_client(None)

    def load_prod_settings(self, **environ):
        # 운영은 오브젝트 스토리지 없이는 부팅을 거부한다(prod.py) — 설정을
        # 읽어 보려는 테스트는 그 조건을 채워 줘야 한다.
        environ.setdefault("AWS_STORAGE_BUCKET_NAME", "test-bucket")
        with mock.patch.dict(os.environ, environ):
            importlib.reload(importlib.import_module("config.settings.prod"))

    def test_dsn_env_turns_sentry_on_without_pii(self):
        self.load_prod_settings(SENTRY_DSN=FAKE_DSN)
        client = sentry_sdk.get_client()
        self.assertTrue(client.is_active())
        self.assertEqual(client.options["max_request_body_size"], "never")
        self.assertFalse(client.options["include_local_variables"])

    def test_no_dsn_env_leaves_sentry_off(self):
        self.load_prod_settings(SENTRY_DSN="")
        self.assertFalse(sentry_sdk.get_client().is_active())



class SentryScrubTests(SimpleTestCase):
    """before_send 가 이벤트에서 무엇을 지우는지 — 실제로 켠 클라이언트를 거쳐 확인한다."""

    def setUp(self):
        init_sentry(FAKE_DSN)
        self.before_send = sentry_sdk.get_client().options["before_send"]

    def tearDown(self):
        client = sentry_sdk.get_client()
        if client.is_active():
            client.close(timeout=0.0)
        sentry_sdk.get_global_scope().set_client(None)

    def make_event(self, **request_overrides):
        request = {
            "url": "https://edujc-lms.fly.dev/api/admin/accounts/students",
            "method": "POST",
            "query_string": "",
            "headers": {"Content-Type": "application/json", "User-Agent": "curl/8.4"},
            "env": {"SERVER_NAME": "edujc-lms.fly.dev", "SERVER_PORT": "8000"},
        }
        request.update(request_overrides)
        return {"level": "error", "request": request}

    def test_request_body_is_dropped(self):
        event = self.before_send(
            self.make_event(data={"name": "김하늘", "phone": "01012345678"}), {}
        )
        self.assertNotIn("data", event["request"])

    def test_query_values_are_masked_but_keys_remain(self):
        event = self.before_send(self.make_event(query_string="q=김하늘&page=3"), {})
        self.assertEqual(event["request"]["query_string"], "q=[Filtered]&page=[Filtered]")

    def test_url_and_headers_survive(self):
        # 다 지우면 "어제 왜 500 났지"에 답할 수 없다 — 어느 엔드포인트였는지는 남아야 한다.
        event = self.before_send(self.make_event(), {})
        self.assertEqual(
            event["request"]["url"], "https://edujc-lms.fly.dev/api/admin/accounts/students"
        )
        self.assertEqual(event["request"]["headers"]["User-Agent"], "curl/8.4")

    def test_event_without_request_passes_through(self):
        # 관리 명령·Celery 태스크 이벤트에는 request 가 없다.
        event = self.before_send({"level": "error"}, {})
        self.assertEqual(event, {"level": "error"})


class SentryDebugViewTests(SimpleTestCase):
    """수집 확인용 엔드포인트 — 토큰이 맞을 때만 500 을 낸다."""

    @override_settings(SENTRY_DEBUG_TOKEN="")
    def test_hidden_when_token_unset(self):
        self.assertEqual(self.client.get("/sentry-debug").status_code, 404)

    @override_settings(SENTRY_DEBUG_TOKEN=TOKEN)
    def test_wrong_token_is_404(self):
        self.assertEqual(self.client.get(f"/sentry-debug?token={TOKEN}x").status_code, 404)

    @override_settings(SENTRY_DEBUG_TOKEN=TOKEN)
    def test_non_ascii_token_is_404_not_500(self):
        # compare_digest 는 str 이면 ASCII 만 받는다 — 한글이 들어오면 404 가 아니라 터졌다.
        self.assertEqual(self.client.get("/sentry-debug?token=틀린토큰").status_code, 404)

    @override_settings(SENTRY_DEBUG_TOKEN=TOKEN)
    def test_correct_token_raises(self):
        client = Client(raise_request_exception=False)
        with self.assertLogs("django.request", level=logging.ERROR):
            self.assertEqual(client.get(f"/sentry-debug?token={TOKEN}").status_code, 500)


class StorageSettingsTests(SimpleTestCase):
    """`fly storage create` 가 넣어 준 이름을 그대로 읽는가.

    Tigris 는 `BUCKET_NAME`·`AWS_ENDPOINT_URL_S3`·`AWS_REGION` 으로 주입하고
    django-storages 는 `AWS_STORAGE_BUCKET_NAME`·`AWS_S3_ENDPOINT_URL`·
    `AWS_S3_REGION_NAME` 을 쓴다. 예전에는 배포 문서가 **별칭을 손으로 set** 하라고
    했는데 그 한 단계가 빠져 있었고, 앱은 아무 소리 없이 파일시스템으로 떨어져
    있었다(2026-08-12 fly secrets 확인). 손 절차는 잊힌다 — 코드가 읽는다.
    """

    def load_base(self, **environ):
        with mock.patch.dict(os.environ, environ, clear=False):
            return importlib.reload(importlib.import_module("config.settings.base"))

    def tearDown(self):
        importlib.reload(importlib.import_module("config.settings.base"))

    def test_it_reads_the_names_tigris_actually_injects(self):
        base = self.load_base(
            BUCKET_NAME="edujc-lms-storage",
            AWS_ENDPOINT_URL_S3="https://t3.storage.dev",
            AWS_REGION="auto",
        )

        self.assertEqual(base.AWS_STORAGE_BUCKET_NAME, "edujc-lms-storage")
        self.assertEqual(base.AWS_S3_ENDPOINT_URL, "https://t3.storage.dev")
        self.assertIn("s3", base.STORAGES["default"]["BACKEND"])

    def test_the_injected_name_wins_when_both_are_set(self):
        """둘 다 있으면 fly 가 준 쪽이다 — 시크릿을 두 벌 심으면 한쪽만 바뀌어 어긋난다."""
        base = self.load_base(
            AWS_STORAGE_BUCKET_NAME="alias", BUCKET_NAME="injected"
        )

        self.assertEqual(base.AWS_STORAGE_BUCKET_NAME, "injected")

    def test_no_bucket_leaves_the_filesystem_in_place(self):
        """로컬·테스트는 버킷이 없다 — 그때는 S3 로 붙으면 안 된다."""
        with mock.patch.dict(
            os.environ, {"AWS_STORAGE_BUCKET_NAME": "", "BUCKET_NAME": ""}, clear=False
        ):
            base = importlib.reload(importlib.import_module("config.settings.base"))

        self.assertEqual(base.AWS_STORAGE_BUCKET_NAME, "")
        self.assertNotIn("s3", str(getattr(base, "STORAGES", {})))
