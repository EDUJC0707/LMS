"""accounts 시리얼라이저 — 인증 입력 검증 + 사용자 요약 응답.

응답에는 개인정보 최소 원칙을 적용한다 — 연락처(phone) 등 화면 조립에
불필요한 필드는 싣지 않는다.
"""
from django.contrib.auth import password_validation
from rest_framework import serializers


class LoginSerializer(serializers.Serializer):
    """로그인 입력 — login_id·password. 검증 실패는 400."""

    login_id = serializers.CharField(max_length=50)
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class PasswordChangeSerializer(serializers.Serializer):
    """비밀번호 변경 입력 — 현재 비밀번호 검증 + 새 비밀번호 정책 검사.

    context 로 user 를 받아 현재 비밀번호 대조와
    AUTH_PASSWORD_VALIDATORS(유사성 검사 포함)를 적용한다.
    """

    current_password = serializers.CharField(write_only=True, trim_whitespace=False)
    new_password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_current_password(self, value):
        if not self.context["user"].check_password(value):
            raise serializers.ValidationError("현재 비밀번호가 올바르지 않습니다.")
        return value

    def validate_new_password(self, value):
        password_validation.validate_password(value, user=self.context["user"])
        return value


def user_summary(user) -> dict:
    """로그인·/me 공통 사용자 요약 — 역할·이름·비밀번호 변경 필요 여부."""
    return {
        "user_id": user.user_id,
        "name": user.name,
        "role": user.role,
        "must_change_password": user.must_change_password,
    }
