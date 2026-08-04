"""Mux 서명 재생 어댑터 (key_considerations §4 — 업체 종속 로직은 앱 레이어).

**여기가 Mux 를 아는 유일한 서버 모듈이다.** 모델은 `provider` 값과 중립 참조
(`external_ref`)만 들고 있고, 업체를 교체하면 이 파일과 프런트 재생기만 바뀐다.

## 서명 재생이 무엇을 막나

Playback ID 의 정책이 `signed` 면 `https://stream.mux.com/{id}.m3u8` 이 403 이다.
재생하려면 **우리 서버가 개인키로 서명한 JWT** 를 토큰으로 붙여야 한다.
즉 재생 권한이 "링크를 아는가"에서 "우리 서버가 내줬는가"로 옮겨간다 —
링크가 유출돼도 토큰 만료 뒤에는 죽는다.

DRM 과는 층이 다르다. 서명은 **누가 스트림을 받아가는가**를 막고, DRM 은
**받아간 파일을 복호화·저장할 수 있는가**를 막는다. 워터마크는 그 둘을 다 통과한
**화면 녹화**를 추적한다. 셋이 서로 다른 구멍이다(playback.py 머리말 참조).

## 만료를 왜 영상 길이보다 길게 잡나

토큰이 재생 도중 만료되면 **그 시점부터 세그먼트 요청이 403** 이 되어 영상이
중간에 끊긴다(Mux 공식 권고: 현재 시각 + 영상 길이를 반드시 넘길 것).
그래서 `TOKEN_TTL` 은 가장 긴 강의(약 2시간)에 되감기·일시정지 여유를 얹은 값이다.
길게 잡아도 위험이 크지 않은 이유는 **권한 자체가 7일 만료**라 토큰을 다시 받는
경로가 이미 막혀 있기 때문이다 — 토큰은 그 안에서의 재생 세션 수명일 뿐이다.

## 키가 없으면 서명하지 않는다

`MUX_SIGNING_KEY_ID`·`MUX_SIGNING_PRIVATE_KEY` 가 비면 `None` 을 돌려준다.
개발·시드 환경은 `public` 정책이나 데모 영상으로 도는데, 여기서 예외를 던지면
키를 안 넣은 로컬에서 재생 화면 자체가 죽는다. **키가 없다 = 서명이 필요 없는
영상만 재생된다**는 뜻이고, 서명이 필요한 영상은 Mux 가 403 으로 막는다 —
우리가 앞질러 막을 필요가 없다.
"""
import base64
import binascii
import datetime

import jwt
from django.conf import settings

#: 토큰 수명 — 가장 긴 강의 + 되감기 여유(위 머리말 참조).
TOKEN_TTL = datetime.timedelta(hours=6)

#: Mux `aud` 값집합. 재생 화면이 실제로 부르는 것만 발급한다 —
#: 안 쓰는 대상(g=gif, d=DRM 라이선스)까지 서명해 내리면 쓰지도 않는 권한이 샌다.
AUDIENCE_VIDEO = "v"
AUDIENCE_THUMBNAIL = "t"
AUDIENCE_STORYBOARD = "s"


def _private_key():
    """설정의 base64 개인키를 PEM 바이트로 편다.

    Mux Signing Keys API 는 개인키를 **base64 로 감싸서** 준다. 대시보드에서
    복사하면 이미 풀린 PEM 인 경우도 있어 둘 다 받는다 — 붙여넣는 사람이
    형식을 판단하게 만들면 언젠가 틀린다.
    """
    raw = (getattr(settings, "MUX_SIGNING_PRIVATE_KEY", "") or "").strip()
    if not raw:
        return None
    if raw.startswith("-----BEGIN"):
        return raw.encode()
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        # 형식이 깨진 키 — 조용히 무서명으로 떨어지면 "왜 403 이지"로 헤맨다.
        raise ValueError(
            "MUX_SIGNING_PRIVATE_KEY 를 읽을 수 없습니다(base64 또는 PEM 이어야 합니다)."
        )


def is_configured():
    """서명 키가 갖춰졌는가 — 관리 화면 진단·테스트가 쓴다."""
    return bool(
        (getattr(settings, "MUX_SIGNING_KEY_ID", "") or "").strip()
        and (getattr(settings, "MUX_SIGNING_PRIVATE_KEY", "") or "").strip()
    )


def sign(playback_id, audience, now, ttl=TOKEN_TTL):
    """재생 토큰 1장. 키가 없으면 None(머리말의 "서명하지 않는다" 계약)."""
    key_id = (getattr(settings, "MUX_SIGNING_KEY_ID", "") or "").strip()
    key = _private_key()
    if not key_id or key is None or not playback_id:
        return None
    return jwt.encode(
        {
            "sub": playback_id,
            "aud": audience,
            "exp": int((now + ttl).timestamp()),
        },
        key,
        algorithm="RS256",
        headers={"kid": key_id},
    )


def playback_tokens(playback_id, now):
    """재생 화면이 필요한 토큰 묶음 — 없으면 빈 dict.

    프런트가 `<MuxPlayer tokens={...}>` 에 그대로 넘긴다. 키 이름은 Mux Player 의
    계약(`playback`·`thumbnail`·`storyboard`)이라 여기서 맞춰 둔다 — 프런트가
    다시 매핑하면 오탈자가 런타임까지 간다.
    """
    if not is_configured() or not playback_id:
        return {}
    return {
        "playback": sign(playback_id, AUDIENCE_VIDEO, now),
        "thumbnail": sign(playback_id, AUDIENCE_THUMBNAIL, now),
        "storyboard": sign(playback_id, AUDIENCE_STORYBOARD, now),
    }
