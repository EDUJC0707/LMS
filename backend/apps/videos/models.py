"""videos 도메인 — 복습영상·시청 권한·동보 (DB 설계 도메인 4 [전면 개정 2026-07-22]).

정렬 테이블(docs/db/lms-db-design-2026-07-15.md 도메인 4 개정판,
PRD 3.1.3/3.1.4/3.2.2~3.2.3, key_considerations §4):
  - videos        복습영상 마스터 — 호스팅 Provider 중립(mux/vdocipher, 업체 미정)
  - video_grants  시청 권한 지급·만료·회수 이력(지급 단위 = 주차)
  - makeup_grants 동보(동영상 보강) 신청·승인 기록 — 무과금(8-8 확정)

**DRM 전환 경위(PRD 3.1.3, 2026-07-21 확정)**: YouTube + RPA 봇 방식 폐기(유튜브
코드 변경 시 작동이 수시로 멈춤 — 안정성 사유) → 외부 DRM 호스팅(Mux/VdoCipher 중
미정) + LMS 내 임베드 재생으로 전환. **연동 개발은 후순위** — LMS 는 대상 산정·
부여·안내·만료 관리를 먼저 개발하고(호스팅 방식과 무관), 호스팅 API 반영 여부는
`video_grants.sync_status` 로만 기록한다(연동 전 NULL 운영). 이에 따라 구
`video_requests`(유튜브 계정 수동 권한 부여/삭제 흐름)와 `students.youtube_email`
은 폐기 — 권한 이력은 `video_grants` 가 대체한다.

**상태 기반 노출(PRD §4)**: 학생·학부모에게 복습영상은 "권한 지급된 주차만"
존재한다 — 소비자용 API 는 `VideoGrant.objects.active()` 를 유일 진입으로 쓴다
(curriculum `released()` 선례와 동일 메커니즘).
"""
from django.db import models
from django.utils import timezone


class Video(models.Model):
    """`videos` — 복습영상 마스터 (도메인 4 [전면 개정 2026-07-22], PRD 3.1.3).

    **Provider 중립 계약(key_considerations §4, payments.Payment 선례)**: 재생·권한
    로직은 앱 레이어의 호스팅 Provider 인터페이스가 담당하고, DB 는 provider 값과
    중립 외부 참조(external_ref: Mux asset id / VdoCipher video id)만 저장한다 —
    업체 종속 컬럼 금지. 업체 확정·교체 시 값집합에 값을 추가하고 구현체만 교체
    (스키마 불변). 업체 미정 + 연동 후순위(PRD 3.1.3)라 provider·external_ref 는
    NULL 로 시작한다(메타 선등록 → 연동 시 채움).

    - course_week: 강의/차시 분류 축(PRD 3.1.3)이자 지급 단위(주차)의 대상 —
      NULL 이면 주차 무관 특강. 주차 삭제 시 영상 자산은 유지(SET_NULL).
    - status: 소비자 노출은 `공개` 상태 + 권한(video_grants) 이중 게이트.
      기본 `준비중`(닫힘이 안전 기본값 — key_considerations §5). 시즌 종료 후
      전량 보관은 `아카이브`(삭제 없음 — 8-16).
    """

    class Provider(models.TextChoices):
        MUX = "mux", "Mux"
        VDOCIPHER = "vdocipher", "VdoCipher"

    class Status(models.TextChoices):
        PREPARING = "준비중", "준비중"
        PUBLISHED = "공개", "공개"
        ARCHIVED = "아카이브", "아카이브"

    video_id = models.BigAutoField(primary_key=True)
    course_week = models.ForeignKey(
        "curriculum.CourseWeek",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="course_week_id",
        related_name="videos",
        verbose_name="커리큘럼 주차",
    )
    title = models.CharField("제목", max_length=200)
    sequence_no = models.SmallIntegerField("차시", null=True, blank=True)
    provider = models.CharField(  # noqa: DJ001
        "호스팅 제공자", max_length=20, choices=Provider.choices, null=True, blank=True
    )
    external_ref = models.CharField(  # noqa: DJ001
        "외부 영상 참조 ID", max_length=200, null=True, blank=True
    )
    duration_seconds = models.IntegerField("재생 길이(초)", null=True, blank=True)
    status = models.CharField(
        "상태", max_length=15, choices=Status.choices, default=Status.PREPARING
    )
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    class Meta:
        db_table = "videos"
        verbose_name = "복습영상"
        verbose_name_plural = "복습영상"
        constraints = [
            # 부분 UQ(provider, external_ref) — 연동 전(NULL)은 제약 밖,
            # 연동 후 동일 업체·동일 자산의 이중 등록 차단
            models.UniqueConstraint(
                fields=["provider", "external_ref"],
                condition=models.Q(external_ref__isnull=False),
                name="uq_videos_provider_ref",
            ),
        ]

    def __str__(self):
        return f"{self.title}({self.status})"


