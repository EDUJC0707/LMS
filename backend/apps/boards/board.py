"""게시판 공용 서비스 — 열람 규칙·작성 권한 매트릭스·페이로드 조립 (PRD 3.3.1·3.3.2·§4).

뷰(views)는 역할 게이트·입력 형태 검증·상태 코드 매핑만 하고, 규칙 강제와
응답 조립은 전부 여기가 담당한다(2차 home·4차 booking 선례).

## 비밀글 은닉 정책 (§4 — 2026-07-22 구현 판단)

질답 비밀글은 **목록에 포함하되 마스킹**한다(제외 아님):
- 제목은 "비밀글입니다"로 대체, 작성자명은 미노출(None) — 제목·본문·작성자가
  모두 가려지므로 유출되는 정보는 "비밀 문의 1건 존재"뿐(정찰 가치 없음).
- 제외 방식은 본인 글 추적 동선(질답=문의 통합 단일 창구 — 8-11)이 끊기고
  사용자별로 목록·페이지가 달라진다. 마스킹은 학원가 Q&A 관례(자물쇠)와
  일치해 이용자 학습 비용도 없다.
- 원제목·작성자는 **작성자 본인·직원에게만**. 상세는 타인에게 404 —
  미존재와 구분 불가(존재 비노출, §4).

## 작성 권한 매트릭스 (PRD 3.3.1)

| 카테고리 | 작성 |
|---|---|
| 공지사항·정오표·이벤트굿즈 | 직원 — 기능 키 `공지작성`(대표 전권 포함) |
| 질답 | 학생·학부모 (is_secret 선택 가능 — 질답 전용) |
| 자유게시판 | 대표만 (강사 트위터형 피드 — PRD 3.3.1) |

## 삭제 정책 — 하드 삭제 (2026-07-22 구현 판단)

- 모델에 삭제 표식 컬럼(is_deleted/deleted_at)이 없고 이번 슬라이스는 스키마
  무변경이다. is_published 는 게시 제어 전용이라 삭제로 오버로드하면
  "미게시 글"과 "삭제 글"이 구분 불가.
- PostComment 가 글 삭제 시 CASCADE("글 삭제 시 답글도 삭제" — 모델 설계
  주석)로 이미 하드 삭제를 전제한다.
- 삭제는 본인 글(또는 직원 운영 삭제 — `공지작성` 키)의 수동 조작만
  허용하므로 key_considerations §5(파괴적 작업 수동)와 충돌하지 않는다.

댓글 작성 규칙: **그 글을 열람할 수 있는 로그인 사용자**로 단일화 — 이벤트
게시판 학생 굿즈 요청(PRD 3.3.1), 비밀글 1:1 대화(작성자·직원만), 질답 후속
문의를 한 규칙으로 커버한다. 비밀글 댓글은 글과 같은 은닉 규칙(모델 계약).
"""
from django.db.models import Count
from django.utils import timezone

from apps.accounts.features import FeatureKey, effective_features
from apps.accounts.models import User
from apps.accounts.permissions import STAFF_ROLES

from .models import Post

MASKED_TITLE = "비밀글입니다"

# 질답만 학생·학부모 작성 — 나머지 소비자 작성 카테고리는 없다(PRD 3.3.1)
_CONSUMER_WRITE_ROLES = frozenset({User.Role.STUDENT, User.Role.PARENT})
# 직원(공지작성 키) 작성 카테고리
_STAFF_WRITE_CATEGORIES = frozenset(
    {Post.Category.NOTICE, Post.Category.ERRATA, Post.Category.EVENT_GOODS}
)


def resolve_category(raw):
    """URL 카테고리 세그먼트 → 모델 값(모델 값집합 기준). 밖의 값은 None(뷰가 404)."""
    return raw if raw in Post.Category.values else None


def is_staff_viewer(user):
    """직원 역할군(대표·관리자·조교) — 비밀글·미게시 글 전체 열람."""
    return user.role in STAFF_ROLES


def can_view(post, user):
    """상세 열람 가능 여부 — 비밀글은 작성자·직원만, 미게시는 직원만(§4 닫힘)."""
    if is_staff_viewer(user):
        return True
    if not post.is_published:
        return False
    return not post.is_secret or post.author_id == user.pk


def can_write(category, user):
    """작성 권한 매트릭스(PRD 3.3.1) — 모듈 docstring 표 참조."""
    if category == Post.Category.FREE:
        return user.role == User.Role.OWNER  # 대표만 — 강사 트위터형
    if category == Post.Category.QNA:
        return user.role in _CONSUMER_WRITE_ROLES
    if category in _STAFF_WRITE_CATEGORIES:
        return FeatureKey.NOTICE_WRITE in effective_features(user)
    return False


