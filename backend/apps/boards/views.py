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

from . import board
from .models import Post

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
