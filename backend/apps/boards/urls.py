"""boards API 라우팅. config.urls 의 /api/boards/ 에 마운트된다.

카테고리 세그먼트는 모델 값집합(공지사항/질답/정오표/자유게시판/이벤트굿즈)
그대로 — 검증은 뷰(board.resolve_category)가 하고 밖의 값은 404.
"""
from django.urls import path

from . import views

app_name = "boards"

urlpatterns = [
    path("<str:category>", views.PostListView.as_view(), name="post-list"),
    path("<str:category>/<int:post_id>", views.PostDetailView.as_view(), name="post-detail"),
    path(
        "<str:category>/<int:post_id>/comments",
        views.CommentCreateView.as_view(),
        name="comment-create",
    ),
    path(
        "<str:category>/<int:post_id>/comments/<int:comment_id>",
        views.CommentDeleteView.as_view(),
        name="comment-delete",
    ),
]
