"""grades 도메인 — 성적·OMR·과제·약점체크 (DB 설계 도메인 2, 시스템 허브).

정렬 테이블(docs/db/lms-db-design-2026-07-15.md §2 도메인 2, baseline
lms-db-spec.html · PRD 3.1.1/3.1.6/3.2.1):
  - class_sessions        수업 회차(↔ course_weeks 매핑)
  - attendances           출결 SSOT — 영상/클리닉/캘린더/리포트 공통 트리거
  - exams · scores        시험 · 성적 집계(클리닉 판정 재사용)
  - assignments           과제 수행 플래그
  - answer_sheets · sheet_answers   OMR 스캔·문항 채점(추가마킹 포함)
  - questions             시험 문항(테마·학습가이드·내신/수능형)
  - question_bank_items   문제은행(내신형/수능형)
  - question_similar_maps 오답→유사문항 사전매칭(문항당 2개)
  - weakness_check_pdfs   약점체크 PDF 생성 기록
  - workbook_submissions  워크북 사진 업로드·수행도 도장

그린필드이므로 baseline+delta 의 최종 상태로 바로 구현한다.
인덱스는 설계 §4.1~§4.3 기준. 단 단일 FK 컬럼과 동일한 설계 인덱스
(idx_attendances_student, idx_qsm_bank, idx_class_sessions_week)는 Django 의
FK 자동 인덱스와 중복이므로 별도로 만들지 않는다(curriculum 선례와 동일 원칙).
"""
from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models


class ClassSession(models.Model):
    """`class_sessions` — 수업 회차 (설계 문서 도메인 2 `class_sessions`).

    - exam: 그날 본 시험(없으면 NULL). 시험 삭제 시 회차 기록은 유지(SET_NULL).
    - course_week: 수업회차 ↔ 커리큘럼 주차 매핑(캘린더 커리큘럼 표시,
      PRD 3.2.0). 주차 삭제 시 회차 기록은 유지(SET_NULL).
    """

    session_id = models.BigAutoField(primary_key=True)
    session_date = models.DateField("수업일")
    session_no = models.SmallIntegerField("차시", null=True, blank=True)
    target_grade = models.SmallIntegerField("대상 학년", null=True, blank=True)
    exam = models.ForeignKey(
        "Exam",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="exam_id",
        related_name="class_sessions",
        verbose_name="그날 시험",
    )
    memo = models.CharField("메모", max_length=200, null=True, blank=True)  # noqa: DJ001
    course_week = models.ForeignKey(
        "curriculum.CourseWeek",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="course_week_id",
        related_name="class_sessions",
        verbose_name="커리큘럼 주차",
    )

    class Meta:
        db_table = "class_sessions"
        verbose_name = "수업 회차"
        verbose_name_plural = "수업 회차"
        indexes = [
            # 설계 §4.4: 캘린더 월 단위 날짜 범위 스캔
            models.Index(fields=["session_date"], name="idx_class_sessions_date"),
            # idx_class_sessions_week 는 course_week FK 자동 인덱스로 갈음
        ]

    def __str__(self):
        return f"{self.session_date} 수업({self.session_no or '-'}차시)"