class MakeupGrant(models.Model):
    """`makeup_grants` — 동보(동영상 보강) 기록 (도메인 4 개정판, PRD 3.2.3·3.1.9).

    결석생이 전화상담(3.1.9) 후 "집에서 영상으로 보강"을 확정하면 관리자가
    체크(`관리자체크`), 연락 두절 시 학생·학부모가 직접 신청(`학생신청`/
    `학부모신청` — 예비 경로). 승인·지급의 상태 기계는 status 가 담당한다.

    **지급 체인 계약**: status 가 `지급완료` 로 전이될 때 앱 레이어가
    VideoGrant(source=`동보`, makeup=이 레코드) 를 생성한다 — 출석생과 동일한
    그 주 복습영상 권한(PRD 3.2.3 1차 경로). 역참조 유일성은
    `uq_video_grants_makeup` 부분 UQ 가 보장(동보 1건당 지급 1건).

    **무과금(2026-07-15 확정, PRD 8-8)**: 동보에는 별도 수강료가 없다 — 설계
    문서 초판의 `is_tuition_billable`·`tuition_charges` 체인은 만들지 않는다.

    - attendance: 결석 근거 회차(SSOT 참조 — 사본 금지). 회차 삭제 시 기록 유지.
    - requested_by: 신청 주체 계정(학생 본인 또는 학부모 — PRD 3.2.3 양측 가능).
    """

    class Source(models.TextChoices):
        ADMIN_CHECK = "관리자체크", "관리자체크"
        STUDENT_REQUEST = "학생신청", "학생신청"
        PARENT_REQUEST = "학부모신청", "학부모신청"

    class Status(models.TextChoices):
        REQUESTED = "신청", "신청"
        APPROVED = "승인", "승인"
        GRANTED = "지급완료", "지급완료"
        REJECTED = "거절", "거절"

    makeup_id = models.BigAutoField(primary_key=True)
    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.PROTECT,
        db_column="student_id",
        related_name="makeup_grants",
        verbose_name="결석 학생",
    )
    attendance = models.ForeignKey(
        "grades.Attendance",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="attendance_id",
        related_name="makeup_grants",
        verbose_name="결석 근거 회차",
    )
    source = models.CharField("신청 경로", max_length=15, choices=Source.choices)
    requested_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="requested_by",
        related_name="requested_makeup_grants",
        verbose_name="신청 주체",
    )
    status = models.CharField(
        "상태", max_length=15, choices=Status.choices, default=Status.REQUESTED
    )
    granted_at = models.DateTimeField("지급완료 시각", null=True, blank=True)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    class Meta:
        db_table = "makeup_grants"
        verbose_name = "동보"
        verbose_name_plural = "동보"

    def __str__(self):
        return f"동보 학생{self.student_id}({self.status})"


class VideoGrantQuerySet(models.QuerySet):
    """VideoGrant 소비자 노출 게이팅 쿼리셋 (PRD §4 상태 기반 노출 원칙)."""

    def active(self, at=None):
        """살아있는 권한만 거른다 — **소비자용 API 의 유일한 진입 계약**.

        학생·학부모에게 시청 가능한 영상(주차)을 내리는 모든 API 는 반드시 이
        메서드를 거친다(강제 지점은 API 응답 레벨 — PRD §4: 권한 지급된 주차만
        존재, 프런트 숨김만으로는 무의미). 관리자 화면·만료 배치는
        `objects.all()` 을 그대로 쓴다. (curriculum `released()` 선례)

        활성 판정(기준 시각 `at`, 기본 now):
        - `revoked_at` IS NULL — 수동 회수(PRD 3.1.4 예외 처리)되지 않았고
        - `expires_at` > at — 만료 시각 도달 즉시 비활성(시청 페이지 자동 소멸,
          PRD 3.1.4 ⑥). 경계 포함 안 함: expires_at == at 는 이미 만료다.
        """
        at = at if at is not None else timezone.now()
        return self.filter(revoked_at__isnull=True, expires_at__gt=at)


