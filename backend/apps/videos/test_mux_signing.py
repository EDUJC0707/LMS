"""Mux 서명 재생 어댑터 테스트 (apps/videos/mux.py).

검증 축:
- **키가 없으면 서명하지 않는다** — 로컬·시드가 키 없이 돌아야 한다. 여기서
  예외를 던지면 키를 안 넣은 개발 환경에서 재생 화면이 통째로 죽는다.
- **서명 형태가 Mux 계약과 같다** — RS256 · 헤더 `kid` · 클레임 `sub`/`aud`/`exp`.
  하나만 틀려도 Mux 가 403 을 내는데, 그건 "권한 없음" 과 화면에서 구분되지 않는다.
- **대상(aud)별로 다른 토큰** — 영상 `v` · 썸네일 `t` · 스토리보드 `s`.
  한 토큰을 돌려쓰면 Mux 가 거절한다.
- **만료가 영상 길이보다 길다** — 재생 도중 만료되면 그 시점부터 세그먼트가
  403 이라 영상이 중간에 끊긴다(Mux 공식 권고).
- **개인키는 base64·PEM 둘 다 받는다** — 붙여넣는 사람이 형식을 판단하게 하면 틀린다.
- **재생 페이로드에 개인키가 새지 않는다** — 나가면 누구나 자기 토큰을 찍는다.
"""
import base64
import datetime

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from . import mux

PLAYBACK_ID = "oxfSIcgB5hF1OWCXYEfg8mH3Rmm01JStKGFzZosOmukA"
KEY_ID = "signing-key-id"
# **고정 시각으로 잡지 않는다.** 2026-08-04 14:00 을 박아 뒀더니 TTL 6시간이
# 지난 그날 저녁 20시부터 `jwt.decode` 가 `ExpiredSignatureError` 를 냈다 —
# 서명은 이 값으로 하는데 검증은 진짜 시계로 하기 때문이다. 하루 만에 저절로
# 빨개지는 테스트였다(2026-08-05 발견·수정).
# 여기서 확인하려는 것은 "언제"가 아니라 TTL 길이와 대상(aud) 분리라서
# 실제 시각으로 서명해도 뜻이 그대로다.
NOW = timezone.now()