class Attendance(models.Model):
    """`attendances` — 출결 **SSOT** (설계 문서 도메인 2 `attendances`, PRD 3.1.6).

    **계약: 이 표가 출결의 단일 원천(SSOT)이다.** 담임이 입력한 status 한 번이
      (1) 복습영상 자동지급 — `출석` 확정 시 video_requests(source=출석자동)
          자동 생성 (PRD 3.1.4)
      (2) 클리닉 대상 판정 전제 — 출석 + 응시(scores.is_taken/exam_taken)
          + 평균미달 → clinic_eligibilities (PRD 3.2.4)
      (3) 캘린더 홈 출석/결석 도장 (PRD 3.2.0)
      (4) 수업별 학부모 리포트 발송 대상 (PRD 3.1.1)
    의 공통 트리거·판정 근거다. 위 소비자들은 별도 출결 사본을 두지 말고
    반드시 이 표를 참조한다. "와야 하는데 안 온 날" = status `결석` 레코드
    존재(담임이 결석분도 입력 — 별도 스케줄 마스터 불필요).

    - status 값집합은 `출석/결석/지각` 뿐이다. **`퇴원` 값 금지** — 퇴원은
      학생 생애주기 상태라 students.enrollment_status 에 단일 저장(회차별
      출결과 분리, 이중모델 방지 — 설계 도메인 1 결정).
    - exam_taken: 현장 시험 응시 여부 -- 잠정: scores.is_taken 재사용 vs
      별도 축(클리닉 대상 판정용).
    - updated_at: 정정 추적(권한 회수 트리거 근거). 설계가 NULL 로 명시 —
      auto_now 를 쓰지 않고 정정 시 앱 레이어에서 갱신한다(최초 입력은 NULL,
      값 존재 = 정정된 레코드).
    - 출결은 회차의 구성요소(CASCADE), 학생 쪽은 기록 보존(PROTECT —
      학생 생애주기는 soft-delete 라 실삭제 자체가 예외 상황).
    """

    class Status(models.TextChoices):
        PRESENT = "출석", "출석"
        ABSENT = "결석", "결석"
        LATE = "지각", "지각"

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        ClassSession,
        on_delete=models.CASCADE,
        db_column="session_id",
        related_name="attendances",
        verbose_name="수업 회차",
    )
    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.PROTECT,
        db_column="student_id",
        related_name="attendances",
        verbose_name="학생",
    )
    status = models.CharField("출결 상태", max_length=10, choices=Status.choices)
    exam_taken = models.BooleanField("현장 시험 응시", null=True, blank=True)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="marked_by",
        related_name="marked_attendances",
        verbose_name="출결 입력자",
    )
    created_at = models.DateTimeField("입력 시각", auto_now_add=True)
    updated_at = models.DateTimeField("정정 시각", null=True, blank=True)

    class Meta:
        db_table = "attendances"
        verbose_name = "출결"
        verbose_name_plural = "출결"
        constraints = [
            # 설계: UQ(session_id, student_id) — 회차당 학생 1줄
            models.UniqueConstraint(
                fields=["session", "student"],
                name="uq_attendances_session_student",
            ),
        ]
        indexes = [
            # 설계 §4.2: 회차별 출석부(상태 집계)
            models.Index(
                fields=["session", "status"],
                name="idx_attendances_session_status",
            ),
            # idx_attendances_student 는 student FK 자동 인덱스로 갈음
        ]

    def __str__(self):
        return f"{self.session_id}회차 학생{self.student_id} {self.status}"


class Exam(models.Model):
    """`exams` — 시험/모의고사 회차 (baseline 도메인 2 `exams`, 불변 참조).

    avg_score/stddev/max_score/top30_score 는 채점 후 계산 캐시(PRD 3.2.1
    성적 요약). avg_score 는 클리닉 대상 판정(평균미달)에서 재사용.
    """

    exam_id = models.BigAutoField(primary_key=True)
    name = models.CharField("시험명", max_length=100)
    exam_date = models.DateField("시험일")
    round_no = models.SmallIntegerField("회차 번호", null=True, blank=True)
    target_grade = models.SmallIntegerField("대상 학년", null=True, blank=True)
    notice = models.TextField("성적표 공지사항", null=True, blank=True)  # noqa: DJ001
    avg_score = models.DecimalField(
        "전체 평균", max_digits=6, decimal_places=2, null=True, blank=True
    )
    stddev = models.DecimalField(
        "표준편차", max_digits=6, decimal_places=2, null=True, blank=True
    )
    max_score = models.DecimalField(
        "최고점", max_digits=6, decimal_places=2, null=True, blank=True
    )
    top30_score = models.DecimalField(
        "상위 30% 점수", max_digits=6, decimal_places=2, null=True, blank=True
    )
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    class Meta:
        db_table = "exams"
        verbose_name = "시험"
        verbose_name_plural = "시험"

    def __str__(self):
        return f"{self.name}({self.exam_date})"


