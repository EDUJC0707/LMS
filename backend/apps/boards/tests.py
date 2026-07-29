"""boards 스모크 테스트 — 도메인 7(게시판·상담) 핵심 계약 검증.

설계 근거: docs/db/lms-db-design-2026-07-15.md 도메인 7(+헤더 노트 ③ 질답↔문의
통합), baseline lms-db-spec.html Domain 6, PRD 3.3.1(게시판)·3.3.2(문의 통합)·
3.1.9/3.4(상담). 질답 공개 방식은 2026-07-22 결정(기본 공개 + 비밀글 옵션).
"""

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Parent, Student, User

from . import models as boards_models
from .models import AbsenceCounseling, ParentCounselRequest, Post, PostComment


def make_admin(login_id="01099998888"):
    return User.objects.create_user(login_id, role=User.Role.ADMIN, name="관리자")


def make_post(**kwargs):
    kwargs.setdefault("category", Post.Category.NOTICE)
    kwargs.setdefault("title", "공지")
    kwargs.setdefault("body", "본문")
    if "author" not in kwargs:
        kwargs["author"] = make_admin()
    return Post.objects.create(**kwargs)


class PostTests(TestCase):
    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(Post._meta.db_table, "posts")
        self.assertEqual(Post._meta.pk.column, "post_id")

    def test_category_value_set_follows_design(self):
        # 설계 delta: 공지사항/정오표 + 질답/자유게시판/이벤트굿즈 확장
        self.assertEqual(
            set(Post.Category.values),
            {"공지사항", "정오표", "질답", "자유게시판", "이벤트굿즈"},
        )

    def test_defaults_follow_design(self):
        # baseline: is_published NN 기본 true, updated_at NULL(정정 추적),
        # course_week NULL(주차공지만 연결)
        post = make_post()
        self.assertTrue(post.is_published)
        self.assertIsNone(post.updated_at)
        self.assertIsNone(post.course_week)

    def test_secret_option_defaults_to_public(self):
        # 2026-07-22 결정(PRD 3.3.1): 질답은 **기본 공개** + 작성 시 비밀글 옵션.
        # 기본값 false = 공개(옵트인 비밀글).
        post = make_post(category=Post.Category.QNA, title="질문", body="모르겠어요")
        self.assertFalse(post.is_secret)

    def test_secret_visibility_contract_documented(self):
        # 비밀글은 작성자·관리자만 열람(결제 등 개인적 문의용) — 강제는 API
        # 레벨(RBAC). 계약이 docstring 에 명시되어야 한다.
        doc = Post.__doc__
        self.assertIn("비밀글", doc)
        self.assertIn("작성자", doc)

    def test_inquiry_tables_not_modeled(self):
        # 헤더 노트 ③(질답↔문의 일단 통합) + PRD 8-11: 1:1 문의는 질답 게시판
        # 비밀글로 흡수 — 그린필드 최종 상태에서 inquiries/inquiry_messages 를
        # 만들지 않는다(분리 여지는 유지 — 확정 시 신설).
        self.assertFalse(hasattr(boards_models, "Inquiry"))
        self.assertFalse(hasattr(boards_models, "InquiryMessage"))


class PostCommentTests(TestCase):
    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(PostComment._meta.db_table, "post_comments")
        self.assertEqual(PostComment._meta.pk.column, "comment_id")

    def test_comment_belongs_to_post(self):
        # 질답 답변(강사/관리자)·자유/이벤트 댓글 공용. 글 삭제 시 답글도 삭제.
        post = make_post(category=Post.Category.QNA)
        comment = PostComment.objects.create(post=post, author=post.author, body="답변")
        self.assertEqual(post.comments.get(), comment)
        post.delete()
        self.assertFalse(PostComment.objects.filter(pk=comment.pk).exists())


class AbsenceCounselingTests(TestCase):
    def setUp(self):
        self.student = Student.objects.create(unique_id="3_1234")

    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(AbsenceCounseling._meta.db_table, "absence_counselings")
        self.assertEqual(AbsenceCounseling._meta.pk.column, "counsel_id")

    def test_target_value_set_follows_design(self):
        # 설계: 학부모(1차)/학생(2차) 순차 통화
        self.assertEqual(set(AbsenceCounseling.Target.values), {"학부모", "학생"})

    def test_status_value_set_and_defaults(self):
        # 설계: 대기/완료/미연결, 기본 대기. makeup_requested 기본 false,
        # attendance(결석 회차) NULL 허용
        counseling = AbsenceCounseling.objects.create(
            student=self.student, target=AbsenceCounseling.Target.PARENT
        )
        self.assertEqual(set(AbsenceCounseling.Status.values), {"대기", "완료", "미연결"})
        self.assertEqual(counseling.status, AbsenceCounseling.Status.PENDING)
        self.assertFalse(counseling.makeup_requested)
        self.assertIsNone(counseling.attendance)

    def test_makeup_chain_contract_documented(self):
        # 결석 → 전화상담 → 동보 체크(makeup_requested) → makeup_grants 연계
        # 체인이 docstring 에 명시되어야 한다(videos 도메인 소비 지점의 준거).
        self.assertIn("makeup_grants", AbsenceCounseling.__doc__)


class ParentCounselRequestTests(TestCase):
    def setUp(self):
        self.parent = Parent.objects.create(phone="01012345678")

    def test_table_and_pk_column_follow_design(self):
        self.assertEqual(ParentCounselRequest._meta.db_table, "parent_counsel_requests")
        self.assertEqual(ParentCounselRequest._meta.pk.column, "request_id")

    def test_status_value_set_and_defaults(self):
        # 설계: 접수/진행/완료, 기본 접수. 자녀(student)·처리자는 NULL 허용
        req = ParentCounselRequest.objects.create(
            parent=self.parent, request_content="아이 성적 상담 원합니다"
        )
        self.assertEqual(set(ParentCounselRequest.Status.values), {"접수", "진행", "완료"})
        self.assertEqual(req.status, ParentCounselRequest.Status.RECEIVED)
        self.assertIsNone(req.student)
        self.assertIsNone(req.handled_by)
        self.assertIsNone(req.handled_at)
        self.assertIsNotNone(req.requested_at)

    def test_requested_at_is_creation_timestamp(self):
        req = ParentCounselRequest.objects.create(
            parent=self.parent, request_content="상담 신청"
        )
        # 양쪽 다 Asia/Seoul 로 맞춘다 — auto_now_add 는 UTC 로 저장되므로
        # `.date()` 와 `date.today()` 를 비교하면 새벽 0~9시에 하루가 어긋난다
        # (2026-07-30 00:0x 에 실제로 깨졌다).
        self.assertEqual(timezone.localdate(req.requested_at), timezone.localdate())
