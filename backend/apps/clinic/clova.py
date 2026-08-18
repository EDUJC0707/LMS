"""CLOVA Speech — 오디오를 한국어 텍스트로. **회의에는 못 들어간다.**

이건 엔진이지 회의 참가자가 아니다. 오디오 URL 을 주면 전사해 준다. 회의에서
소리를 떠 오는 일은 `recall.py` 가 하고, 여기는 받아쓰기만 한다.

**왜 구글·업체 전사 대신 이걸 쓰나.** 제3자 벤치마크(rtzr, AI-Hub 6종, 세트당
3,000문장)에서 한국어 강연 CER **7.08% 로 1위**다 — Deepgram nova-2 21.02%,
Gemini 2.0 Flash 16.58%, Google STT v2 11.50%. 회의록 업체들의 "99% 정확도"는
언어별로 분해된 적이 없는 마케팅 숫자라 근거로 치지 않는다.

**`boostings` 가 이 엔진에만 있는 값이다.** 전사 전에 단어를 넣어 인식을 그쪽
으로 쏠리게 한다. LMS 는 그 클리닉이 어느 시험·단원인지 이미 알고 있으므로
단원 용어를 실어 보낼 수 있다 — 우리가 실제로 틀렸던 `대립유전자 → 대리비전자`
(2026-08-12 실측)가 정확히 이걸로 푸는 종류다.
"""
import json

from django.conf import settings

from .conferencing import PermanentConferenceError, TemporaryConferenceError
from .google_meet import urllib_transport

#: 회의 한 건이 길어서 넉넉히 잡는다 — 동기 호출이라 전사가 끝날 때까지 기다린다.
TIMEOUT_SECONDS = 600

_RETRYABLE_STATUSES = frozenset({408, 429})


def transcribe(audio_url, *, terms=(), transport=None):
    """오디오 URL → `"[화자] 말\\n[화자] 말"` 텍스트. 발화가 없으면 빈 문자열.

    **화자 이름은 붙이지 않는다.** 업체는 `1`·`2` 같은 라벨만 주고 누가 조교
    인지는 회의 밖 정보다. 라벨을 그대로 남기고 판단은 사람이 한다.
    """
    invoke = (getattr(settings, "CLOVA_SPEECH_INVOKE_URL", "") or "").rstrip("/")
    secret = getattr(settings, "CLOVA_SPEECH_SECRET", "")
    if not invoke or not secret:
        raise PermanentConferenceError("CLOVA Speech 자격증명이 설정되지 않았습니다.")

    body = {
        "url": audio_url,
        "language": "ko-KR",
        # 동기로 받는다 — 콜백으로 받으면 외부에 열린 엔드포인트가 하나 더 생기고
        # 그 자리를 지키는 일이 새로 생긴다. 클리닉은 하루 몇 건이라 기다려도 된다.
        "completion": "sync",
        # 조교와 학생이 갈리지 않으면 감독 근거가 안 된다. 둘뿐이라 범위를 못 박는다.
        "diarization": {"enable": True, "speakerCountMin": 1, "speakerCountMax": 2},
    }
    if terms:
        # 빈 배열을 보내면 업체가 요청 전체를 거절한다 — 있을 때만 싣는다.
        body["boostings"] = [{"words": t} for t in terms]

    status, raw = (transport or urllib_transport)(
        "POST",
        f"{invoke}/recognizer/url",
        json.dumps(body).encode(),
        {"X-CLOVASPEECH-API-KEY": secret, "Content-Type": "application/json"},
        TIMEOUT_SECONDS,
    )
    if status >= 300:
        detail = raw.decode(errors="replace")[:200]
        message = f"전사에 실패했습니다({status}): {detail}"
        if status in _RETRYABLE_STATUSES or status >= 500:
            raise TemporaryConferenceError(message)
        raise PermanentConferenceError(message)
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise PermanentConferenceError("전사 응답을 읽을 수 없습니다.") from exc

    lines = []
    for part in payload.get("segments") or []:
        said = (part.get("text") or "").strip()
        if not said:
            continue
        label = ((part.get("speaker") or {}).get("label") or "?").strip()
        lines.append(f"[{label}] {said}")
    return "\n".join(lines)