class Question(models.Model):
    """`questions` — 문항 채점기준 (baseline + delta, PRD 3.1.1 문항 정보 입력).

    - theme_tag: 누적 테마별 정답률 집계축(PRD 3.2.1) -- 잠정: 중단원 재사용
      vs 신규 태그.
    - study_guide: 오답 시 학습가이드(성적표 학습동선, 첫해 수기 → AI 학습데이터).
    - guide_video_id: 학습가이드가 가리키는 복습영상 -- 잠정: 텍스트 vs 엔티티
      참조. 설계는 FK videos 이나 videos 앱이 아직 placeholder(모델 없음)라
      FK 제약 없는 BIGINT 로 구현 — videos.Video 구현 시 FK 승격.
    - question_format: 내신형/수능형 — 유사문항 조회 대상 문제은행 선택.
    - 문항은 시험의 구성요소(CASCADE).
    """

    class Format(models.TextChoices):
        SCHOOL = "내신형", "내신형"
        CSAT = "수능형", "수능형"

    question_id = models.BigAutoField(primary_key=True)
    exam = models.ForeignKey(
        Exam,
        on_delete=models.CASCADE,
        db_column="exam_id",
        related_name="questions",
        verbose_name="시험",
    )
    q_number = models.SmallIntegerField("문항 번호")
    answer = models.CharField("정답", max_length=10)
    points = models.DecimalField("배점", max_digits=4, decimal_places=1)
    unit_major = models.CharField("대단원", max_length=50)
    unit_minor = models.CharField("중단원", max_length=50, null=True, blank=True)  # noqa: DJ001
    wrong_rate = models.DecimalField(
        "오답률", max_digits=5, decimal_places=2, null=True, blank=True
    )
    theme_tag = models.CharField("테마", max_length=50, null=True, blank=True)  # noqa: DJ001
    study_guide = models.TextField("오답 학습가이드", null=True, blank=True)  # noqa: DJ001
    guide_video_id = models.BigIntegerField("학습가이드 복습영상", null=True, blank=True)
    question_format = models.CharField(  # noqa: DJ001
        "문항 유형", max_length=10, choices=Format.choices, null=True, blank=True
    )

    class Meta:
        db_table = "questions"
        verbose_name = "문항"
        verbose_name_plural = "문항"
        constraints = [
            # 설계: UQ(exam_id, q_number)
            models.UniqueConstraint(
                fields=["exam", "q_number"],
                name="uq_questions_exam_q_number",
            ),
        ]

    def __str__(self):
        return f"{self.exam_id}번 시험 {self.q_number}번 문항"


class AnswerSheet(models.Model):
    """`answer_sheets` — OMR 스캔·매칭 (baseline 도메인 2, PRD 3.1.1).

    - student: 원번+이름 대조(매칭) 전 NULL, 대조 완료 시 채움. 매칭 이력
      보존을 위해 학생 실삭제는 차단(PROTECT).
    - match_status: PRD 3.1.1 대조 6분기(정상/부분/불일치/미존재/중복/비정상).
    - 답안지는 시험의 구성요소(CASCADE).
    """

    class MatchStatus(models.TextChoices):
        MATCHED = "정상", "정상"
        PARTIAL = "부분", "부분"
        MISMATCH = "불일치", "불일치"
        MISSING = "미존재", "미존재"
        DUPLICATE = "중복", "중복"
        INVALID = "비정상", "비정상"

    sheet_id = models.BigAutoField(primary_key=True)
    exam = models.ForeignKey(
        Exam,
        on_delete=models.CASCADE,
        db_column="exam_id",
        related_name="answer_sheets",
        verbose_name="시험",
    )
    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        db_column="student_id",
        related_name="answer_sheets",
        verbose_name="학생",
    )
    scan_image_path = models.CharField("스캔 파일 경로", max_length=500)
    recognized_unique_id = models.CharField(  # noqa: DJ001
        "인식된 원번", max_length=10, null=True, blank=True
    )
    recognized_name = models.CharField("인식된 이름", max_length=50, null=True, blank=True)  # noqa: DJ001
    match_status = models.CharField("대조 상태", max_length=20, choices=MatchStatus.choices)
    is_corrected = models.BooleanField("수동 보정 완료", default=False)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    class Meta:
        db_table = "answer_sheets"
        verbose_name = "OMR 답안지"
        verbose_name_plural = "OMR 답안지"

    def __str__(self):
        return f"답안지 {self.sheet_id}({self.match_status})"


