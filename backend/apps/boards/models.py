"""boards 도메인 — 게시판·문의·상담 (DB 설계 도메인 7).

정렬 테이블(docs/db/lms-db-design-2026-07-15.md 도메인 7 + 헤더 노트 ③,
baseline lms-db-spec.html Domain 6, PRD 3.3.1/3.3.2/3.1.9/3.4):
  - posts                    게시판(공지/정오표/질답/자유/이벤트굿즈, 주차공지 연동)
  - post_comments            게시판 답글/댓글
  - absence_counselings      결석 전화상담 기록(관리자용)
  - parent_counsel_requests  학부모 상담 신청

`inquiries`/`inquiry_messages`(baseline 1:1 문의)는 만들지 않는다 — 설계
헤더 노트 ③(질답↔문의 **일단 통합**, 단일 창구) + PRD 8-11 결정에 따라
1:1 문의는 질답 게시판의 비밀글 옵션(2026-07-22 결정)으로 흡수된다.
분리 여지는 유지 — 공개 Q&A/1:1 분리 확정 시 표 신설로 대응(가산, 저위험).

그린필드이므로 baseline+delta 의 최종 상태로 바로 구현한다.
"""
from django.conf import settings
from django.db import models


class Post(models.Model):
    """`posts` — 게시판 (baseline + delta, PRD 3.3.1).

    카테고리별 운영(작성 권한은 API 레벨 RBAC — PRD §4):
    - 공지사항: 관리자 작성. 주차 공지는 course_week 로 캘린더 홈(3.2.0) 연동.
    - 정오표: 관리자 작성.
    - 질답: 학생 질문 + 강사/관리자 답변(post_comments). 문의(3.3.2)와 통합된
      단일 창구(8-11). **기본 공개 + 작성 시 비밀글 옵션(2026-07-22 결정)** —
      is_secret=true 면 작성자·관리자만 열람(결제 등 개인적 문의용). 열람
      강제는 API 레벨(프런트 숨김만으로는 무의미 — PRD §4).
    - 자유게시판: 강사(한종철)/지정 관리자의 트위터형 피드.
    - 이벤트굿즈: 관리자 공지 + 학생 요청/제안.
    학생·학부모 열람(비공개 조건: is_published=false 또는 비밀글 비작성자).
    - updated_at: 수정 추적. 설계가 NULL 명시 — auto_now 없이 수정 시 앱
      레이어에서 갱신(값 존재 = 수정된 글, grades.Attendance 선례).
    """

    class Category(models.TextChoices):
        NOTICE = "공지사항", "공지사항"
        ERRATA = "정오표", "정오표"
        QNA = "질답", "질답"
        FREE = "자유게시판", "자유게시판"
        EVENT_GOODS = "이벤트굿즈", "이벤트굿즈"

    post_id = models.BigAutoField(primary_key=True)
    category = models.CharField("카테고리", max_length=15, choices=Category.choices)
    title = models.CharField("제목", max_length=200)
    body = models.TextField("본문")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column="author_id",
        related_name="posts",
        verbose_name="작성자",
    )
    is_published = models.BooleanField("게시 여부", default=True)
    # 2026-07-22 결정(PRD 3.3.1): 기본 공개, 비밀글은 옵트인.
    is_secret = models.BooleanField("비밀글", default=False)
    course_week = models.ForeignKey(
        "curriculum.CourseWeek",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="course_week_id",
        related_name="posts",
        verbose_name="주차 공지 연동",
    )
    created_at = models.DateTimeField("작성 시각", auto_now_add=True)
    updated_at = models.DateTimeField("수정 시각", null=True, blank=True)

    class Meta:
        db_table = "posts"
        verbose_name = "게시글"
        verbose_name_plural = "게시글"

    def __str__(self):
        return f"[{self.category}] {self.title}"


class PostComment(models.Model):
    """`post_comments` — 게시판 답글 (설계 도메인 7 신규, PRD 3.3.1).

    질답 답변(강사/관리자)·자유/이벤트 댓글 공용. 비밀글의 답글 열람 범위는
    글과 동일(작성자·관리자만 — API 레벨 강제). 글 삭제 시 답글도 삭제(CASCADE).
    """

    comment_id = models.BigAutoField(primary_key=True)
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        db_column="post_id",
        related_name="comments",
        verbose_name="게시글",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        db_column="author_id",
        related_name="post_comments",
        verbose_name="작성자",
    )
    body = models.TextField("본문")
    created_at = models.DateTimeField("작성 시각", auto_now_add=True)

    class Meta:
        db_table = "post_comments"
        verbose_name = "게시글 답글"
        verbose_name_plural = "게시글 답글"

    def __str__(self):
        return f"글{self.post_id} 답글{self.comment_id}"


