"""테스트 전역 안전망 — 기계 밖으로 나가지 않는다.

`.env` 에 진짜 OCR 키가 들어 있고 `dev` 설정이 그걸 읽는다. 그래서 폴백 경로를
건드리는 테스트가 하나만 생겨도 **실제로 업체를 호출하고 과금된다.** 여기서
그 문을 막아 두면, 부르려는 테스트는 시끄럽게 실패한다(조용히 나가는 것보다
낫다). 진짜로 호출을 흉내 내려는 테스트는 자기가 `requests.post` 를 갈아
끼우므로 이 안전망 위에 그대로 얹힌다.

알림·이메일은 이미 dev 설정이 Fake 어댑터를 물려 두었다(config/settings/dev.py)
— 같은 원칙을 OCR 에도 세운 것이다.
"""
import pytest

from apps.grades import ocr


@pytest.fixture(autouse=True)
def _no_outbound_ocr(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError(
            "테스트가 실제 OCR 업체를 호출하려 했습니다. "
            "apps.grades.ocr.read_score 를 갈아 끼우세요."
        )

    monkeypatch.setattr(ocr.requests, "post", refuse)
