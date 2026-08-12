"""손글씨 OCR — 마킹이 없는 장에서 점수만 건진다 (업체 경계).

## 왜 있나 — 엔진이 못 읽는 장이 3분의 1이다

`성적 조사 카드` 실물 94장 중 **34장이 버블을 하나도 안 칠하고** ★내 점수★
칸에 손으로만 적어 냈다(2026-08-11 실측). 엔진은 마킹만 읽으므로(decisions.md
"인식 방식") 그 34장은 통째로 보류다. 여기가 그 34장을 위한 자리다.

**엔진 규칙은 안 바뀐다.** 마킹은 여전히 마킹만으로 읽는다 — OCR 은 마킹이
없을 때만, 점수 한 칸에만 부른다. 이름·전화·답은 절대 OCR 로 읽지 않는다.

## 지면 밖으로 나가는 것은 숫자뿐이다

보내는 것은 `★내 점수★` 칸을 자른 조각이고, 그 칸에는 **숫자만** 있다 —
이름도 전화 뒷자리도 들어 있지 않다(card.SURVEY_SCORE_HANDWRITING 주석).
스캔 전면을 보내면 실명과 전화가 함께 나가므로 **절대 그러지 않는다.**

## 실측 (2026-08-11, Upstage `model=ocr`)

정답을 아는 표본(버블이 칠해진 59장)에서:

| | |
|---|---|
| 손글씨가 있는 장에서 맞힌 비율 | 42/44 = 95.5% |
| 맞힌 건 신뢰도 | 최소 0.748 · 중앙 0.995 |
| 틀린 건 신뢰도 | 0.617 · 0.890 |
| **신뢰도 0.90 문턱** | 자동 채택 36장 · **오답 0** |

그래서 문턱을 0.90 에 둔다 — 그 위에서는 실측 오답이 없었고, 아래는 사람에게
넘긴다(닫힘 기본값 — key_considerations §5). 틀린 두 건은 `1` 과 `7` 이었다:
한국식 7 은 가로줄이 있어 1 과 붙는다.

보류 34장에 대 보면 20장이 문턱을 넘었다. 12장은 손글씨조차 없었다(백지).

## 업체를 갈아 끼우는 자리

이 모듈 하나다(key_considerations §4 — 클리닉 화상 어댑터 선례). 호출부는
`read_score(png) -> int | None` 만 안다. 키가 없으면 **부르지 않고 None** 이라
OCR 없이도 시스템이 그대로 돈다.
"""
import logging
import re

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_URL = "https://api.upstage.ai/v1/document-digitization"
#: 점수가 될 수 있는 값의 범위. 지면의 10의 자리가 1~5, 1의 자리가 0~9 다.
_MAX_SCORE = 59


def read_score(png):
    """`★내 점수★` 칸 PNG → 점수(int). 못 읽거나 못 믿으면 None.

    None 을 돌려주는 경우가 넷이다. 넷 다 "사람이 본다"로 수렴한다:
    키 없음 · 호출 실패 · 신뢰도 미달 · 지면이 표현할 수 없는 값.
    """
    if not settings.UPSTAGE_API_KEY:
        return None
    try:
        response = requests.post(
            _URL,
            headers={"Authorization": f"Bearer {settings.UPSTAGE_API_KEY}"},
            files={"document": ("score.png", png, "image/png")},
            data={"model": "ocr"},
            timeout=settings.OMR_OCR_TIMEOUT,
        )
        response.raise_for_status()
        body = response.json()
    except requests.RequestException as error:
        # 업체가 죽어도 판독이 죽지는 않는다 — 그 장만 보류로 남는다.
        logger.warning("omr ocr failed: %s", error)
        return None

    digits = re.sub(r"\D", "", body.get("text") or "")
    confidence = body.get("confidence") or 0.0
    if not digits or confidence < settings.OMR_OCR_MIN_CONFIDENCE:
        return None
    score = int(digits)
    if not 0 <= score <= _MAX_SCORE:
        # 지면이 낼 수 없는 수다 — 칸 밖의 글자를 물었다는 뜻이라 버린다.
        return None
    return score
