"""감독 요약 — 전사 원문을 관리자가 읽을 문장으로.

**전사와 다른 업체다.** 받아쓰기는 CLOVA(한국어 정확도), 요약은 여기다.
같은 녹취로 CLOVA Studio·GPT-5.6 Luna/Terra/Sol 을 나란히 돌려 고른 결과가
**Luna** 다(2026-08-19):

  · 지어낸 사건 0 · 가짜 인용 0 — CLOVA 만 두 줄을 한 문장으로 합쳐 인용했다
  · 가장 빠름(5.8초) · 1건 약 1원 — Sol 의 30분의 1
  · 상위 모델이 값을 못 했다. 우리 일은 어려운 추론이 아니라 "원문에 있나"
    판정이고, Sol 은 오히려 감독과 무관한 네트워크 지연을 특이사항으로 골랐다

**요약은 덤이다.** 실패해도 전사는 이미 문서로 남는다(recall._summarise).
"""
import json

from django.conf import settings

from .conferencing import PermanentConferenceError, TemporaryConferenceError
from .google_meet import urllib_transport

ENDPOINT = "https://api.openai.com/v1/responses"

#: 요약이 길 이유가 없다 — 관리자가 훑고 판단하는 글이다.
MAX_OUTPUT_TOKENS = 800

#: 어려운 추론이 아니라 "원문에 있나" 판정이라 낮게 둔다. 올리면 느려지고 비싸다.
REASONING_EFFORT = "low"

TIMEOUT_SECONDS = 300

_RETRYABLE_STATUSES = frozenset({408, 429})

#: 관리자가 읽고 조교를 판단하는 글이다. 그래서 "무슨 얘기가 오갔나"가 아니라
#: **"제대로 가르쳤나"** 를 묻는다 — 토픽 나열은 판단 근거가 되지 못한다.
PROMPT = (
    "너는 학원 관리자다. 아래는 강사(조교)와 학생이 1:1 로 오답을 푸는 "
    "보충 수업의 녹취록이다. 줄마다 `시:분:초 [화자]` 가 붙어 있고, "
    "화자 번호가 누가 누구인지는 알려져 있지 않다. "
    "관리자가 조교의 수업을 판단할 수 있도록 한국어로 짧게 정리해라.\n"
    "- 무엇을 다뤘는지 한 줄\n"
    "- 조교가 오답의 원인을 설명했는지\n"
    "- 학생이 이해했는지 확인하는 장면이 있었는지\n"
    "- 눈에 띄는 문제(설명이 끊김·잡담·한쪽이 오래 혼자 말함 등)\n"
    "녹취에 없는 것은 쓰지 마라. 없으면 '확인되지 않음' 이라고 적어라."
)


def summarize(text, *, transport=None):
    """전사 원문 → 감독용 요약. 원문이 비면 부르지 않고 None."""
    body = (text or "").strip()
    if not body:
        # 아무도 말하지 않은 회의 — 부를 이유가 없다(요금도 안 쓴다).
        return None

    key = getattr(settings, "OPENAI_API_KEY", "")
    if not key:
        raise PermanentConferenceError("요약 자격증명이 설정되지 않았습니다.")
    model = getattr(settings, "SUMMARY_MODEL", "") or "gpt-5.6-luna"

    status, raw = (transport or urllib_transport)(
        "POST",
        ENDPOINT,
        json.dumps(
            {
                "model": model,
                "input": [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": body},
                ],
                "max_output_tokens": MAX_OUTPUT_TOKENS,
                "reasoning": {"effort": REASONING_EFFORT},
            },
            ensure_ascii=False,
        ).encode(),
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        TIMEOUT_SECONDS,
    )
    if status >= 300:
        detail = raw.decode(errors="replace")[:200]
        message = f"요약에 실패했습니다({status}): {detail}"
        if status in _RETRYABLE_STATUSES or status >= 500:
            raise TemporaryConferenceError(message)
        raise PermanentConferenceError(message)
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise PermanentConferenceError("요약 응답을 읽을 수 없습니다.") from exc

    # 응답은 조각 목록이다 — 생각 조각과 글 조각이 섞여 오므로 글만 잇는다.
    said = "".join(
        chunk.get("text", "")
        for item in payload.get("output") or []
        for chunk in item.get("content") or []
        if chunk.get("type") == "output_text"
    )
    return said.strip() or None
