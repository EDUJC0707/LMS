"""videos 도메인 — 복습영상·시청 권한·동보 (DB 설계 도메인 4 [전면 개정 2026-07-22]).

정렬 테이블(docs/db/lms-db-design-2026-07-15.md 도메인 4 개정판,
PRD 3.1.3/3.1.4/3.2.2~3.2.3, key_considerations §4):
  - videos        복습영상 마스터 — 호스팅 Provider 중립(mux/vdocipher, 업체 미정)
  - video_grants  시청 권한 지급·만료·회수 이력(지급 단위 = 영상)
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
    중립 외부 참조(external_ref)만 저장한다 —
    업체 종속 컬럼 금지. 업체 확정·교체 시 값집합에 값을 추가하고 구현체만 교체
    (스키마 불변). 업체 미정 + 연동 후순위(PRD 3.1.3)라 provider·external_ref 는
    NULL 로 시작한다(메타 선등록 → 연동 시 채움).

    - course_week: 강의/차시 분류 축(PRD 3.1.3)이자 지급 단위(주차)의 대상 —
      NULL 이면 주차 무관 특강. 주차 삭제 시 영상 자산은 유지(SET_NULL).
      **지급 단위는 아니다** — 권한은 영상을 직접 가리키므로(VideoGrant 계약)
      이 값을 바꿔도 이미 지급된 권한은 끊기지 않는다. 다만 출결 자동지급의
      대상을 고르는 축이라, 비어 있으면 자동지급이 성립하지 않는다.
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
    #: **재생기에 그대로 넘어가는 값이다.** Mux 는 자산 하나에 asset id 와
    #: playback id 가 따로 있는데, 재생 화면이 이 값을 `playbackId` 로 쓰므로
    #: (frontend StudentVideoPage `playbackIdOf`) 여기 들어가야 하는 것은
    #: **playback id** 다. asset id 를 넣으면 재생이 조용히 실패한다.
    #: (2026-08-04 교정 — 구 docstring 이 "Mux asset id" 라고 잘못 적고 있었다.
    #:  CLAUDE.md §6: 뒤집힌 사실을 문서에 남기지 않는다.)
    external_ref = models.CharField(  # noqa: DJ001
        "재생 참조 ID", max_length=200, null=True, blank=True
    )
    #: 업로드가 진행 중인 Mux Direct Upload 의 id.
    #:
    #: **행을 업로드 **시작** 시점에 만들기 위해 있다.** 파일은 브라우저에서 Mux 로
    #: 직접 가는데(우리 서버를 안 지난다), 그 사이 브라우저가 닫히면 Mux 에는 자산이
    #: 생겼는데 우리 DB 에는 아무 것도 없는 상태가 된다 — 돈은 나가고 추적은 안 되는
    #: 유실이다. 그래서 시작할 때 행을 먼저 만들고 이 값으로 나중에 이어 붙인다.
    #:
    #: 자산이 준비되면 `external_ref` 가 채워지고 이 값은 남는다(감사 흔적).
    #: 즉 **`upload_ref` 만 있고 `external_ref` 가 비면 "업로드/인코딩 중"** 이다.
    upload_ref = models.CharField(  # noqa: DJ001
        "업로드 참조 ID", max_length=200, null=True, blank=True
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
    의 단일 표.

    **지급 단위는 영상 1개다** (2026-08-04 사용자 확정 — 구 "주차 묶음" 개정).
    한 학생이 그 주 영상 3개를 볼 수 있으면 **행이 3개** 생긴다.

    왜 바꿨나: 구 설계는 권한을 `course_week` 에 걸고 재생 판정이 영상의
    course_week 와 맞춰봤다. 그러면 **영상과 권한이 같은 칸을 공유**해서,
    관리자가 영상의 주차를 고치는 순간 그 주차 권한을 든 학생 전원이 못 보게
    됐다(2026-08-04 실측: 영상 1건의 주차를 옮기면 활성 권한 51건이 끊김).
    영상의 주차는 **콘텐츠 분류**이고 권한은 **학생이 무엇을 볼 수 있는가** 라
    둘은 별개 축이다. 이제 영상을 다른 주차로 옮겨도 권한은 그대로 붙어 있다.

    **지급 시점 계약**: 지급은 **출결 확정 시점 한 번**만 일어나고, 그때
    `공개` 상태인 그 회차 주차의 영상들에만 권한이 생긴다(2026-08-04 확정).
    따라서 **영상은 출결 입력 전에 `공개` 여야 한다** — 나중에 공개한 영상은
    그 주 출석자에게 자동으로 열리지 않는다(수동 지급으로만 메운다).

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
    video = models.ForeignKey(
        Video,
        on_delete=models.PROTECT,
        db_column="video_id",
        related_name="video_grants",
        verbose_name="지급 영상",
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
            # 출석 1건 + 영상 1개당 자동지급 1행(중복 자동생성 차단).
            # 지급 단위가 영상이 된 뒤로 한 출석이 여러 행을 낳으므로
            # attendance 단독 UQ 는 성립하지 않는다(2026-08-04 개정).
            models.UniqueConstraint(
                fields=["attendance", "video"],
                condition=models.Q(attendance__isnull=False),
                name="uq_video_grants_attendance_video",
            ),
            # 동보 1건 + 영상 1개당 지급 1행 — MakeupGrant 지급 체인 계약의 DB 백스톱
            models.UniqueConstraint(
                fields=["makeup", "video"],
                condition=models.Q(makeup__isnull=False),
                name="uq_video_grants_makeup_video",
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
        return f"권한 학생{self.student_id} 영상{self.video_id}({self.source})"


class WatermarkTamper(models.Model):
    """`watermark_tampers` — 시청 중 워터마크가 제거된 기록 (2026-08-04 사용자 착안).

    ## 왜 있나 — 못 막는 것을 기록으로 바꾼다

    워터마크는 클라이언트 오버레이라 개발자도구 한 줄로 지워진다
    (`document.querySelector('.vd-mark').remove()`). 서버측 굽기(burn-in)를 파는
    업체가 우리 규모에 없어(2026-08-04 전수조사) **원리상 막을 수 없다.**

    그래서 막는 대신 **적는다.** 워터마크는 "유출된 뒤에 누구였나" 를 답하고,
    이 표는 **"유출하려 했다"** 를 답한다. 실수로 지울 수 있는 물건이 아니므로
    행 하나가 곧 의도의 증거다.

    ## 무엇을 못 잡나 (알고 쓰라고 적는다)

    작정하면 이 보고 요청도 함께 막는다(개발자도구 네트워크 차단·JS 비활성화).
    즉 **가볍게 지우는 학생은 잡히고 작정한 학생은 안 잡힌다.** 그래도 값이 있는
    이유는 우리 위협이 보안 연구자가 아니라 **녹화본을 돌리는 학생**이기 때문이고,
    "지우면 기록에 남는다" 는 사실 자체가 억제력이기 때문이다.

    ## 왜 학생·영상을 함께 두나

    누가 어떤 영상에서 시도했는지가 조치의 단위다. 시각은 서버가 찍는다 —
    기기 시계를 믿으면 기록의 증거력이 사라진다(워터마크 날짜와 같은 이유).
    """

    tamper_id = models.BigAutoField(primary_key=True)
    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.PROTECT,
        db_column="student_id",
        related_name="watermark_tampers",
        verbose_name="학생",
    )
    video = models.ForeignKey(
        Video,
        on_delete=models.PROTECT,
        db_column="video_id",
        related_name="watermark_tampers",
        verbose_name="영상",
    )
    #: 서버 시계로 찍는다 — 기기 시계를 믿으면 증거력이 없다.
    occurred_at = models.DateTimeField("발생 시각", auto_now_add=True)

    class Meta:
        db_table = "watermark_tampers"
        verbose_name = "워터마크 제거 시도"
        verbose_name_plural = "워터마크 제거 시도"
        indexes = [
            # 학생별 조회(반복 시도자 확인)가 이 표를 쓰는 유일한 축이다.
            models.Index(fields=["student", "-occurred_at"], name="idx_tamper_student"),
        ]

    def __str__(self):
        return f"워터마크 제거 학생{self.student_id} 영상{self.video_id}"
