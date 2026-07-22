"""게시판 API 6차 슬라이스 테스트 (PRD 3.3.1·3.3.2·§4).

검증 축:
- 카테고리별 작성 권한 매트릭스(PRD 3.3.1) 전수 — 공지/정오표/이벤트=직원(공지작성 키),
  질답=학생·학부모, 자유게시판=대표만
- 비밀글 은닉(§4): 목록 마스킹·상세 404(존재 비노출)·댓글 동일 규칙
- 본인/타인 수정·삭제 경계(직원 운영 삭제는 공지작성 키)
- 쿼리 효율: assertNumQueries 로 쿼리 수 고정(N+1 회귀 방지)
"""
import json

from django.test import TestCase

from apps.accounts.features import FeatureKey
from apps.accounts.models import StaffFeatureGrant, User
from apps.curriculum.models import Course, CourseWeek

from .models import Post, PostComment

BOARDS = "/api/boards"
MASKED_TITLE = "비밀글입니다"


def board_url(category, *parts):
    return "/".join([BOARDS, category, *map(str, parts)])


def make_user(login_id, role, name="사용자"):
    return User.objects.create_user(login_id=login_id, role=role, name=name)


class BoardFixtureMixin:
    """역할 전 스펙트럼(대표·관리자·조교·학생2·학부모) 계정 픽스처."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("own-board", User.Role.OWNER, name="한종철")
        cls.admin = make_user("adm-board", User.Role.ADMIN, name="관리자")
        cls.assistant = make_user("ast-board", User.Role.ASSISTANT, name="조교")
        cls.student = make_user("stu-board", User.Role.STUDENT, name="김서연")
        cls.student2 = make_user("stu2-board", User.Role.STUDENT, name="박지훈")
        cls.parent = make_user("par-board", User.Role.PARENT, name="김학부모")

    def login(self, user):
        self.client.force_login(user)

    def post_json(self, url, body):
        return self.client.post(url, data=json.dumps(body), content_type="application/json")

    def patch_json(self, url, body):
        return self.client.patch(url, data=json.dumps(body), content_type="application/json")

    def create_post(self, category, **body):
        body.setdefault("title", "제목")
        body.setdefault("body", "본문")
        return self.post_json(board_url(category), body)


# ---------------------------------------------------------------------------
# 목록 GET /api/boards/{category}
# ---------------------------------------------------------------------------


class PostListTests(BoardFixtureMixin, TestCase):
    def test_login_required(self):
        # 비로그인 랜딩 공개(3.3.3 ①)는 미확정이라 제외 — 로그인 필수
        res = self.client.get(board_url("공지사항"))
        self.assertEqual(res.status_code, 403)

    def test_unknown_category_is_404(self):
        self.login(self.student)
        self.assertEqual(self.client.get(board_url("없는게시판")).status_code, 404)

    def test_lists_newest_first_with_pagination(self):
        posts = [
            Post.objects.create(
                category=Post.Category.NOTICE, title=f"공지{i}", body="본문", author=self.admin
            )
            for i in range(25)
        ]
        self.login(self.student)
        res = self.client.get(board_url("공지사항"))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["count"], 25)
        self.assertEqual(len(data["results"]), 20)  # 전역 PAGE_SIZE
        self.assertEqual(data["results"][0]["post_id"], posts[-1].post_id)  # 최신순
        first = data["results"][0]
        self.assertEqual(first["title"], "공지24")
        self.assertEqual(first["author_name"], "관리자")
        self.assertFalse(first["is_secret"])
        self.assertEqual(first["comment_count"], 0)
        self.assertIsNone(first["course_week"])
        self.assertNotIn("body", first)  # 목록엔 본문 미포함
        page2 = self.client.get(board_url("공지사항") + "?page=2").json()
        self.assertEqual(len(page2["results"]), 5)

    def test_categories_are_isolated(self):
        Post.objects.create(
            category=Post.Category.QNA, title="질문", body="본문", author=self.student
        )
        self.login(self.student)
        self.assertEqual(self.client.get(board_url("공지사항")).json()["count"], 0)
        self.assertEqual(self.client.get(board_url("질답")).json()["count"], 1)

    def test_secret_post_masked_for_other_consumers(self):
        # §4 은닉: 타인에게 제목 "비밀글입니다"·작성자 미노출(개인 특정 차단)
        Post.objects.create(
            category=Post.Category.QNA,
            title="결제 문의",
            body="개인 사정",
            author=self.student,
            is_secret=True,
        )
        for viewer in (self.student2, self.parent):
            self.login(viewer)
            row = self.client.get(board_url("질답")).json()["results"][0]
            self.assertEqual(row["title"], MASKED_TITLE)
            self.assertIsNone(row["author_name"])
            self.assertTrue(row["is_secret"])

    def test_secret_post_original_title_for_author_and_staff(self):
        Post.objects.create(
            category=Post.Category.QNA,
            title="결제 문의",
            body="개인 사정",
            author=self.student,
            is_secret=True,
        )
        for viewer in (self.student, self.owner, self.admin, self.assistant):
            self.login(viewer)
            row = self.client.get(board_url("질답")).json()["results"][0]
            self.assertEqual(row["title"], "결제 문의")
            self.assertEqual(row["author_name"], "김서연")

    def test_unpublished_hidden_from_consumers_visible_to_staff(self):
        Post.objects.create(
            category=Post.Category.NOTICE,
            title="비공개 공지",
            body="본문",
            author=self.admin,
            is_published=False,
        )
        self.login(self.student)
        self.assertEqual(self.client.get(board_url("공지사항")).json()["count"], 0)
        self.login(self.admin)
        rows = self.client.get(board_url("공지사항")).json()
        self.assertEqual(rows["count"], 1)
        self.assertFalse(rows["results"][0]["is_published"])

    def test_week_notice_exposes_course_week(self):
        # 주차공지 연동(Post.course_week)은 조회 필드로만 노출(3.2.0 연동)
        course = Course.objects.create(name="로직엔제")
        week = CourseWeek.objects.create(course=course, week_no=4, title="4주차")
        Post.objects.create(
            category=Post.Category.NOTICE,
            title="4주차 공지",
            body="오메가블랙 1회 응시",
            author=self.admin,
            course_week=week,
        )
        self.login(self.student)
        row = self.client.get(board_url("공지사항")).json()["results"][0]
        self.assertEqual(
            row["course_week"],
            {"week_id": week.week_id, "week_no": 4, "course_name": "로직엔제"},
        )

    def test_list_query_count(self):
        for i in range(3):
            post = Post.objects.create(
                category=Post.Category.QNA, title=f"질문{i}", body="본문", author=self.student
            )
            PostComment.objects.create(post=post, author=self.admin, body="답변")
        self.login(self.student2)
        with self.assertNumQueries(4):  # 세션+사용자(2) + count + 페이지(annotate)
            self.client.get(board_url("질답"))


# ---------------------------------------------------------------------------
# 상세 GET /api/boards/{category}/{post_id}
# ---------------------------------------------------------------------------


class PostDetailTests(BoardFixtureMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.qna = Post.objects.create(
            category=Post.Category.QNA, title="적분 질문", body="모르겠어요", author=cls.student
        )
        cls.answer = PostComment.objects.create(post=cls.qna, author=cls.admin, body="답변입니다")
        cls.secret = Post.objects.create(
            category=Post.Category.QNA,
            title="결제 문의",
            body="개인 사정",
            author=cls.student,
            is_secret=True,
        )

    def test_login_required(self):
        res = self.client.get(board_url("질답", self.qna.post_id))
        self.assertEqual(res.status_code, 403)

    def test_detail_returns_post_with_comments(self):
        self.login(self.student2)
        res = self.client.get(board_url("질답", self.qna.post_id))
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["title"], "적분 질문")
        self.assertEqual(data["body"], "모르겠어요")
        self.assertEqual(data["author_name"], "김서연")
        self.assertFalse(data["is_mine"])
        comment = data["comments"][0]
        self.assertEqual(comment["body"], "답변입니다")
        self.assertEqual(comment["author_name"], "관리자")
        self.assertEqual(comment["author_role"], "관리자")  # 답변자 구분 배지용
        self.assertFalse(comment["is_mine"])

    def test_is_mine_flag_for_author(self):
        self.login(self.student)
        data = self.client.get(board_url("질답", self.qna.post_id)).json()
        self.assertTrue(data["is_mine"])

    def test_category_mismatch_is_404(self):
        # 질답 글을 공지사항 경로로 조회 — 카테고리 경계 강제
        self.login(self.student)
        self.assertEqual(
            self.client.get(board_url("공지사항", self.qna.post_id)).status_code, 404
        )

    def test_secret_detail_404_for_others(self):
        # 존재 비노출 — 미존재와 같은 404(§4)
        for viewer in (self.student2, self.parent):
            self.login(viewer)
            res = self.client.get(board_url("질답", self.secret.post_id))
            self.assertEqual(res.status_code, 404)
            self.assertEqual(res.json()["detail"], "찾을 수 없습니다.")

    def test_secret_detail_for_author_and_staff(self):
        for viewer in (self.student, self.owner, self.admin, self.assistant):
            self.login(viewer)
            res = self.client.get(board_url("질답", self.secret.post_id))
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["title"], "결제 문의")

    def test_unpublished_detail_404_for_consumers(self):
        hidden = Post.objects.create(
            category=Post.Category.NOTICE,
            title="비공개",
            body="본문",
            author=self.admin,
            is_published=False,
        )
        self.login(self.student)
        self.assertEqual(self.client.get(board_url("공지사항", hidden.post_id)).status_code, 404)
        self.login(self.admin)
        self.assertEqual(self.client.get(board_url("공지사항", hidden.post_id)).status_code, 200)

    def test_detail_query_count(self):
        self.login(self.student2)
        with self.assertNumQueries(4):  # 세션+사용자(2) + 글 + 댓글
            self.client.get(board_url("질답", self.qna.post_id))


# ---------------------------------------------------------------------------
# 작성 POST /api/boards/{category} — 권한 매트릭스(PRD 3.3.1)
# ---------------------------------------------------------------------------


class PostCreateMatrixTests(BoardFixtureMixin, TestCase):
    """카테고리 5종 × 역할 전수 — 공지/정오표/이벤트=직원(공지작성 키),
    질답=학생·학부모, 자유게시판=대표만."""

    def assert_matrix(self, category, allowed, denied):
        for user in allowed:
            self.login(user)
            res = self.create_post(category)
            self.assertEqual(res.status_code, 201, f"{category}/{user.name} 허용이어야 함")
        for user in denied:
            self.login(user)
            res = self.create_post(category)
            self.assertEqual(res.status_code, 403, f"{category}/{user.name} 차단이어야 함")
            self.assertEqual(res.json()["detail"], "접근 권한이 없습니다.")

    def test_notice_staff_only(self):
        # 공지사항: 직원(공지작성) — 관리자 프리셋 보유, 조교 프리셋 미보유
        self.assert_matrix(
            "공지사항",
            allowed=[self.owner, self.admin],
            denied=[self.assistant, self.student, self.parent],
        )

    def test_errata_staff_only(self):
        self.assert_matrix(
            "정오표",
            allowed=[self.owner, self.admin],
            denied=[self.assistant, self.student, self.parent],
        )

    def test_event_goods_staff_only(self):
        self.assert_matrix(
            "이벤트굿즈",
            allowed=[self.owner, self.admin],
            denied=[self.assistant, self.student, self.parent],
        )

    def test_qna_consumers_only(self):
        # 질답: 학생·학부모 작성 — 직원은 댓글(답변)로만 참여
        self.assert_matrix(
            "질답",
            allowed=[self.student, self.parent],
            denied=[self.owner, self.admin, self.assistant],
        )

    def test_free_board_owner_only(self):
        # 자유게시판: 대표만(강사 트위터형) — 공지작성 키 보유 관리자도 차단
        self.assert_matrix(
            "자유게시판",
            allowed=[self.owner],
            denied=[self.admin, self.assistant, self.student, self.parent],
        )

    def test_assistant_with_delta_grant_can_write_notice(self):
        # 프리셋 ⊕ delta — 대표가 공지작성을 개별 부여하면 조교도 작성 가능
        StaffFeatureGrant.objects.create(
            user=self.assistant, feature_key=FeatureKey.NOTICE_WRITE, is_granted=True
        )
        self.login(self.assistant)
        self.assertEqual(self.create_post("공지사항").status_code, 201)

    def test_anonymous_is_denied(self):
        self.assertEqual(self.create_post("공지사항").status_code, 403)

    def test_unknown_category_is_404(self):
        self.login(self.admin)
        self.assertEqual(self.create_post("없는게시판").status_code, 404)


class PostCreateTests(BoardFixtureMixin, TestCase):
    def test_created_post_payload_and_row(self):
        self.login(self.student)
        res = self.create_post("질답", title="적분 질문", body="모르겠어요")
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["title"], "적분 질문")
        self.assertEqual(data["category"], "질답")
        self.assertEqual(data["author_name"], "김서연")
        self.assertTrue(data["is_mine"])
        self.assertFalse(data["is_secret"])  # 기본 공개(2026-07-22 결정)
        post = Post.objects.get(pk=data["post_id"])
        self.assertEqual(post.author, self.student)
        self.assertTrue(post.is_published)
        self.assertIsNone(post.updated_at)

    def test_qna_secret_opt_in(self):
        self.login(self.student)
        res = self.create_post("질답", title="결제 문의", is_secret=True)
        self.assertEqual(res.status_code, 201)
        self.assertTrue(Post.objects.get(pk=res.json()["post_id"]).is_secret)

    def test_secret_rejected_outside_qna(self):
        # 비밀글은 질답(문의 통합 창구) 전용 — 공지 비밀글은 무의미
        self.login(self.admin)
        res = self.create_post("공지사항", is_secret=True)
        self.assertEqual(res.status_code, 400)

    def test_course_week_not_writable(self):
        # 주차공지 연동은 조회 필드로만 노출 — 작성 입력은 무시
        course = Course.objects.create(name="로직엔제")
        week = CourseWeek.objects.create(course=course, week_no=1)
        self.login(self.admin)
        res = self.create_post("공지사항", course_week_id=week.week_id)
        self.assertEqual(res.status_code, 201)
        self.assertIsNone(Post.objects.get(pk=res.json()["post_id"]).course_week)

    def test_title_and_body_required(self):
        self.login(self.student)
        for body in ({"body": "본문"}, {"title": "제목"}, {"title": " ", "body": "본문"}):
            res = self.post_json(board_url("질답"), body)
            self.assertEqual(res.status_code, 400, body)

    def test_title_length_limit(self):
        self.login(self.student)
        res = self.create_post("질답", title="가" * 201)
        self.assertEqual(res.status_code, 400)

    def test_is_secret_must_be_boolean(self):
        self.login(self.student)
        res = self.create_post("질답", is_secret="예")
        self.assertEqual(res.status_code, 400)


# ---------------------------------------------------------------------------
# 수정 PATCH /api/boards/{category}/{post_id} — 본인 글만
# ---------------------------------------------------------------------------


class PostUpdateTests(BoardFixtureMixin, TestCase):
    def setUp(self):
        self.qna = Post.objects.create(
            category=Post.Category.QNA, title="질문", body="본문", author=self.student
        )
        self.secret = Post.objects.create(
            category=Post.Category.QNA,
            title="결제 문의",
            body="개인 사정",
            author=self.student,
            is_secret=True,
        )

    def test_author_updates_own_post_and_updated_at_set(self):
        self.assertIsNone(self.qna.updated_at)
        self.login(self.student)
        res = self.patch_json(
            board_url("질답", self.qna.post_id), {"title": "수정된 질문", "body": "보충"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["title"], "수정된 질문")
        self.assertEqual(data["body"], "보충")
        self.assertIsNotNone(data["updated_at"])  # 값 존재 = 수정된 글(모델 계약)
        self.qna.refresh_from_db()
        self.assertEqual(self.qna.title, "수정된 질문")
        self.assertIsNotNone(self.qna.updated_at)

    def test_author_toggles_secret_on_qna(self):
        self.login(self.student)
        res = self.patch_json(board_url("질답", self.qna.post_id), {"is_secret": True})
        self.assertEqual(res.status_code, 200)
        self.qna.refresh_from_db()
        self.assertTrue(self.qna.is_secret)

    def test_secret_patch_rejected_outside_qna(self):
        notice = Post.objects.create(
            category=Post.Category.NOTICE, title="공지", body="본문", author=self.admin
        )
        self.login(self.admin)
        res = self.patch_json(board_url("공지사항", notice.post_id), {"is_secret": True})
        self.assertEqual(res.status_code, 400)

    def test_other_consumer_cannot_update_public_post(self):
        # 열람은 되지만 수정 권한 없음 — 403(404 아님: 공개 글은 존재가 이미 노출)
        self.login(self.student2)
        res = self.patch_json(board_url("질답", self.qna.post_id), {"title": "탈취"})
        self.assertEqual(res.status_code, 403)

    def test_staff_cannot_update_others_post(self):
        # 직원 운영 권한은 삭제만 — 타인 글 내용 수정은 대표 포함 불가
        for staff in (self.owner, self.admin):
            self.login(staff)
            res = self.patch_json(board_url("질답", self.qna.post_id), {"title": "수정"})
            self.assertEqual(res.status_code, 403, staff.name)

    def test_secret_post_update_404_for_others(self):
        # 비밀글은 열람 불가자에게 존재 비노출 — 수정 시도도 404
        self.login(self.student2)
        res = self.patch_json(board_url("질답", self.secret.post_id), {"title": "탈취"})
        self.assertEqual(res.status_code, 404)

    def test_empty_patch_is_400(self):
        self.login(self.student)
        res = self.patch_json(board_url("질답", self.qna.post_id), {"course_week_id": 1})
        self.assertEqual(res.status_code, 400)

    def test_anonymous_is_denied(self):
        res = self.patch_json(board_url("질답", self.qna.post_id), {"title": "수정"})
        self.assertEqual(res.status_code, 403)


# ---------------------------------------------------------------------------
# 삭제 DELETE /api/boards/{category}/{post_id} — 본인 글 + 직원 운영 삭제
# ---------------------------------------------------------------------------


class PostDeleteTests(BoardFixtureMixin, TestCase):
    def setUp(self):
        self.qna = Post.objects.create(
            category=Post.Category.QNA, title="질문", body="본문", author=self.student
        )

    def delete(self, category, post_id):
        return self.client.delete(board_url(category, post_id))

    def test_author_deletes_own_post_hard_with_comments(self):
        # 하드 삭제(board 서비스 docstring 판단) — 댓글도 CASCADE 소멸
        comment = PostComment.objects.create(post=self.qna, author=self.admin, body="답변")
        self.login(self.student)
        res = self.delete("질답", self.qna.post_id)
        self.assertEqual(res.status_code, 204)
        self.assertFalse(Post.objects.filter(pk=self.qna.post_id).exists())
        self.assertFalse(PostComment.objects.filter(pk=comment.comment_id).exists())

    def test_staff_with_notice_key_can_moderate_delete(self):
        # 직원 운영 삭제 — 공지작성 키(대표 전권·관리자 프리셋)
        for staff in (self.owner, self.admin):
            post = Post.objects.create(
                category=Post.Category.QNA, title="질문", body="본문", author=self.student
            )
            self.login(staff)
            self.assertEqual(self.delete("질답", post.post_id).status_code, 204, staff.name)
            self.assertFalse(Post.objects.filter(pk=post.post_id).exists())

    def test_assistant_without_key_cannot_delete(self):
        self.login(self.assistant)
        self.assertEqual(self.delete("질답", self.qna.post_id).status_code, 403)

    def test_assistant_with_delta_grant_can_delete(self):
        StaffFeatureGrant.objects.create(
            user=self.assistant, feature_key=FeatureKey.NOTICE_WRITE, is_granted=True
        )
        self.login(self.assistant)
        self.assertEqual(self.delete("질답", self.qna.post_id).status_code, 204)

    def test_other_consumer_cannot_delete(self):
        self.login(self.student2)
        self.assertEqual(self.delete("질답", self.qna.post_id).status_code, 403)
        self.assertTrue(Post.objects.filter(pk=self.qna.post_id).exists())

    def test_secret_post_delete_404_for_others(self):
        secret = Post.objects.create(
            category=Post.Category.QNA,
            title="문의",
            body="비밀",
            author=self.student,
            is_secret=True,
        )
        self.login(self.student2)
        self.assertEqual(self.delete("질답", secret.post_id).status_code, 404)

    def test_anonymous_is_denied(self):
        self.assertEqual(self.delete("질답", self.qna.post_id).status_code, 403)


# ---------------------------------------------------------------------------
# 댓글 POST /api/boards/{category}/{post_id}/comments — 열람 가능한 글에만
# ---------------------------------------------------------------------------


class CommentCreateTests(BoardFixtureMixin, TestCase):
    def setUp(self):
        self.event = Post.objects.create(
            category=Post.Category.EVENT_GOODS, title="굿즈 배포", body="본문", author=self.admin
        )
        self.secret = Post.objects.create(
            category=Post.Category.QNA,
            title="결제 문의",
            body="개인 사정",
            author=self.student,
            is_secret=True,
        )

    def comment(self, category, post_id, body="댓글"):
        return self.post_json(board_url(category, post_id, "comments"), {"body": body})

    def test_student_requests_goods_on_event_post(self):
        # 이벤트 게시판 댓글 = 학생 굿즈 요청(PRD 3.3.1)
        self.login(self.student)
        res = self.comment("이벤트굿즈", self.event.post_id, body="키링 원해요")
        self.assertEqual(res.status_code, 201)
        data = res.json()
        self.assertEqual(data["body"], "키링 원해요")
        self.assertEqual(data["author_name"], "김서연")
        self.assertEqual(data["author_role"], "학생")
        self.assertTrue(data["is_mine"])
        self.assertEqual(self.event.comments.get().author, self.student)

    def test_secret_post_comments_follow_same_hiding_rule(self):
        # 비밀글 댓글: 작성자(후속 문의)·직원(답변)만 — 타인 404(존재 비노출)
        self.login(self.student)
        self.assertEqual(self.comment("질답", self.secret.post_id).status_code, 201)
        self.login(self.admin)
        self.assertEqual(self.comment("질답", self.secret.post_id).status_code, 201)
        self.login(self.student2)
        self.assertEqual(self.comment("질답", self.secret.post_id).status_code, 404)

    def test_unpublished_post_comment_404_for_consumers(self):
        hidden = Post.objects.create(
            category=Post.Category.NOTICE,
            title="비공개",
            body="본문",
            author=self.admin,
            is_published=False,
        )
        self.login(self.student)
        self.assertEqual(self.comment("공지사항", hidden.post_id).status_code, 404)
        self.login(self.admin)
        self.assertEqual(self.comment("공지사항", hidden.post_id).status_code, 201)

    def test_body_required(self):
        self.login(self.student)
        for body in ({}, {"body": " "}, {"body": 3}):
            res = self.post_json(
                board_url("이벤트굿즈", self.event.post_id, "comments"), body
            )
            self.assertEqual(res.status_code, 400, body)

    def test_missing_post_is_404(self):
        self.login(self.student)
        self.assertEqual(self.comment("이벤트굿즈", 999999).status_code, 404)
        # 카테고리 경계 밖 경로도 404
        self.assertEqual(self.comment("공지사항", self.event.post_id).status_code, 404)

    def test_anonymous_is_denied(self):
        self.assertEqual(self.comment("이벤트굿즈", self.event.post_id).status_code, 403)


# ---------------------------------------------------------------------------
# 댓글 DELETE /api/boards/{category}/{post_id}/comments/{comment_id}
# ---------------------------------------------------------------------------


class CommentDeleteTests(BoardFixtureMixin, TestCase):
    def setUp(self):
        self.qna = Post.objects.create(
            category=Post.Category.QNA, title="질문", body="본문", author=self.student
        )
        self.comment = PostComment.objects.create(
            post=self.qna, author=self.student, body="후속 문의"
        )

    def delete(self, comment=None, category="질답", post=None):
        comment = comment or self.comment
        post = post or self.qna
        return self.client.delete(
            board_url(category, post.post_id, "comments", comment.comment_id)
        )

    def test_author_deletes_own_comment(self):
        self.login(self.student)
        self.assertEqual(self.delete().status_code, 204)
        self.assertFalse(PostComment.objects.filter(pk=self.comment.comment_id).exists())

    def test_other_consumer_cannot_delete(self):
        self.login(self.student2)
        self.assertEqual(self.delete().status_code, 403)
        self.assertTrue(PostComment.objects.filter(pk=self.comment.comment_id).exists())

    def test_staff_with_notice_key_can_moderate_delete(self):
        self.login(self.admin)
        self.assertEqual(self.delete().status_code, 204)

    def test_assistant_without_key_cannot_delete(self):
        self.login(self.assistant)
        self.assertEqual(self.delete().status_code, 403)

    def test_secret_post_comment_delete_404_for_others(self):
        secret = Post.objects.create(
            category=Post.Category.QNA,
            title="문의",
            body="비밀",
            author=self.student,
            is_secret=True,
        )
        hidden_comment = PostComment.objects.create(
            post=secret, author=self.student, body="후속"
        )
        self.login(self.student2)
        self.assertEqual(
            self.delete(comment=hidden_comment, post=secret).status_code, 404
        )

    def test_comment_of_other_post_is_404(self):
        other = Post.objects.create(
            category=Post.Category.QNA, title="다른 질문", body="본문", author=self.student2
        )
        self.login(self.student)
        self.assertEqual(self.delete(post=other).status_code, 404)

    def test_anonymous_is_denied(self):
        self.assertEqual(self.delete().status_code, 403)
