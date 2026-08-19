"""테스트 전역 안전망 — 기계 밖으로 나가지 않는다.

`.env` 에 진짜 OCR 키가 들어 있고 `dev` 설정이 그걸 읽는다. 그래서 폴백 경로를
건드리는 테스트가 하나만 생겨도 **실제로 업체를 호출하고 과금된다.** 여기서
그 문을 막아 두면, 부르려는 테스트는 시끄럽게 실패한다(조용히 나가는 것보다
낫다). 진짜로 호출을 흉내 내려는 테스트는 자기가 `requests.post` 를 갈아
끼우므로 이 안전망 위에 그대로 얹힌다.

알림·이메일은 이미 dev 설정이 Fake 어댑터를 물려 두었다(config/settings/dev.py)
— 같은 원칙을 OCR 에도 세운 것이다.

업로드도 같은 축이다. 테스트가 진짜 `MEDIA_ROOT` 에 쓰면 **DB 는 롤백되는데
파일은 남는다** — 실제로 실행마다 쌓여 110개 26MB 가 되어 있었다(2026-08-12).
스토리지는 트랜잭션 밖이라 아무도 안 걷어 간다.

Sentry 도 같다. 전역 클라이언트라 켜 놓고 안 끄면 **다음 테스트가 물려받는다** —
`config.settings.prod` 는 import 만으로 켜므로 설정 한 줄을 읽으려던 테스트가
그렇게 된다(2026-08-19, `pytest -n 8` 로 순서가 흔들리자 드러났다). 각 테스트에
tearDown 을 다는 대신 여기서 한 번에 끈다.
"""
import tempfile

import pytest
import sentry_sdk

from apps.grades import ocr


@pytest.fixture(autouse=True)
def _no_outbound_ocr(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(
            "테스트가 실제 OCR 업체를 호출하려 했습니다. "
            "apps.grades.ocr.read_score 를 갈아 끼우세요."
        )

    monkeypatch.setattr(ocr.requests, "post", refuse)


@pytest.fixture(autouse=True, scope="session")
def _media_in_a_tempdir():
    """업로드는 임시 폴더로 — 테스트가 진짜 media/ 를 더럽히지 않는다."""
    from django.test import override_settings

    with tempfile.TemporaryDirectory() as folder:
        with override_settings(MEDIA_ROOT=folder):
            yield


@pytest.fixture(autouse=True)
def _sentry_stays_off():
    """테스트가 켠 Sentry 를 다음 테스트에 물려주지 않는다."""
    yield
    client = sentry_sdk.get_client()
    if client.is_active():
        client.close(timeout=0.0)
        sentry_sdk.get_global_scope().set_client(None)
