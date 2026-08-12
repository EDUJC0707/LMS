"""boards 뷰 — 게시판 API 6차 슬라이스 (PRD 3.3.1·3.3.2·§4).

- GET    /api/boards/{category}                     목록(페이지네이션·최신순)
- POST   /api/boards/{category}                     작성(카테고리별 권한 매트릭스)
- GET    /api/boards/{category}/{post_id}           상세(+댓글)
- PATCH  /api/boards/{category}/{post_id}           수정(본인 글만)
- DELETE /api/boards/{category}/{post_id}           삭제(본인 + 직원 운영 삭제)
- POST   /api/boards/{category}/{post_id}/comments  댓글 작성(열람 가능한 글에만)
- DELETE /api/boards/{category}/{post_id}/comments/{comment_id}  댓글 삭제

규칙 강제·페이로드 조립은 board 서비스가 담당한다 — 뷰는 로그인 게이트·
카테고리/입력 검증·대상 조회(열람 불가는 404 존재 비노출)·상태 코드 매핑만
한다(2차 home·4차 booking 선례). 열람은 학생·학부모·직원 전 역할 허용
(PRD 3.3.1 "학생·학부모 모두 열람") — 비로그인 공개(3.3.3 ①)는 미확정이라 제외.
"""
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.features import FeatureKey
from apps.accounts.permissions import FeatureRequired

from . import board, channeltalk, counseling
from .models import AbsenceCounseling, Post

_NOT_FOUND_MESSAGE = "찾을 수 없습니다."
# 자격 없음 — 기능 존재를 특정하지 않는 단일 메시지(accounts.permissions 와 동일)
_DENIED_MESSAGE = "접근 권한이 없습니다."


def _not_found():
    return Response({"detail": _NOT_FOUND_MESSAGE}, status=status.HTTP_404_NOT_FOUND)


def _denied():
    return Response({"detail": _DENIED_MESSAGE}, status=status.HTTP_403_FORBIDDEN)


def _bad_request(message):
    return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)


def _parse_post_input(data, category, partial=False):
    """작성/수정 입력의 형태 검증 — (인정 필드 dict, 오류 메시지).

    인정 필드는 title·body·is_secret 뿐 — course_week 등 나머지는 무시
    (주차공지 연동은 조회 전용). is_secret 은 질답(문의 통합 창구) 전용.
    """
    fields = {}
    if "title" in data or not partial:
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            return None, "title이 필요합니다."
        if len(title.strip()) > 200:
            return None, "title은 200자 이내입니다."
        fields["title"] = title.strip()
    if "body" in data or not partial:
        body = data.get("body")
        if not isinstance(body, str) or not body.strip():
            return None, "body가 필요합니다."
        fields["body"] = body
    if "is_secret" in data:
        is_secret = data["is_secret"]
        if not isinstance(is_secret, bool):
            return None, "is_secret은 true/false 입니다."
        if is_secret and category != Post.Category.QNA:
            return None, "비밀글은 질답 게시판에서만 설정할 수 있습니다."
        fields["is_secret"] = is_secret
    if partial and not fields:
        return None, "수정할 내용이 없습니다."
    return fields, None


def _load_post(category, post_id, user):
    """카테고리 경계 안에서 글 로드 — 미존재·열람 불가 모두 None(404 단일화)."""
    post = (
        Post.objects.select_related("author", "course_week__course")
        .filter(pk=post_id, category=category)
        .first()
    )
    if post is None or not board.can_view(post, user):
        return None
    return post


def _comments(post):
    """상세·수정 응답 공용 — 댓글 오래된 순(대화 흐름) 로드."""
    return list(post.comments.select_related("author").order_by("created_at", "comment_id"))


class PostListView(APIView):
    """GET /api/boards/{category} — 목록. 비밀글은 마스킹 포함(board 서비스 판단)."""

    permission_classes = [IsAuthenticated]

    def get(self, request, category):
        category = board.resolve_category(category)
        if category is None:
            return _not_found()
        queryset = board.list_queryset(category, request.user)
        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(
            [board.list_item(post, request.user) for post in page]
        )

    def post(self, request, category):
        """POST /api/boards/{category} — 작성 권한 매트릭스는 board.can_write."""
        category = board.resolve_category(category)
        if category is None:
            return _not_found()
        if not board.can_write(category, request.user):
            return _denied()
        data = request.data if isinstance(request.data, dict) else {}
        fields, error = _parse_post_input(data, category)
        if error:
            return _bad_request(error)
        post = board.create_post(category, request.user, fields)
        return Response(
            board.detail_payload(post, request.user, comments=[]),
            status=status.HTTP_201_CREATED,
        )