class SheetAnswer(models.Model):
    """`sheet_answers` — 문항별 답안·채점 (baseline + delta, PRD 3.1.1).

    - extra_practice_marked: OMR '더 풀고 싶은 문항' 추가 마킹란 인식값
      (정오 무관). 약점체크 대상 = result=`오답` OR extra_practice_marked=true
      → 각각 유사문항 2개(question_similar_maps).
    - 답안지·문항의 구성요소(CASCADE — exam 삭제 시 두 경로 모두 연쇄 삭제).
    """

    class Result(models.TextChoices):
        CORRECT = "정답", "정답"
        WRONG = "오답", "오답"
        BLANK = "무응답", "무응답"
        MULTI = "복수마킹", "복수마킹"

    id = models.BigAutoField(primary_key=True)
    sheet = models.ForeignKey(
        AnswerSheet,
        on_delete=models.CASCADE,
        db_column="sheet_id",
        related_name="answers",
        verbose_name="답안지",
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        db_column="question_id",
        related_name="sheet_answers",
        verbose_name="문항",
    )
    marked = models.CharField("마킹 값", max_length=10, null=True, blank=True)  # noqa: DJ001
    result = models.CharField("채점 결과", max_length=10, choices=Result.choices)
    is_corrected = models.BooleanField("수동 보정", default=False)
    extra_practice_marked = models.BooleanField("추가 마킹", default=False)
    extra_mark_corrected = models.BooleanField("추가 마킹 보정", default=False)

    class Meta:
        db_table = "sheet_answers"
        verbose_name = "문항 답안"
        verbose_name_plural = "문항 답안"
        constraints = [
            # 설계: UQ(sheet_id, question_id)
            models.UniqueConstraint(
                fields=["sheet", "question"],
                name="uq_sheet_answers_sheet_question",
            ),
        ]
        indexes = [
            # 설계 §4.1: 오답/추가마킹 문항만 스캔(약점체크 소스) — 부분 인덱스
            models.Index(
                fields=["sheet"],
                name="idx_sheet_answers_weak",
                condition=models.Q(result="오답") | models.Q(extra_practice_marked=True),
            ),
        ]

    def __str__(self):
        return f"답안지{self.sheet_id} 문항{self.question_id} {self.result}"


class Score(models.Model):
    """`scores` — 성적 집계 (baseline 도메인 2 `scores`, 불변 참조).

    - is_taken: 응시 여부(false=미응시, 총점 0 처리 — PRD 3.1.1). 클리닉 대상
      판정(출석+응시+평균미달)에서 attendances 와 함께 재사용.
    - 대단원별 점수는 questions+sheet_answers 로 즉석 계산(별도 표 없음).
    - 성적은 시험의 구성요소(CASCADE), 학생 쪽은 기록 보존(PROTECT).
    """

    score_id = models.BigAutoField(primary_key=True)
    exam = models.ForeignKey(
        Exam,
        on_delete=models.CASCADE,
        db_column="exam_id",
        related_name="scores",
        verbose_name="시험",
    )
    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.PROTECT,
        db_column="student_id",
        related_name="scores",
        verbose_name="학생",
    )
    total_score = models.DecimalField(
        "총점", max_digits=6, decimal_places=2, null=True, blank=True
    )
    max_score = models.DecimalField(
        "만점", max_digits=6, decimal_places=2, null=True, blank=True
    )
    percentile = models.DecimalField(
        "백분위", max_digits=5, decimal_places=2, null=True, blank=True
    )
    rank_top_pct = models.DecimalField(
        "석차 상위 %", max_digits=5, decimal_places=2, null=True, blank=True
    )
    is_taken = models.BooleanField("응시 여부", default=True)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    class Meta:
        db_table = "scores"
        verbose_name = "성적"
        verbose_name_plural = "성적"
        constraints = [
            # 설계: UQ(exam_id, student_id) — 한 학생·한 시험당 1줄
            models.UniqueConstraint(
                fields=["exam", "student"],
                name="uq_scores_exam_student",
            ),
        ]
        indexes = [
            # 설계 §4.1: 학생 누적 추이(회차별)는 student 선행 복합
            models.Index(
                fields=["student", "exam"],
                name="idx_scores_student_exam",
            ),
        ]

    def __str__(self):
        return f"시험{self.exam_id} 학생{self.student_id} {self.total_score}"