def can_moderate(user):
    """직원 운영 삭제(타인 글·댓글) — 기능 키 `공지작성` 보유(대표 전권 포함)."""
    return FeatureKey.NOTICE_WRITE in effective_features(user)


def can_edit(post, user):
    """수정은 본인 글만 — 직원 운영 권한은 삭제에 한정(내용 변조 방지)."""
    return post.author_id == user.pk


def can_delete(post, user):
    """삭제는 본인 글 + 직원 운영 삭제(공지작성 키). 하드 삭제 — 모듈 docstring."""
    return post.author_id == user.pk or can_moderate(user)


def can_delete_comment(comment, user):
    """댓글 삭제는 본인 것 + 직원 운영 삭제(공지작성 키)."""
    return comment.author_id == user.pk or can_moderate(user)


def update_post(post, fields):
    """본인 글 수정 — updated_at 은 앱 레이어에서 갱신(값 존재 = 수정된 글,
    모델 계약: auto_now 없이 grades.Attendance 선례)."""
    for name, value in fields.items():
        setattr(post, name, value)
    post.updated_at = timezone.now()
    post.save(update_fields=[*fields, "updated_at"])
    return post


def create_comment(post, user, body):
    """댓글 생성 — 열람 가능 검사(can_view)는 호출측 통과 전제(모듈 docstring 규칙)."""
    return post.comments.create(author=user, body=body)


def create_post(category, user, fields):
    """글 생성 — 권한(can_write)·입력 검증은 호출측 통과 전제.

    course_week 는 받지 않는다 — 주차공지 연동은 조회 필드로만 노출(과제 계약).
    """
    return Post.objects.create(
        category=category,
        title=fields["title"],
        body=fields["body"],
        is_secret=fields.get("is_secret", False),
        author=user,
    )


def list_queryset(category, user):
    """목록 쿼리 — 최신순. 미게시는 직원만, 비밀글은 포함(마스킹은 직렬화에서)."""
    queryset = Post.objects.filter(category=category)
    if not is_staff_viewer(user):
        queryset = queryset.filter(is_published=True)
    return (
        queryset.select_related("author", "course_week__course")
        .annotate(comment_count=Count("comments"))
        .order_by("-created_at", "-post_id")
    )


def list_item(post, user):
    """목록 행 — 본문 미포함. 비밀글은 타인에게 제목·작성자 마스킹(모듈 docstring)."""
    masked = post.is_secret and not (is_staff_viewer(user) or post.author_id == user.pk)
    return {
        "post_id": post.post_id,
        "title": MASKED_TITLE if masked else post.title,
        "author_name": None if masked else post.author.name,
        "is_secret": post.is_secret,
        "is_published": post.is_published,
        "comment_count": post.comment_count,
        "course_week": _course_week_block(post.course_week),
        "created_at": _iso(post.created_at),
        "updated_at": _iso(post.updated_at),
        "is_mine": post.author_id == user.pk,
    }


def detail_payload(post, user, comments):
    """상세 응답 — 열람 가능 전제(can_view 통과 후 호출). 댓글 포함."""
    return {
        "post_id": post.post_id,
        "category": post.category,
        "title": post.title,
        "body": post.body,
        "author_name": post.author.name,
        "is_secret": post.is_secret,
        "is_published": post.is_published,
        "course_week": _course_week_block(post.course_week),
        "created_at": _iso(post.created_at),
        "updated_at": _iso(post.updated_at),
        "is_mine": post.author_id == user.pk,
        "comments": [comment_block(c, user) for c in comments],
    }


def comment_block(comment, user):
    """댓글 블록 — author_role 로 강사/관리자 답변 구분(질답 답변 배지용)."""
    return {
        "comment_id": comment.comment_id,
        "author_name": comment.author.name,
        "author_role": comment.author.role,
        "body": comment.body,
        "created_at": _iso(comment.created_at),
        "is_mine": comment.author_id == user.pk,
    }


def _course_week_block(course_week):
    """주차공지 연동(3.2.0) — 조회 필드로만 노출. 주차 제목·날짜는 내리지 않는다
    (미공개 주차 정보 유출 방지 — 공개 판정은 홈 API released() 담당)."""
    if course_week is None:
        return None
    return {
        "week_id": course_week.week_id,
        "week_no": course_week.week_no,
        "course_name": course_week.course.name,
    }


def _iso(value):
    return timezone.localtime(value).isoformat() if value else None
