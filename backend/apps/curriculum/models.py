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


class Subject(models.Model):
    """`subjects` — 과목 + 과목구분 (FLOW 1-1·1-2).

    커리 위의 두 층이다. 층이 둘인데 표가 하나인 것은 **구분이 과목의 속성**이기
    때문이다 — 과목 하나가 두 구분에 걸치지 않는다(`통합과학` 은 언제나 수능).

    **구분은 값집합으로 잠근다**(FLOW 1-2). 안 늘어나는 값이고, 신규 입력을
    열어 두면 `수능`·`수능(재종)` 처럼 표기가 흔들려 아래 층 분류가 지저분해진다.
    **과목은 늘어나므로 행이다** — 커리가 아직 없는 과목도 골라야 해서 문자열
    사본이 아니라 표로 둔다.

    잠금은 API 입구(`class_admin.open_class`)가 건다. DB CHECK 는 두지 않는다
    (key_considerations §6 — 값 추가 시 무마이그레이션).
    """

    class Track(models.TextChoices):
        SUNEUNG = "수능", "수능"
        NAESIN = "내신", "내신"

    subject_id = models.BigAutoField(primary_key=True)
    track = models.CharField("과목구분", max_length=10, choices=Track.choices)
    name = models.CharField("과목명", max_length=50)

    class Meta:
        db_table = "subjects"
        verbose_name = "과목"
        verbose_name_plural = "과목"
        constraints = [
            models.UniqueConstraint(
                fields=["track", "name"],
                name="uq_subjects_track_name",
            ),
        ]

    def __str__(self):
        return self.name


class Course(models.Model):
    """`courses` — 강좌 마스터 (설계 문서 도메인 3 `courses`).

    캘린더 홈(PRD 3.2.0)의 주차별 커리큘럼 표기의 뿌리. 예: 로직엔제.
    """

    course_id = models.BigAutoField(primary_key=True)
    # 과목은 커리의 위층이다(FLOW 1-1). 옛 커리는 층이 생기기 전에 만들어져
    # 비어 있다 — 커리를 지우지 않으려고 NULL 을 허용한다.
    subject = models.ForeignKey(
        Subject,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        db_column="subject_id",
        related_name="courses",
        verbose_name="과목",
    )
    name = models.CharField("강좌명", max_length=100)
    # 총주차는 커리의 것이다(FLOW 1-2). 반을 만들 때 이만큼 회차를 채우고
    # (FLOW 1-3), 그 뒤 반에서 주차를 더하고 지워도 이 값은 안 바뀐다(1-5).
    total_weeks = models.PositiveSmallIntegerField("총주차", default=0)
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
    같은 `2026 여름 N제` 를 목반과 화반이 같이 듣기 때문에 반을 문자열로 두면
    오타 하나가 반을 둘로 가르고, 주차 날짜를 반마다 따로 가질 수 없다.

    반이 담는 것은 **학생·출결·성적·주차 날짜**다. 주 1회라 주차와 수업
    회차가 1:1 이므로(FLOW 1-1) 반의 주차는 별도 표가 아니라
    `grades.ClassSession` 이다 — 반별 주차 날짜가 곧 `session_date`.
    `CourseWeek` 에는 내용(제목·학습계획·영상)만 남는다.

    - 커리 삭제로 반과 그에 달린 기록이 유실되지 않게 PROTECT.
    - start_date(개강일)는 반을 만들 때 받지만, 문자열 반을 승격시킨
      백필분은 알 수 없어 NULL 이다.
    - uses_payssam: 교재값을 결제선생으로 받는 반인가(FLOW 2-7). 미래탐구는
      결제선생이 받고 **러셀은 학원이 따로 받는다** — 러셀 반에 청구가 나가면
      학부모는 같은 교재값을 두 번 낸다. **장소로 자동 판정하지 않는다**(FLOW
      2-7): 장소가 반 이름에 안 적힐 수도 있고 예외도 생기므로 조교가 반 단위로
      고른다. 기본값이 false 인 이유는 잘못 나간 청구는 되돌려도 학부모가 이미
      받았고, 안 나간 청구는 켜고 다시 보내면 그만이기 때문이다
      (key_considerations §5 — 닫힘이 안전 기본값).
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
    uses_payssam = models.BooleanField("결제선생 청구", default=False)
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
    - klass: 반(`Class`). 반 이름은 여기서만 읽는다 — 문자열 사본은 2026-08-18
      제거됐다(이름을 고치면 사본이 옛 이름으로 남았다).
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


# --- 반 이름 읽기 ---------------------------------------------------------
#
# 반 이름은 `Class.name` 하나뿐이다(사본 금지 — key_considerations §6).
# 학생↔반은 N:M 이라(FLOW 1-1) "그 학생의 반"이 여럿일 수 있어, 문맥이 없는
# 자리는 활성 수강 중 **가장 먼저 등록한 반**으로 정한다(홈의 primary 와 같은 축).


def class_name_subquery(outer="pk", course_id=None):
    """학생 행에 붙일 반 이름 서브쿼리 — 명단·성적표처럼 학생 수만큼 도는 자리용.

    `outer` 는 학생 FK 를 가리키는 바깥 필드(학생 목록은 "pk", 성적·답안지
    목록은 "student_id"). `course_id` 를 주면 그 커리의 반으로 좁힌다 —
    출결표는 그 회차 커리의 반이어야 한다.
    """
    enrollments = CourseEnrollment.objects.filter(
        student=models.OuterRef(outer), status=CourseEnrollment.Status.ENROLLED
    )
    if course_id is not None:
        enrollments = enrollments.filter(course_id=course_id)
    return models.Subquery(
        enrollments.order_by("enrollment_id").values("klass__name")[:1]
    )


def class_name_of(student):
    """학생 1명의 반 이름. 목록은 이 함수 대신 `class_name_subquery` 를 annotate 한다."""
    return (
        CourseEnrollment.objects.filter(
            student=student, status=CourseEnrollment.Status.ENROLLED
        )
        .order_by("enrollment_id")
        .values_list("klass__name", flat=True)
        .first()
    )