class Assignment(models.Model):
    """`assignments` — 과제 수행 (baseline 도메인 2, 불변 참조, PRD 3.1.1).

    done 플래그는 관리자 수동 입력. 워크북 사진(workbook_submissions)과
    이원 관리 — 리포트의 '수행=사진 링크' 연결은 앱 레이어 소관.
    """

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        ClassSession,
        on_delete=models.CASCADE,
        db_column="session_id",
        related_name="assignments",
        verbose_name="수업 회차",
    )
    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.PROTECT,
        db_column="student_id",
        related_name="assignments",
        verbose_name="학생",
    )
    done = models.BooleanField("과제 수행 여부")
    memo = models.CharField("메모", max_length=200, null=True, blank=True)  # noqa: DJ001

    class Meta:
        db_table = "assignments"
        verbose_name = "과제"
        verbose_name_plural = "과제"
        constraints = [
            # 설계: UQ(session_id, student_id)
            models.UniqueConstraint(
                fields=["session", "student"],
                name="uq_assignments_session_student",
            ),
        ]

    def __str__(self):
        return f"회차{self.session_id} 학생{self.student_id} {'수행' if self.done else '미수행'}"


class QuestionBankItem(models.Model):
    """`question_bank_items` — 문제은행 (설계 문서 도메인 2 신규, PRD 3.1.8).

    내신형(개념확인)/수능형 2종 DB. 원 문항의 question_format 에 대응하는
    bank_type 에서 유사문항을 매칭한다. 폐기는 is_active=false(soft-off).
    """

    class BankType(models.TextChoices):
        SCHOOL = "내신형", "내신형"
        CSAT = "수능형", "수능형"

    bank_item_id = models.BigAutoField(primary_key=True)
    bank_type = models.CharField("은행 유형", max_length=10, choices=BankType.choices)
    content_path = models.CharField("문제 파일 경로", max_length=500)
    answer = models.CharField("정답", max_length=10, null=True, blank=True)  # noqa: DJ001
    unit_major = models.CharField("대단원", max_length=50, null=True, blank=True)  # noqa: DJ001
    unit_minor = models.CharField("중단원", max_length=50, null=True, blank=True)  # noqa: DJ001
    theme_tag = models.CharField("테마", max_length=50, null=True, blank=True)  # noqa: DJ001
    difficulty = models.SmallIntegerField("난이도", null=True, blank=True)
    # -- 잠정: 라벨링 툴 내부/외부(설계 문서 §6)
    labels = models.JSONField("세부 라벨", null=True, blank=True)
    source = models.CharField("출처", max_length=200, null=True, blank=True)  # noqa: DJ001
    is_active = models.BooleanField("활성", default=True)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    class Meta:
        db_table = "question_bank_items"
        verbose_name = "문제은행 문항"
        verbose_name_plural = "문제은행 문항"
        indexes = [
            # 설계 §4.3: 유형+단원 필터, 활성만 부분 인덱스
            models.Index(
                fields=["bank_type", "unit_major", "unit_minor"],
                name="idx_qbank_type_unit",
                condition=models.Q(is_active=True),
            ),
            # 설계 §4.3: 라벨 검색(JSONB) — GIN
            GinIndex(fields=["labels"], name="idx_qbank_labels"),
        ]

    def __str__(self):
        return f"문제은행 {self.bank_item_id}({self.bank_type})"


class QuestionSimilarMap(models.Model):
    """`question_similar_maps` — 오답→유사문항 사전매칭 (도메인 2 신규, PRD 3.1.8).

    원고 작성 시 문항당 유사문항 2개를 미리 매칭. 채점 후 오답·추가마킹
    문항의 유사문항을 이 표에서 자동 조회(약점체크 PDF 소스).
    - ordinal: 설계 CHECK 1..2 — DB CHECK 금지 원칙이라 앱 레벨 choices 로 강제.
    - 문항 삭제 시 매핑도 삭제(CASCADE). 은행 문항은 매핑이 남아 있는 동안
      실삭제 차단(PROTECT — 폐기는 is_active=false).
    """

    class Ordinal(models.IntegerChoices):
        FIRST = 1, "1번"
        SECOND = 2, "2번"

    map_id = models.BigAutoField(primary_key=True)
    question = models.ForeignKey(
        Question,
        on_delete=models.CASCADE,
        db_column="question_id",
        related_name="similar_maps",
        verbose_name="원 문항",
    )
    similar_bank_item = models.ForeignKey(
        QuestionBankItem,
        on_delete=models.PROTECT,
        db_column="similar_bank_item_id",
        related_name="similar_maps",
        verbose_name="유사문항",
    )
    ordinal = models.SmallIntegerField("순번", choices=Ordinal.choices)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    class Meta:
        db_table = "question_similar_maps"
        verbose_name = "유사문항 매칭"
        verbose_name_plural = "유사문항 매칭"
        constraints = [
            # 설계: UQ(question_id, ordinal) — 문항당 1·2번
            models.UniqueConstraint(
                fields=["question", "ordinal"],
                name="uq_qsm_question_ordinal",
            ),
        ]
        # idx_qsm_bank 는 similar_bank_item FK 자동 인덱스로 갈음

    def __str__(self):
        return f"문항{self.question_id} 유사{self.ordinal}번"


