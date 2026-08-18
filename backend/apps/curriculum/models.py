"""curriculum 도메인 — 강좌·주차·캘린더 (DB 설계 도메인 3, 신규 도메인).

정렬 테이블(docs/db/lms-db-design-2026-07-15.md §2 도메인 3, PRD 3.2.0):
  - courses             강좌 마스터
  - course_weeks        주차 + 오프라인 특이사항(주차공지 → 캘린더 표기)
  - week_day_plans      Day 학습계획(주 호버 시 노출)
  - course_enrollments  학생↔강좌/반(캘린더 커리큘럼 렌더 근거)

그린필드이므로 설계 문서의 최종 상태로 바로 구현한다.
인덱스는 설계 §4.4(캘린더 홈 집계) 기준. 단 `idx_course_weeks_course_no`
(course_id, week_no)는 UQ(course_id, week_no)가 만드는 유니크 인덱스와
컬럼이 동일해 중복이므로 별도 인덱스는 만들지 않는다.
"""
from django.db import models
from django.utils import timezone


class Course(models.Model):
    """`courses` — 강좌 마스터 (설계 문서 도메인 3 `courses`).

    캘린더 홈(PRD 3.2.0)의 주차별 커리큘럼 표기의 뿌리. 예: 로직엔제.
    """

    course_id = models.BigAutoField(primary_key=True)
    name = models.CharField("강좌명", max_length=100)
    target_grade = models.SmallIntegerField("대상 학년", null=True, blank=True)
    is_active = models.BooleanField("활성", default=True)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    class Meta:
        db_table = "courses"
        verbose_name = "강좌"
        verbose_name_plural = "강좌"

    def __str__(self):
        return self.name


class Class(models.Model):
    """`classes` — 반 (FLOW 1-1).

    커리(`Course`)는 **무엇을 가르치는가**, 반은 **누가·언제 듣는가**다.
    같은 `2026 여름 N제` 를 목반과 화반이 같이 듣기 때문에 반을 문자열
    (`CourseEnrollment.class_name`)로 두면 오타 하나가 반을 둘로 가르고,
    주차 날짜를 반마다 따로 가질 수 없다.

    반이 담는 것은 **학생·출결·성적·주차 날짜**다. 주 1회라 주차와 수업
    회차가 1:1 이므로(FLOW 1-1) 반의 주차는 별도 표가 아니라
    `grades.ClassSession` 이다 — 반별 주차 날짜가 곧 `session_date`.
    `CourseWeek` 에는 내용(제목·학습계획·영상)만 남는다.

    - 커리 삭제로 반과 그에 달린 기록이 유실되지 않게 PROTECT.
    - start_date(개강일)는 반을 만들 때 받지만, 문자열 반을 승격시킨
      백필분은 알 수 없어 NULL 이다.
    """

    class_id = models.BigAutoField(primary_key=True)
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        db_column="course_id",
        related_name="classes",
        verbose_name="커리",
    )
    name = models.CharField("수강반명", max_length=50)
    start_date = models.DateField("개강일", null=True, blank=True)
    is_active = models.BooleanField("활성", default=True)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    class Meta:
        db_table = "classes"
        verbose_name = "반"
        verbose_name_plural = "반"
        constraints = [
            models.UniqueConstraint(
                fields=["course", "name"],
                name="uq_classes_course_name",
            ),
        ]

    def __str__(self):
        return self.name


class CourseWeekQuerySet(models.QuerySet):
    """CourseWeek 소비자 노출 게이팅 쿼리셋 (PRD §4 상태 기반 노출 원칙)."""

    def released(self, at=None):
        """공개된 주차만 거른다 — **소비자용 API 의 유일한 진입 계약**.

        학생·학부모에게 주차(커리큘럼·학습계획·주차공지)를 내리는 모든 API 는
        반드시 이 메서드를 거친다(강제 지점은 API 응답 레벨 — PRD §4:
        미래 주차 비공개, 프런트 숨김만으로는 무의미). 관리자 화면은
        `objects.all()` 을 그대로 쓴다.

        공개 판정(기준 시각 `at`, 기본 now):
        - `release_at` 설정됨 → `release_at <= at` 이면 공개.
          start_date 보다 우선한다(조기 공개·연기 오버라이드).
        - `release_at` NULL → `start_date`(주 시작일) 당일 자정(로컬)부터 공개.
        - `release_at` NULL + `start_date` NULL → 무기한 비공개(닫힘이 안전
          기본값 — 경쟁사 열람 차단이라는 §4 목적상 열림 기본값 금지).
        """
        at = at if at is not None else timezone.now()
        return self.filter(
            models.Q(release_at__lte=at)
            | models.Q(release_at__isnull=True, start_date__lte=timezone.localdate(at))
        )