class AbsenceCounseling(models.Model):
    """`absence_counselings` — 결석 전화상담 기록 (설계 도메인 7 신규, PRD 3.1.9).

    결석 체인의 상담 단계: 결석(grades.Attendance status `결석`) → 상담 대기열
    자동 생성(PRD §4 배치 ④) → 학부모(1차)/학생(2차) 전화 →
    **makeup_requested=true(동보 체크) → videos 도메인 `makeup_grants`
    (source=관리자체크) 생성 → 영상 자동지급** 으로 이어진다(연계는 앱 레이어,
    이 표는 상담 기록·근거만 담당 — 감사 이력).
    - attendance: 대상 결석 회차(출결 SSOT 참조 — 사본 금지). 회차 삭제 시
      상담 기록은 유지(SET_NULL).
    """

    class Target(models.TextChoices):
        PARENT = "학부모", "학부모"  # 1차
        STUDENT = "학생", "학생"  # 2차

    class Status(models.TextChoices):
        PENDING = "대기", "대기"
        COMPLETED = "완료", "완료"
        UNREACHED = "미연결", "미연결"

    class Provider(models.TextChoices):
        """통화가 어디를 거쳤나 — 업체 이름은 **값**이지 컬럼이 아니다.

        업체 종속 컬럼(`channeltalk_call_id` 등)을 만들지 않는 이유는
        key_considerations §4 와 같다: 업체를 바꾸면 스키마가 따라 움직인다.
        `provider` + 중립 참조 하나면 어댑터만 갈아 끼우면 된다.
        """

        CHANNELTALK = "채널톡", "채널톡"

    counsel_id = models.BigAutoField(primary_key=True)
    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.PROTECT,
        db_column="student_id",
        related_name="absence_counselings",
        verbose_name="결석생",
    )
    attendance = models.ForeignKey(
        "grades.Attendance",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="attendance_id",
        related_name="absence_counselings",
        verbose_name="결석 회차",
    )
    target = models.CharField("통화 대상", max_length=10, choices=Target.choices)
    called_at = models.DateTimeField("통화 일시", null=True, blank=True)
    absence_reason = models.CharField("결석 사유", max_length=300, null=True, blank=True)  # noqa: DJ001
    makeup_requested = models.BooleanField("동보 신청 여부", default=False)
    call_memo = models.TextField("통화 내용", null=True, blank=True)  # noqa: DJ001
    follow_up_action = models.CharField("후속 조치", max_length=300, null=True, blank=True)  # noqa: DJ001
    status = models.CharField(
        "상태", max_length=15, choices=Status.choices, default=Status.PENDING
    )
    counselor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="counselor_id",
        related_name="absence_counselings",
        verbose_name="결석 담당자",
    )
    # 조교가 "이 통화가 이 시도다" 라고 확정한 것만 저장한다. 로그 전체를
    # 복사하지 않는 이유: 업체 응답에 통화 ID 가 없어 중복 제거를
    # (시각·번호·방향) 복합키로 추측해야 하고, 그 추측이 곧 계약이 된다.
    provider = models.CharField(
        "통화 경로", max_length=10, choices=Provider.choices, blank=True, default=""
    )
    # 채널톡은 통화 ID 를 안 준다 — 유일한 안정 참조가 userChatId 다.
    # 녹음·STT 도 이 값으로 찾는다.
    provider_ref = models.CharField("통화 참조", max_length=64, blank=True, default="")
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    class Meta:
        db_table = "absence_counselings"
        verbose_name = "결석 상담"
        verbose_name_plural = "결석 상담"

    def __str__(self):
        return f"결석상담 학생{self.student_id} {self.target}({self.status})"


class ParentCounselRequest(models.Model):
    """`parent_counsel_requests` — 학부모 상담 신청 (설계 도메인 7 신규, PRD 3.4).

    학부모 write 허용 범위(헤더 노트 ④)의 상담 신청 창구. 접수 → 진행 → 완료.
    처리자·시각을 남긴다(감사 이력). student 는 대상 자녀(다자녀 드롭다운
    컨텍스트) — 미지정 신청도 가능(NULL).
    """

    class Status(models.TextChoices):
        RECEIVED = "접수", "접수"
        IN_PROGRESS = "진행", "진행"
        COMPLETED = "완료", "완료"

    request_id = models.BigAutoField(primary_key=True)
    parent = models.ForeignKey(
        "accounts.Parent",
        on_delete=models.PROTECT,
        db_column="parent_id",
        related_name="counsel_requests",
        verbose_name="신청 학부모",
    )
    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="student_id",
        related_name="parent_counsel_requests",
        verbose_name="대상 자녀",
    )
    request_content = models.TextField("상담 요청 내용")
    status = models.CharField(
        "상태", max_length=15, choices=Status.choices, default=Status.RECEIVED
    )
    admin_reply = models.TextField("관리자 응답 메모", null=True, blank=True)  # noqa: DJ001
    requested_at = models.DateTimeField("신청 시각", auto_now_add=True)
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="handled_by",
        related_name="handled_counsel_requests",
        verbose_name="처리자",
    )
    handled_at = models.DateTimeField("처리 시각", null=True, blank=True)

    class Meta:
        db_table = "parent_counsel_requests"
        verbose_name = "학부모 상담 신청"
        verbose_name_plural = "학부모 상담 신청"

    def __str__(self):
        return f"상담신청 학부모{self.parent_id}({self.status})"