def _keypair():
    """Mux Signing Keys API 가 주는 형태(base64 로 감싼 PKCS8 PEM)를 흉내낸다."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return key.public_key(), pem, base64.b64encode(pem).decode()


PUBLIC_KEY, PEM, B64 = _keypair()


def signed(**overrides):
    settings = {"MUX_SIGNING_KEY_ID": KEY_ID, "MUX_SIGNING_PRIVATE_KEY": B64}
    settings.update(overrides)
    return override_settings(**settings)


class MuxSigningKeyAbsentTests(SimpleTestCase):
    """키가 없을 때 — 죽지 않고 서명만 건너뛴다."""

    @override_settings(MUX_SIGNING_KEY_ID="", MUX_SIGNING_PRIVATE_KEY="")
    def test_not_configured_without_keys(self):
        self.assertFalse(mux.is_configured())

    @override_settings(MUX_SIGNING_KEY_ID="", MUX_SIGNING_PRIVATE_KEY="")
    def test_tokens_are_empty_without_keys(self):
        self.assertEqual(mux.playback_tokens(PLAYBACK_ID, NOW), {})

    @override_settings(MUX_SIGNING_KEY_ID="", MUX_SIGNING_PRIVATE_KEY="")
    def test_sign_returns_none_without_keys(self):
        self.assertIsNone(mux.sign(PLAYBACK_ID, mux.AUDIENCE_VIDEO, NOW))

    @override_settings(MUX_SIGNING_KEY_ID=KEY_ID, MUX_SIGNING_PRIVATE_KEY="")
    def test_key_id_alone_is_not_configured(self):
        """반쪽만 채운 설정은 미설정이다 — 서명 시도가 예외로 터지면 안 된다."""
        self.assertFalse(mux.is_configured())
        self.assertEqual(mux.playback_tokens(PLAYBACK_ID, NOW), {})


class MuxSigningTests(SimpleTestCase):
    """서명 형태가 Mux 계약과 같은가."""

    def test_configured_with_both_keys(self):
        with signed():
            self.assertTrue(mux.is_configured())

    def test_token_verifies_with_the_public_key(self):
        """실제로 검증되는 서명인가 — 형태만 맞고 서명이 깨져 있으면 Mux 가 403 이다."""
        with signed():
            token = mux.sign(PLAYBACK_ID, mux.AUDIENCE_VIDEO, NOW)
        claims = jwt.decode(
            token, PUBLIC_KEY, algorithms=["RS256"], audience=mux.AUDIENCE_VIDEO
        )
        self.assertEqual(claims["sub"], PLAYBACK_ID)

    def test_header_carries_key_id(self):
        """`kid` 가 없으면 Mux 는 어느 키로 검증할지 모른다."""
        with signed():
            token = mux.sign(PLAYBACK_ID, mux.AUDIENCE_VIDEO, NOW)
        header = jwt.get_unverified_header(token)
        self.assertEqual(header["kid"], KEY_ID)
        self.assertEqual(header["alg"], "RS256")

    def test_expiry_outlasts_a_long_lecture(self):
        """가장 긴 강의(2시간)를 넘겨야 재생 도중 끊기지 않는다."""
        with signed():
            token = mux.sign(PLAYBACK_ID, mux.AUDIENCE_VIDEO, NOW)
        claims = jwt.decode(
            token, PUBLIC_KEY, algorithms=["RS256"], audience=mux.AUDIENCE_VIDEO
        )
        lasted = datetime.timedelta(seconds=claims["exp"] - NOW.timestamp())
        self.assertGreater(lasted, datetime.timedelta(hours=2))

    def test_each_audience_gets_its_own_token(self):
        """영상·썸네일·스토리보드를 한 토큰으로 돌려쓰면 Mux 가 거절한다."""
        with signed():
            tokens = mux.playback_tokens(PLAYBACK_ID, NOW)
        self.assertEqual(set(tokens), {"playback", "thumbnail", "storyboard"})
        audiences = {
            name: jwt.decode(
                value, options={"verify_signature": False, "verify_aud": False}
            )["aud"]
            for name, value in tokens.items()
        }
        self.assertEqual(
            audiences,
            {
                "playback": mux.AUDIENCE_VIDEO,
                "thumbnail": mux.AUDIENCE_THUMBNAIL,
                "storyboard": mux.AUDIENCE_STORYBOARD,
            },
        )

    def test_drm_audience_is_not_issued(self):
        """안 쓰는 대상까지 서명해 내리면 쓰지도 않는 권한이 샌다."""
        with signed():
            tokens = mux.playback_tokens(PLAYBACK_ID, NOW)
        issued = {
            jwt.decode(v, options={"verify_signature": False, "verify_aud": False})["aud"]
            for v in tokens.values()
        }
        self.assertNotIn("d", issued)
        self.assertNotIn("g", issued)

    def test_accepts_raw_pem_as_well_as_base64(self):
        """붙여넣는 사람이 형식을 판단하게 만들면 언젠가 틀린다."""
        with signed(MUX_SIGNING_PRIVATE_KEY=PEM.decode()):
            self.assertIsNotNone(mux.sign(PLAYBACK_ID, mux.AUDIENCE_VIDEO, NOW))

    def test_broken_key_raises_instead_of_silently_skipping(self):
        """조용히 무서명으로 떨어지면 '왜 403 이지'로 헤맨다."""
        with signed(MUX_SIGNING_PRIVATE_KEY="!!not-base64!!"):
            with self.assertRaises(ValueError):
                mux.sign(PLAYBACK_ID, mux.AUDIENCE_VIDEO, NOW)

    def test_no_token_without_a_playback_id(self):
        """연동 전 영상은 external_ref 가 비어 있다 — 빈 sub 로 서명하지 않는다."""
        with signed():
            self.assertEqual(mux.playback_tokens(None, NOW), {})
            self.assertEqual(mux.playback_tokens("", NOW), {})

    def test_private_key_never_appears_in_a_token(self):
        """개인키가 나가면 누구나 자기 토큰을 찍는다."""
        with signed():
            tokens = mux.playback_tokens(PLAYBACK_ID, NOW)
        secret = B64[:40]
        for value in tokens.values():
            self.assertNotIn(secret, value)
