"""clinic 도메인 — 클리닉(오답/약점 보충 1:1 과외) (DB 설계 도메인 6).

정렬 테이블(docs/db/lms-db-design-2026-07-15.md 도메인 6, baseline
lms-db-spec.html Domain 4, PRD 3.2.4):
  - clinic_slots            요일×시간 슬롯·정원(정원 = 조교 수)
  - clinic_requests         신청·배정·링크·클리닉 출결(노쇼)
  - clinic_eligibilities    대상자 판정 기록(원천은 grades — 사본 금지)
  - clinic_eval_criteria    평가표 항목(체크리스트 마스터)
  - clinic_evaluations      평가(클리닉 1건당 1개, 녹음경로·AI요약)
  - clinic_evaluation_items 항목별 판단(AI 판단 + 관리자 수정)

그린필드이므로 baseline+delta 의 최종 상태로 바로 구현한다.
인덱스는 설계 §4.8 기준. 노쇼 누적·영구제한의 원천은
accounts.Student(noshow_count/clinic_banned) — 여기 사본을 두지 않는다.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

# 클리닉 한 타임 정원 — **1 고정**(2026-07-21 회의: "시간별로 학생 한 명씩").
# ClinicSlot.capacity 의 기본값·CheckConstraint·모델 검증이 공유하는 유일한 값.
SLOT_CAPACITY = 1


class ClinicSlot(models.Model):
    """`clinic_slots` — 요일×시간 슬롯 (설계 도메인 6, PRD 3.2.4).

    - weekday: 0=일…6=토(운영은 월~금). 시간대는 사전 정의 슬롯(예: 19~20시)로
      제한하고 학생은 달력에서 날짜→시간을 골라 신청한다.
    - capacity: **한 타임 1명 고정**. 근거는 2026-07-21 회의 — "클리닉이 한
      시간에 여러 개 일어나는 경우도 있나요?" → "시간별로 학생 한 명씩"(그래서
      구글 미트 계정 1개로 충분하다는 결론이 성립한다). 즉 정원은 관리자가
      정하는 설정값이 아니라 **운영의 고정 사실**이므로 관리자 API·화면에
      편집 경로를 두지 않고(editable=False) DB CheckConstraint 로 못 박는다.
      (2026-07-15 회의의 "배정 가능 인원 기준으로 관리자가 설정"은 0721 회의로
      뒤집힌 서술이다 — 정정 기록은 마이그레이션 0002·설계 문서 각주에.)
      **컬럼을 남기는 이유**: ① 설계 문서(lms-db-design-2026-07-15 도메인 6)와
      baseline 스키마가 이 컬럼을 정의하고 있어 삭제는 되돌리기 비싼 스키마
      변경이다 ② 마감 판정식(활성 신청 수 >= capacity)이 컬럼을 그대로 읽어
      1 이 어디서 오는지 코드에 드러난다 ③ 운영 전제가 바뀌어 2명이 되는 날
      제약 완화만으로 열 수 있다. 값이 1 뿐이므로 소비자 응답에는 싣지 않는다
      (booking.slot_block — 잔여석·정원 노출 폐지).
      마감 판정 계약: 해당 (slot, requested_date)의 활성 신청 수(status
      `대기`+`승인배정`) >= capacity → 마감. capacity=1 이므로 **활성 신청이
      한 건만 있어도 그 날짜·시간은 마감**이다. 집계는 clinic_requests 를 세는
      앱 레이어 소관 — 잔여석 사본 컬럼 금지.
    - 폐지는 is_active=false(soft-off). 신청 이력이 참조하므로 실삭제는
      차단(ClinicRequest.slot PROTECT).
    """

    # 한 타임 1명(2026-07-21 회의) — 모듈 상수 SLOT_CAPACITY 의 클래스 별칭.
    FIXED_CAPACITY = SLOT_CAPACITY

    slot_id = models.BigAutoField(primary_key=True)
    weekday = models.SmallIntegerField("요일")  # 0=일…6=토
    start_time = models.TimeField("시작 시간")
    end_time = models.TimeField("종료 시간")
    capacity = models.SmallIntegerField("정원", default=SLOT_CAPACITY, editable=False)
    is_active = models.BooleanField("활성", default=True)

    class Meta:
        db_table = "clinic_slots"
        verbose_name = "클리닉 슬롯"
        verbose_name_plural = "클리닉 슬롯"
        constraints = [
            # 설계: UQ(weekday, start_time)
            models.UniqueConstraint(
                fields=["weekday", "start_time"],
                name="uq_clinic_slots_weekday_start",
            ),
            # 한 타임 1명(0721 회의) — 값집합이 아니라 운영 불변식이라 DB 로 막는다
            # (key_considerations §6 의 "값집합 CHECK 금지"와 다른 축).
            models.CheckConstraint(
                condition=models.Q(capacity=SLOT_CAPACITY),
                name="ck_clinic_slots_capacity_one",
            ),
        ]

    def __str__(self):
        return f"슬롯 요일{self.weekday} {self.start_time}~{self.end_time}"

    def clean(self):
        """폼·직접 호출 경로에서도 같은 불변식을 잡는다(DB 제약과 이중)."""
        super().clean()
        if self.capacity != self.FIXED_CAPACITY:
            raise ValidationError({"capacity": "클리닉 정원은 1로 고정입니다."})


class ClinicRequest(models.Model):
    """`clinic_requests` — 클리닉 신청·배정·출결 (baseline + delta, PRD 3.2.4).

    상태 흐름: `대기` → 관리자 승인+배정(`승인배정`, assigned_staff 지정) 또는
    `미승인`. 학생 취소는 status `취소` + cancelled_at 스탬프.

    앱 레이어 계약(모델은 근거 컬럼만 기록):
    - **전날 마감**: 클리닉 날짜의 전날까지만 신청·변경·취소 가능 — 당일과
      지난 날짜는 시각과 무관하게 불가(2026-07-29 확정).
    - **신청 창구의 끝**: requested_date 는 그 시험 회차의 **시험일이 속한
      주의 다음 주 월요일**까지만 가능(2026-07-29 확정). 시험을 본 주 다음
      주에 클리닉을 진행하므로 월요일에 닫아야 그날 조교 배정을 확정할 수
      있다. 창구 끝은 신청·변경에만 걸고 **취소에는 걸지 않는다**(자원 반납).
    - **링크 노출**: meet_url 은 시작 5분 전부터 해당 학생 계정에만 노출.
      클리닉 1건 = 새 구글 미트 스페이스 1개(링크 재사용 금지 —
      key_considerations §4).
    - **노쇼**: attendance_status `결석`(시작 10분 이상 미출석, 결석 처리
      버튼) = 노쇼 1회. 누적·영구제한의 원천은 accounts.Student 의
      noshow_count/clinic_banned(사본 금지) — 결석 처리 시 앱 레이어가
      증가시키고, 2회 도달 시 clinic_banned=true(해제는 관리자 수동).
      **취소는 노쇼로 집계하지 않는다**(cancelled_at 존재 ≠ 노쇼).
    - 출석/결석 버튼 처리 순간 학부모 알림 발송(attendance_marked_at 이
      발송 시점 근거).
    """

    class Status(models.TextChoices):
        PENDING = "대기", "대기"
        APPROVED = "승인배정", "승인배정"
        REJECTED = "미승인", "미승인"
        CANCELLED = "취소", "취소"

    class AttendanceStatus(models.TextChoices):
        UNMARKED = "미처리", "미처리"
        PRESENT = "출석", "출석"
        ABSENT = "결석", "결석"  # = 노쇼

    clinic_id = models.BigAutoField(primary_key=True)
    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.PROTECT,
        db_column="student_id",
        related_name="clinic_requests",
        verbose_name="신청 학생",
    )
    requested_date = models.DateField("희망 날짜")
    requested_time = models.TimeField("희망 시작 시간")
    status = models.CharField(
        "상태", max_length=15, choices=Status.choices, default=Status.PENDING
    )
    assigned_staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="assigned_staff_id",
        related_name="assigned_clinic_requests",
        verbose_name="배정 조교",
    )
    meet_url = models.CharField("구글 미트 링크", max_length=500, null=True, blank=True)  # noqa: DJ001
    attendance_status = models.CharField(  # noqa: DJ001
        "클리닉 출결",
        max_length=10,
        choices=AttendanceStatus.choices,
        null=True,
        blank=True,
    )
    attendance_marked_at = models.DateTimeField("출결 처리 시각", null=True, blank=True)
    attendance_marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="attendance_marked_by",
        related_name="marked_clinic_requests",
        verbose_name="출결 처리자",
    )
    slot = models.ForeignKey(
        ClinicSlot,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        db_column="slot_id",
        related_name="requests",
        verbose_name="신청 슬롯",
    )
    exam = models.ForeignKey(
        "grades.Exam",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="exam_id",
        related_name="clinic_requests",
        verbose_name="대상 판정 근거 시험",
    )
    cancelled_at = models.DateTimeField("취소 시각", null=True, blank=True)
    created_at = models.DateTimeField("신청 시각", auto_now_add=True)
    updated_at = models.DateTimeField("시간수정 추적", null=True, blank=True)

    class Meta:
        db_table = "clinic_requests"
        verbose_name = "클리닉 신청"
        verbose_name_plural = "클리닉 신청"
        indexes = [
            # 설계 §4.8: 슬롯별 활성 신청 수(정원 체크) — 부분 인덱스
            models.Index(
                fields=["slot", "requested_date"],
                name="idx_clinic_req_slot",
                condition=models.Q(status__in=["대기", "승인배정"]),
            ),
        ]

    def __str__(self):
        return f"클리닉 학생{self.student_id} {self.requested_date}({self.status})"


class ClinicEligibility(models.Model):
    """`clinic_eligibilities` — 대상자 판정 기록 (설계 도메인 6, PRD 3.2.4).

    **참조 계약(원천은 grades — 사본 컬럼 금지)**: 자격 3조건의 원천은
      ① 해당 시험일 출석 = `attendances`(그 시험이 걸린 회차의 status `출석`,
        grades.Attendance — 출결 SSOT)
      ② 현장 시험 응시 = `scores.is_taken`(grades.Score) 또는
        `attendances.exam_taken`(잠정 축 병존 — 설계 도메인 2)
      ③ 평균 미달 = 학생 총점(scores.total_score) < 기준점. 기준점은
        cutoff_score 가 있으면 그 값, 없으면 전체평균(`exams.avg_score`) —
        전체평균 자동(A) 기본 + 관리자 컷(B) 교체(헤더 노트 ⑤, 미결 8-10).
    이 표는 판정 **결과**(is_target/reason)와 판정에 쓴 기준점·처리자·시각만
    기록한다(감사 이력). 출석·응시 값을 여기 복사하지 않는다.

    판정 확정(is_target=true) 즉시 대상자에게 신청 안내 알림 발송(PRD 3.1.2).
    소비자 화면 계약: 대상자만 '신청' 버튼 활성, 비대상자는 '미대상자' 표시
    (상태 기반 노출 — PRD §4, 강제는 API 레벨).
    """

    class Reason(models.TextChoices):
        ABSENT = "결석", "결석"
        NOT_TAKEN = "미응시", "미응시"
        ABOVE_AVG = "평균이상", "평균이상"

    eligibility_id = models.BigAutoField(primary_key=True)
    exam = models.ForeignKey(
        "grades.Exam",
        on_delete=models.CASCADE,
        db_column="exam_id",
        related_name="clinic_eligibilities",
        verbose_name="시험",
    )
    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.PROTECT,
        db_column="student_id",
        related_name="clinic_eligibilities",
        verbose_name="학생",
    )
    is_target = models.BooleanField("대상자", default=False)
    # -- 잠정: 전체평균 vs 별도 컷(미결 8-10). NULL=전체평균 자동 판정.
    cutoff_score = models.DecimalField(
        "판정 기준점", max_digits=6, decimal_places=2, null=True, blank=True
    )
    reason = models.CharField(  # noqa: DJ001
        "미대상 사유", max_length=30, choices=Reason.choices, null=True, blank=True
    )
    determined_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="determined_by",
        related_name="determined_clinic_eligibilities",
        verbose_name="판정자",
    )
    determined_at = models.DateTimeField("판정 시각", null=True, blank=True)

    class Meta:
        db_table = "clinic_eligibilities"
        verbose_name = "클리닉 대상자 판정"
        verbose_name_plural = "클리닉 대상자 판정"
        constraints = [
            # 설계: UQ(exam_id, student_id) — 시험·학생당 판정 1건
            models.UniqueConstraint(
                fields=["exam", "student"],
                name="uq_clinic_elig_exam_student",
            ),
        ]
        indexes = [
            # 설계 §4.8: 대상자만 부분 인덱스(신청 버튼 활성 조회)
            models.Index(
                fields=["student"],
                name="idx_clinic_elig_student",
                condition=models.Q(is_target=True),
            ),
        ]

    def __str__(self):
        return f"시험{self.exam_id} 학생{self.student_id} {'대상' if self.is_target else '미대상'}"


class ClinicEvalCriteria(models.Model):
    """`clinic_eval_criteria` — 조교 평가표 항목 마스터 (baseline, PRD 3.2.4).

    관리자가 평가 항목을 미리 입력(체크리스트). 폐지는 is_active=false —
    평가 이력이 참조하므로 실삭제 차단(ClinicEvaluationItem.criteria PROTECT).
    """

    criteria_id = models.BigAutoField(primary_key=True)
    item = models.CharField("평가 항목", max_length=200)
    description = models.CharField("기준 설명", max_length=300, null=True, blank=True)  # noqa: DJ001
    display_order = models.SmallIntegerField("표시 순서", null=True, blank=True)
    is_active = models.BooleanField("활성", default=True)

    class Meta:
        db_table = "clinic_eval_criteria"
        verbose_name = "클리닉 평가 항목"
        verbose_name_plural = "클리닉 평가 항목"

    def __str__(self):
        return self.item


class ClinicEvaluation(models.Model):
    """`clinic_evaluations` — 조교 수행 평가 (baseline, PRD 3.2.4).

    클리닉 1건당 1개(1:1). 녹음(감독용, 녹화 아님) 근거로 AI 가 요약·항목
    판단 → overall_result `부적격`이면 needs_review=true 로 관리자 검토 흐름.
    recording_path 는 스토리지 경로만(큰 파일 DB 저장 금지).
    """

    class OverallResult(models.TextChoices):
        QUALIFIED = "적격", "적격"
        UNQUALIFIED = "부적격", "부적격"

    eval_id = models.BigAutoField(primary_key=True)
    clinic = models.OneToOneField(
        ClinicRequest,
        on_delete=models.CASCADE,
        db_column="clinic_id",
        related_name="evaluation",
        verbose_name="클리닉",
    )
    recording_path = models.CharField("녹음 파일 경로", max_length=500, null=True, blank=True)  # noqa: DJ001
    ai_summary = models.TextField("AI 녹음 요약", null=True, blank=True)  # noqa: DJ001
    overall_result = models.CharField(  # noqa: DJ001
        "종합 판정", max_length=10, choices=OverallResult.choices, null=True, blank=True
    )
    needs_review = models.BooleanField("관리자 확인 필요", default=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="reviewed_by",
        related_name="reviewed_clinic_evaluations",
        verbose_name="확인 관리자",
    )
    reviewed_at = models.DateTimeField("확인 시각", null=True, blank=True)
    review_note = models.CharField("검토 메모", max_length=300, null=True, blank=True)  # noqa: DJ001
    evaluated_at = models.DateTimeField("AI 평가 시각", null=True, blank=True)

    class Meta:
        db_table = "clinic_evaluations"
        verbose_name = "클리닉 평가"
        verbose_name_plural = "클리닉 평가"

    def __str__(self):
        return f"클리닉{self.clinic_id} 평가({self.overall_result or '미판정'})"


class ClinicEvaluationItem(models.Model):
    """`clinic_evaluation_items` — 항목별 판단 (baseline, PRD 3.2.4).

    AI 판단(result/ai_reason) + 관리자 최종 수정(admin_override).
    admin_override 가 있으면 그 값이 최종값(없으면 result).
    """

    class Result(models.TextChoices):
        MET = "충족", "충족"
        UNMET = "미충족", "미충족"

    id = models.BigAutoField(primary_key=True)
    evaluation = models.ForeignKey(
        ClinicEvaluation,
        on_delete=models.CASCADE,
        db_column="eval_id",
        related_name="items",
        verbose_name="평가",
    )
    criteria = models.ForeignKey(
        ClinicEvalCriteria,
        on_delete=models.PROTECT,
        db_column="criteria_id",
        related_name="evaluation_items",
        verbose_name="평가 항목",
    )
    result = models.CharField("AI 판단", max_length=10, choices=Result.choices)
    ai_reason = models.CharField("AI 판단 근거", max_length=500, null=True, blank=True)  # noqa: DJ001
    admin_override = models.CharField(  # noqa: DJ001
        "관리자 수정 최종값", max_length=10, choices=Result.choices, null=True, blank=True
    )

    class Meta:
        db_table = "clinic_evaluation_items"
        verbose_name = "클리닉 평가 항목별 판단"
        verbose_name_plural = "클리닉 평가 항목별 판단"
        constraints = [
            # baseline: UNIQUE(eval_id, criteria_id)
            models.UniqueConstraint(
                fields=["evaluation", "criteria"],
                name="uq_clinic_eval_items_criteria",
            ),
        ]

    def __str__(self):
        final = self.admin_override or self.result
        return f"평가{self.evaluation_id} 항목{self.criteria_id} {final}"