class PostDetailView(APIView):
    """GET /api/boards/{category}/{post_id} — 상세(+댓글).

    비밀글은 작성자·직원만 — 타인은 미존재와 같은 404(존재 비노출, §4).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, category, post_id):
        category = board.resolve_category(category)
        if category is None:
            return _not_found()
        post = _load_post(category, post_id, request.user)
        if post is None:
            return _not_found()
        return Response(board.detail_payload(post, request.user, _comments(post)))

    def patch(self, request, category, post_id):
        """PATCH — 본인 글만(직원 운영 권한은 삭제에 한정). 응답은 상세와 동형."""
        category = board.resolve_category(category)
        if category is None:
            return _not_found()
        post = _load_post(category, post_id, request.user)
        if post is None:
            return _not_found()
        if not board.can_edit(post, request.user):
            return _denied()
        data = request.data if isinstance(request.data, dict) else {}
        fields, error = _parse_post_input(data, category, partial=True)
        if error:
            return _bad_request(error)
        board.update_post(post, fields)
        return Response(board.detail_payload(post, request.user, _comments(post)))

    def delete(self, request, category, post_id):
        """DELETE — 본인 글 + 직원 운영 삭제(공지작성 키). 하드 삭제(board 판단)."""
        category = board.resolve_category(category)
        if category is None:
            return _not_found()
        post = _load_post(category, post_id, request.user)
        if post is None:
            return _not_found()
        if not board.can_delete(post, request.user):
            return _denied()
        post.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CommentCreateView(APIView):
    """POST /api/boards/{category}/{post_id}/comments — 열람 가능한 글에만.

    열람 가능 = 댓글 가능(board 서비스 규칙) — 이벤트 학생 굿즈 요청·비밀글
    1:1 대화(작성자·직원)·질답 후속 문의를 한 규칙으로 커버. 열람 불가 글은
    404(존재 비노출).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, category, post_id):
        category = board.resolve_category(category)
        if category is None:
            return _not_found()
        post = _load_post(category, post_id, request.user)
        if post is None:
            return _not_found()
        data = request.data if isinstance(request.data, dict) else {}
        body = data.get("body")
        if not isinstance(body, str) or not body.strip():
            return _bad_request("body가 필요합니다.")
        comment = board.create_comment(post, request.user, body)
        return Response(
            board.comment_block(comment, request.user), status=status.HTTP_201_CREATED
        )


