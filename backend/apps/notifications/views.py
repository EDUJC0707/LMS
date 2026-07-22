"""notifications 뷰 — 내 알림 내역 8차 슬라이스 (설계 도메인 8, PRD 3.1.2).

- GET /api/me/notifications — 로그인 사용자 알림 내역(최신순 페이지네이션)

**대상 3분기 매칭**: notifications 행은 student/parent/user 중 정확히 하나를
가리킨다(모델 clean 계약). 조회도 같은 축 — 학생 role 은 자신의 students 행,
학부모 role 은 parents 행, 직원 role 군은 users 행으로만 매칭한다. 역할 밖
분기·타인 행은 애초에 쿼리에 포함하지 않는다(닫힘이 기본값 —
key_considerations §5). 사람 행 미연결(role 만 학생/학부모) 예외 상태는
빈 목록으로 방어한다(/me 의 null 방어와 동일 방향).

정렬은 -notif_id(생성 역순) — sent_at 은 알림톡 채널 연동 전까지 NULL 이
다수라(발송 대기) 정렬 축으로 쓸 수 없고, PK 역순이 곧 최신순이다.
"""
from django.utils import timezone
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from apps.accounts.models import Parent, Student, User
from apps.accounts.permissions import STAFF_ROLES, IsParent, IsStaffRole, IsStudent

from .models import Notification


class MeNotificationsView(APIView):
    """GET /api/me/notifications — 내 알림 내역(3분기 매칭·페이지네이션)."""

    permission_classes = [IsStudent | IsParent | IsStaffRole]

    def get(self, request):
        queryset = self._my_notifications(request.user).order_by("-notif_id")
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response([self._item(n) for n in page])

    @staticmethod
    def _my_notifications(user):
        if user.role == User.Role.STUDENT:
            student = Student.objects.filter(user=user).first()
            if student is None:
                return Notification.objects.none()
            return Notification.objects.filter(student=student)
        if user.role == User.Role.PARENT:
            parent = Parent.objects.filter(user=user).first()
            if parent is None:
                return Notification.objects.none()
            return Notification.objects.filter(parent=parent)
        if user.role in STAFF_ROLES:
            return Notification.objects.filter(user=user)
        return Notification.objects.none()

    @staticmethod
    def _item(notification):
        return {
            "notif_id": notification.notif_id,
            "type": notification.type,
            "channel": notification.channel,
            "title": notification.title,
            "body": notification.body,
            "status": notification.status,
            "ref_type": notification.ref_type,
            "ref_id": notification.ref_id,
            "sent_at": (
                timezone.localtime(notification.sent_at).isoformat()
                if notification.sent_at
                else None
            ),
            "created_at": timezone.localtime(notification.created_at).isoformat(),
        }
