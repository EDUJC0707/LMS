"""운영 설정을 읽어 보는 테스트용 도구 — **부작용을 되돌려 준다.**

`config.settings.prod` 는 import 만으로 두 가지를 한다:

- 오브젝트 스토리지 버킷이 없으면 **부팅을 거부한다**(`ImproperlyConfigured`)
- `SENTRY_DSN` 이 있으면 **Sentry 를 전역으로 켠다**(`init_sentry`)

그래서 설정 한 줄을 읽으려고 reload 한 테스트가 **다음 테스트에 켜진 Sentry 를
물려준다.** 2026-08-19 에 실제로 그랬다 — `payments.test_provider` 와
`notifications.test_channels` 가 뒷정리 없이 reload 했고, 직렬에서는 순서가 우연히
안전했다가 `pytest -n 8` 로 순서가 흔들리자 `SentryInitTests` 가 무작위로 깨졌다.

세 파일이 같은 다섯 줄을 각자 베껴 쓰고 있었으므로 여기 한 곳에 둔다.
"""

import contextlib
import importlib
import os
from unittest import mock

import sentry_sdk


def _reset_sentry():
    client = sentry_sdk.get_client()
    if client.is_active():
        client.close(timeout=0.0)
    sentry_sdk.get_global_scope().set_client(None)


@contextlib.contextmanager
def prod_settings(**environ):
    """운영 설정 모듈을 reload 해서 넘겨준다. 빠져나올 때 Sentry 를 되돌린다."""
    environ.setdefault("AWS_STORAGE_BUCKET_NAME", "test-bucket")
    try:
        with mock.patch.dict(os.environ, environ):
            yield importlib.reload(importlib.import_module("config.settings.prod"))
    finally:
        _reset_sentry()