class VideoGrant(models.Model):
    """`video_grants` — 시청 권한 지급·만료·회수 이력 (도메인 4 개정판, PRD 3.1.4).

    부여·만료 이력 관리(PRD 3.1.4: 학생별 부여일·만료 예정일·회수 여부 기록·추적)
    의 단일 표. 지급 단위는 **주차**(course_week) — "그 주 복습영상" 묶음이며,
    개별 영상 나열은 주차·상태(`공개`)로 조회한다(영상별 행 복제 없음).

    지급 경로(source):
    - `출석자동`: 출결 SSOT 의 `출석` 확정 트리거(PRD 3.1.4 ① — 신청·승인 없음).
      attendance 가 근거이며 부분 UQ 로 출석 1건당 자동지급 1건.
    - `동보`: MakeupGrant `지급완료` 전이 시 생성(PRD 3.2.3). makeup 이 근거이며
      부분 UQ 로 동보 1건당 지급 1건.
    - `학생신청`: 신청 기반 예외 플로우(PRD 3.1.4 요구사항 1~6, 8.1-2 연장 포함).
    - `수동`: 관리자 수동 부여(PRD 3.1.4 예외 처리).

    **만료 계약**: expires_at = 지급(granted_at) + 7일이 기본이며(2026-07-15 회의,
    관리자 설정으로 변경 가능 — PRD 3.1.4 ⑥) **기본값 산정은 앱 레이어**가 지급
    시점에 계산해 채운다(DB default 없음 — 정책 변경이 스키마와 무관하도록).

    **DRM 연동(후순위)**: 실제 부여/회수의 호스팅 API 반영은 sync_status 로 기록
    (`대기`→`부여반영`/`회수반영`, 실패 시 `실패`). 연동 전에는 NULL 로 운영하고
    관리자 수동 처리(PRD 3.1.4 ③)로 갈음한다.
    """

    class Source(models.TextChoices):
        ATTENDANCE_AUTO = "출석자동", "출석자동"
        MAKEUP = "동보", "동보"
        STUDENT_REQUEST = "학생신청", "학생신청"
        MANUAL = "수동", "수동"

    class SyncStatus(models.TextChoices):
        PENDING = "대기", "대기"
        GRANT_SYNCED = "부여반영", "부여반영"
        REVOKE_SYNCED = "회수반영", "회수반영"
        FAILED = "실패", "실패"

    grant_id = models.BigAutoField(primary_key=True)
    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.PROTECT,
        db_column="student_id",
        related_name="video_grants",
        verbose_name="학생",
    )
    course_week = models.ForeignKey(
        "curriculum.CourseWeek",
        on_delete=models.PROTECT,
        db_column="course_week_id",
        related_name="video_grants",
        verbose_name="지급 주차",
    )
    source = models.CharField("지급 경로", max_length=15, choices=Source.choices)
    attendance = models.ForeignKey(
        "grades.Attendance",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="attendance_id",
        related_name="video_grants",
        verbose_name="출석 근거",
    )
    makeup = models.ForeignKey(
        MakeupGrant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="makeup_id",
        related_name="video_grants",
        verbose_name="동보 근거",
    )
    granted_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="granted_by",
        related_name="granted_video_grants",
        verbose_name="지급 처리자",
    )
    granted_at = models.DateTimeField("지급 시각")
    expires_at = models.DateTimeField("만료 예정 시각")
    revoked_at = models.DateTimeField("회수 시각", null=True, blank=True)
    sync_status = models.CharField(  # noqa: DJ001
        "호스팅 반영 상태",
        max_length=15,
        choices=SyncStatus.choices,
        null=True,
        blank=True,
    )
    synced_at = models.DateTimeField("호스팅 반영 시각", null=True, blank=True)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    objects = VideoGrantQuerySet.as_manager()

    class Meta:
        db_table = "video_grants"
        verbose_name = "영상 권한"
        verbose_name_plural = "영상 권한"
        constraints = [
            # 출석 1건당 자동지급 1건(중복 자동생성 차단) — NULL 은 제약 밖
            models.UniqueConstraint(
                fields=["attendance"],
                condition=models.Q(attendance__isnull=False),
                name="uq_video_grants_attendance",
            ),
            # 동보 1건당 지급 1건 — MakeupGrant 지급 체인 계약의 DB 백스톱
            models.UniqueConstraint(
                fields=["makeup"],
                condition=models.Q(makeup__isnull=False),
                name="uq_video_grants_makeup",
            ),
        ]
        indexes = [
            # 학생별 활성 권한 조회(시청 페이지)·만료 배치 스캔 축
            models.Index(
                fields=["student", "expires_at"],
                name="idx_video_grants_student_exp",
            ),
        ]

    def __str__(self):
        return f"권한 학생{self.student_id} 주차{self.course_week_id}({self.source})"