class WeaknessCheckPdf(models.Model):
    """`weakness_check_pdfs` — 약점체크 PDF 생성 기록 (도메인 2 신규, PRD 3.1.8).

    성적처리 완료 시 학생별 1p 성적표 + 유사문항 다시풀기 PDF 자동 생성
    (인쇄만 하면 되는 상태 — PRD 3.1.1). 학생·시험당 1건.
    """

    class Status(models.TextChoices):
        PENDING = "생성대기", "생성대기"
        GENERATED = "생성완료", "생성완료"
        PRINTED = "인쇄완료", "인쇄완료"
        FAILED = "실패", "실패"

    pdf_id = models.BigAutoField(primary_key=True)
    exam = models.ForeignKey(
        Exam,
        on_delete=models.CASCADE,
        db_column="exam_id",
        related_name="weakness_check_pdfs",
        verbose_name="시험",
    )
    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.PROTECT,
        db_column="student_id",
        related_name="weakness_check_pdfs",
        verbose_name="학생",
    )
    pdf_path = models.CharField("PDF 경로", max_length=500, null=True, blank=True)  # noqa: DJ001
    page_count = models.SmallIntegerField("페이지 수", null=True, blank=True)
    status = models.CharField(
        "상태", max_length=15, choices=Status.choices, default=Status.PENDING
    )
    generated_at = models.DateTimeField("생성 완료 시각", null=True, blank=True)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    class Meta:
        db_table = "weakness_check_pdfs"
        verbose_name = "약점체크 PDF"
        verbose_name_plural = "약점체크 PDF"
        constraints = [
            # 설계: UQ(exam_id, student_id) — 학생·시험당 1건
            models.UniqueConstraint(
                fields=["exam", "student"],
                name="uq_weakness_pdfs_exam_student",
            ),
        ]

    def __str__(self):
        return f"약점체크 시험{self.exam_id} 학생{self.student_id}({self.status})"


class WorkbookSubmission(models.Model):
    """`workbook_submissions` — 워크북 사진 업로드 (도메인 2 신규, PRD 3.1.7).

    워크북 마지막 페이지 사진(OCR 불필요) + 수행도 ABC 도장. 학부모 리포트의
    "과제 수행=사진 링크"로 연결(PRD 3.1.1).
    - student: -- 잠정 매핑키(조교 수동 지정 vs 원번 인식).
    - session: 어느 수업분인지(NULL 허용). 회차 삭제 시 사진 기록 유지(SET_NULL).
    """

    class PerformanceGrade(models.TextChoices):
        A = "A", "A"
        B = "B", "B"
        C = "C", "C"

    submission_id = models.BigAutoField(primary_key=True)
    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.PROTECT,
        db_column="student_id",
        related_name="workbook_submissions",
        verbose_name="학생",
    )
    session = models.ForeignKey(
        ClassSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="session_id",
        related_name="workbook_submissions",
        verbose_name="수업 회차",
    )
    image_path = models.CharField("사진 경로", max_length=500)
    admin_original_text = models.TextField("관리용 원본 텍스트", null=True, blank=True)  # noqa: DJ001
    performance_grade = models.CharField(  # noqa: DJ001
        "수행도", max_length=1, choices=PerformanceGrade.choices, null=True, blank=True
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="uploaded_by",
        related_name="uploaded_workbook_submissions",
        verbose_name="업로드 조교",
    )
    created_at = models.DateTimeField("업로드 시각", auto_now_add=True)

    class Meta:
        db_table = "workbook_submissions"
        verbose_name = "워크북 제출"
        verbose_name_plural = "워크북 제출"

    def __str__(self):
        return f"워크북 학생{self.student_id} 회차{self.session_id or '-'}"