class CommentDeleteView(APIView):
    """DELETE /api/boards/{category}/{post_id}/comments/{comment_id} —
    본인 댓글 + 직원 운영 삭제(공지작성 키). 글이 은닉 대상이면 404."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, category, post_id, comment_id):
        category = board.resolve_category(category)
        if category is None:
            return _not_found()
        post = _load_post(category, post_id, request.user)
        if post is None:
            return _not_found()
        comment = post.comments.filter(pk=comment_id).first()
        if comment is None:
            return _not_found()
        if not board.can_delete_comment(comment, request.user):
            return _denied()
        comment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- 결석 상담(8차) — counseling_urls.py 마운트 ---------------------------


class CounselingQueueView(APIView):
    """GET /api/admin/counseling/queue — 결석 상담 대기열 (상담기록).

    출결 트리거(3차)가 만든 대기 카드 + 시도 횟수 표시(counseling 서비스의
    행=시도 이력 계약). 상담 기록은 관리자 전용(PRD 3.1.9) — 기능 키 게이트.
    """

    permission_classes = [FeatureRequired(FeatureKey.COUNSEL_RECORD)]

    def get(self, request):
        return Response({"queue": counseling.queue_rows()})


class CounselingRecordView(APIView):
    """PATCH /api/admin/counseling/{counsel_id} — 통화 결과 기록 (상담기록)."""

    permission_classes = [FeatureRequired(FeatureKey.COUNSEL_RECORD)]

    def patch(self, request, counsel_id):
        card = (
            AbsenceCounseling.objects.select_related("student__user", "attendance")
            .filter(pk=counsel_id)
            .first()
        )
        if card is None:
            return _not_found()
        body = request.data if isinstance(request.data, dict) else {}
        result = body.get("result")
        # 결과 없이 횟수만 저장할 수 있다 — 조교가 아직 거는 중인 상태다.
        if result is not None and result not in ("연결", "미연결", "종결"):
            return _bad_request("result는 연결·미연결·종결 중 하나여야 합니다.")
        if "makeup_requested" in body and not isinstance(body["makeup_requested"], bool):
            return _bad_request("makeup_requested는 true/false여야 합니다.")
        for name in ("absence_reason", "call_memo", "follow_up_action", "provider_ref"):
            if name in body and not isinstance(body[name], str):
                return _bad_request(f"{name}은 문자열이어야 합니다.")
        try:
            card, attempts, next_card, closed = counseling.record_call(
                card, result, body, request.user
            )
        except counseling.CounselingError as error:
            return _bad_request(error.message)
        return Response(
            {
                "counsel_id": card.counsel_id,
                "status": card.status,
                "attempts": attempts,
                "next_counsel_id": next_card.counsel_id if next_card else None,
                "closed": closed,
                "makeup_requested": card.makeup_requested,
            }
        )


class CounselingOpenView(APIView):
    """POST /api/admin/counseling — 통화 카드를 연다 (학생 2차, 8-18)."""

    permission_classes = [FeatureRequired(FeatureKey.COUNSEL_RECORD)]

    def post(self, request):
        body = request.data if isinstance(request.data, dict) else {}
        target = body.get("target")
        if target not in AbsenceCounseling.Target.values:
            return _bad_request("target은 학부모 또는 학생이어야 합니다.")
        # 같은 결석의 다른 대상으로 연다 — 화면이 이미 들고 있는 카드를 기준점으로
        # 삼으면 결석 회차 id 를 응답에 실어 내보내지 않아도 된다.
        source = AbsenceCounseling.objects.filter(pk=body.get("from_counsel_id")).first()
        if source is None:
            return _bad_request("기준 상담 카드를 찾을 수 없습니다.")
        try:
            card = counseling.open_card(source.student, source.attendance, target)
        except counseling.CounselingError as error:
            return _bad_request(error.message)
        return Response(
            {"counsel_id": card.counsel_id, "target": card.target, "status": card.status},
            status=201,
        )


class CounselingCallsView(APIView):
    """GET /api/admin/counseling/{counsel_id}/calls — 이 카드로 건 최근 통화.

    화면이 `안 받음/통화함` 버튼을 미리 채우는 재료다. **번호는 응답에 싣지
    않는다** — 서버가 카드에서 꺼내 조회하고 결과만 준다(명부 API 와 같은 이유:
    응답으로 연락처를 역추적할 수 있으면 안 된다).
    """

    permission_classes = [FeatureRequired(FeatureKey.COUNSEL_RECORD)]

    def get(self, request, counsel_id):
        card = (
            AbsenceCounseling.objects.select_related("student__user")
            .filter(pk=counsel_id)
            .first()
        )
        if card is None:
            return _not_found()
        return Response({"calls": channeltalk.recent_calls(counseling.phone_for(card))})


class CounselingTranscriptView(APIView):
    """GET /api/admin/counseling/{counsel_id}/transcript — 전사 + 녹음 링크.

    **자동으로 메모를 채우지 않는다** — 조교가 읽고 확정한다(2026-08-12).
    녹음 링크는 만료되는 서명 URL 이라 저장하지 않고 볼 때마다 새로 받는다.
    """

    permission_classes = [FeatureRequired(FeatureKey.COUNSEL_RECORD)]

    def get(self, request, counsel_id):
        card = AbsenceCounseling.objects.filter(pk=counsel_id).first()
        if card is None:
            return _not_found()
        if not card.provider_ref:
            return Response({"transcript": "", "recording_url": None})
        return Response(
            {
                # 전사는 저장분을 쓴다 — 채널톡은 90일까지만 되돌려 준다.
                "transcript": card.call_transcript,
                # 녹음은 매번 새로 받는다 — 서명 URL 이라 저장하면 죽는다.
                "recording_url": channeltalk.recording_url(card.provider_ref),
            }
        )


class CounselingNotifyView(APIView):
    """POST /api/admin/counseling/{counsel_id}/notify — 결석 안내 발송 (버튼)."""

    permission_classes = [FeatureRequired(FeatureKey.COUNSEL_RECORD)]

    def post(self, request, counsel_id):
        card = AbsenceCounseling.objects.filter(pk=counsel_id).first()
        if card is None:
            return _not_found()
        try:
            sent = counseling.notify(card)
        except counseling.CounselingError as error:
            return _bad_request(error.message)
        return Response({"counsel_id": card.counsel_id, "sent": sent})