class CourseWeek(models.Model):
    """`course_weeks` — 주차 + 주차공지 (설계 문서 도메인 3 `course_weeks`).

    - offline_notice: 오프라인 특이사항(예: 오메가블랙 1회 응시) → 캘린더
      표기(PRD 3.2.0). 공지사항 게시판(posts.course_week_id)과 연동.
    - 주차는 강좌의 구성요소라 강좌 삭제 시 함께 삭제(CASCADE).
    - release_at: 소비자 공개 시점(PRD §4 상태 기반 노출 — 콘텐츠 단위,
      3.2.0). NULL 이면 주 시작일(start_date)과 동기화되어 시작일 자정부터
      공개(값 복제가 없어 start_date 변경을 자동 추종). 관리자 조기 공개는
      release_at 을 앞당겨 설정. start_date 까지 NULL 이면 무기한 비공개.
      판정 로직·계약은 `CourseWeekQuerySet.released()` docstring 참조.
    """

    week_id = models.BigAutoField(primary_key=True)
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        db_column="course_id",
        related_name="weeks",
        verbose_name="강좌",
    )
    week_no = models.SmallIntegerField("주차 번호")
    # 아래 문자열 컬럼은 설계 문서가 NULL로 명시 — ''와 미입력을 구분한다.
    title = models.CharField("주차 제목", max_length=100, null=True, blank=True)  # noqa: DJ001
    offline_notice = models.TextField("오프라인 특이사항", null=True, blank=True)  # noqa: DJ001
    start_date = models.DateField("시작일", null=True, blank=True)
    end_date = models.DateField("종료일", null=True, blank=True)
    release_at = models.DateTimeField(
        "공개 시점",
        null=True,
        blank=True,
        help_text="비우면 시작일 자정부터 공개. 조기 공개는 이 값을 앞당겨 설정.",
    )

    objects = CourseWeekQuerySet.as_manager()

    class Meta:
        db_table = "course_weeks"
        verbose_name = "강좌 주차"
        verbose_name_plural = "강좌 주차"
        constraints = [
            # 설계: UQ(course_id, week_no) — §4.4 idx_course_weeks_course_no 겸용
            models.UniqueConstraint(
                fields=["course", "week_no"],
                name="uq_course_weeks_course_week_no",
            ),
        ]

    def __str__(self):
        return f"{self.course} {self.week_no}주차"


class WeekDayPlan(models.Model):
    """`week_day_plans` — Day 학습계획 (설계 문서 도메인 3 `week_day_plans`).

    주에 커서를 올리면(호버/탭) Day1·Day2… 학습계획 노출(PRD 3.2.0).
    주차의 구성요소라 주차 삭제 시 함께 삭제(CASCADE).
    """

    plan_id = models.BigAutoField(primary_key=True)
    week = models.ForeignKey(
        CourseWeek,
        on_delete=models.CASCADE,
        db_column="week_id",
        related_name="day_plans",
        verbose_name="주차",
    )
    day_no = models.SmallIntegerField("Day 번호")
    title = models.CharField("제목", max_length=100, null=True, blank=True)  # noqa: DJ001
    content = models.TextField("학습계획", null=True, blank=True)  # noqa: DJ001
    display_order = models.SmallIntegerField("표시 순서", null=True, blank=True)

    class Meta:
        db_table = "week_day_plans"
        verbose_name = "Day 학습계획"
        verbose_name_plural = "Day 학습계획"
        constraints = [
            # 설계: UQ(week_id, day_no)
            models.UniqueConstraint(
                fields=["week", "day_no"],
                name="uq_week_day_plans_week_day_no",
            ),
        ]

    def __str__(self):
        return f"{self.week} Day{self.day_no}"


class CourseEnrollment(models.Model):
    """`course_enrollments` — 학생↔강좌/반 (설계 문서 도메인 3 `course_enrollments`).

    캘린더가 "이 학생이 어느 강좌 몇 주차인지" 렌더하는 근거(PRD 3.2.0).
    - status는 설계 값집합(한국어) 그대로. DB CHECK는 두지 않는다
      (설계 원칙: 값 추가 시 무마이그레이션).
    - 수강 이력은 기록이므로 학생·강좌 삭제로 유실되지 않게 PROTECT.
    - primary_weekday: 0=일…6=토. -- 잠정: 다요일 반복 시 확장(설계 문서 주석)
    - klass: 진짜 반(`Class`). `class_name` 문자열과 당분간 공존한다 —
      문자열을 읽는 자리가 아직 여럿이라 제거는 별건이다.
    """

    class Status(models.TextChoices):
        ENROLLED = "수강", "수강"
        COMPLETED = "종료", "종료"
        SUSPENDED = "중단", "중단"

    enrollment_id = models.BigAutoField(primary_key=True)
    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.PROTECT,
        db_column="student_id",
        related_name="course_enrollments",
        verbose_name="학생",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        db_column="course_id",
        related_name="enrollments",
        verbose_name="강좌",
    )
    class_name = models.CharField("반", max_length=30, null=True, blank=True)  # noqa: DJ001
    klass = models.ForeignKey(
        Class,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        db_column="class_id",
        related_name="enrollments",
        verbose_name="반",
    )
    primary_weekday = models.SmallIntegerField("주 수업 요일", null=True, blank=True)
    status = models.CharField(
        "수강 상태",
        max_length=15,
        choices=Status.choices,
        default=Status.ENROLLED,
    )
    enrolled_at = models.DateTimeField("수강 시작 시각", auto_now_add=True)
    ended_at = models.DateTimeField("수강 종료 시각", null=True, blank=True)

    class Meta:
        db_table = "course_enrollments"
        verbose_name = "수강"
        verbose_name_plural = "수강"
        constraints = [
            # 학생↔반은 N:M(FLOW 1-1) — 수능 반과 내신 반을 같이 듣는 학생이
            # 있다. 구 UQ(student, course)는 그걸 막았으므로 반 단위로 옮긴다.
            models.UniqueConstraint(
                fields=["student", "klass"],
                name="uq_course_enrollments_student_class",
            ),
        ]
        indexes = [
            # 설계 §4.4: 학생별 활성 수강만 부분 인덱스
            models.Index(
                fields=["student"],
                name="idx_course_enrollments_student",
                condition=models.Q(status="수강"),
            ),
        ]

    def __str__(self):
        return f"{self.student_id}↔{self.course_id}({self.get_status_display()})"
