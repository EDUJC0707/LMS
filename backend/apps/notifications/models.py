"""notifications 도메인 — 알림 발송 이력 (DB 설계 도메인 8).

정렬 테이블(docs/db/lms-db-design-2026-07-15.md 도메인 8·§1.4, baseline
lms-db-spec.html Domain 7, PRD 3.1.2·§4·6-8):
  - notifications  발송 이력(= 관리자 발송내역 조회의 바탕). 대상 3분기
                   (student/parent/user), channel/type/status 값집합.

**채널 추상화 계약(key_considerations §4, PRD 6-8)**: 발송은 앱 레이어의
"알림 채널" 인터페이스(현재 카카오 알림톡, 향후 앱푸시 확장·교체)가 담당하고,
DB 는 channel 값과 중립 결과(status/error_msg)만 기록한다 — 업체(솔라피 등)
종속 컬럼 금지. 채널 추가 = Channel 값 추가 + 구현체 등록(스키마 불변).

그린필드이므로 baseline 최종 상태로 바로 구현한다. 인덱스는 설계 §4.5 기준.
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Notification(models.Model):
    """`notifications` — 알림 발송 이력 (baseline 도메인 7, PRD 3.1.2).

    - **대상 3분기**: student(학생)/parent(학부모)/user(직원) 중 **정확히
      하나만** 채운다. DB CHECK 금지 원칙이라 강제는 앱 레벨(clean) —
      개인별(1명 단위) 발송 행 단위이며, 전체 일괄 발송도 대상자 수만큼
      행을 만든다(행 = 발송내역 조회 단위).
    - **type 은 개방 값집합**: 발송 시점 전체 확정 목록이 미결 8-17
      (2026-07-29 수신 예정)이라 choices 를 필드에 바인딩하지 않는다.
      값 추가 = Type 상수 추가뿐(AlterField 마이그레이션조차 없음).
      알려진 값은 Type 에 상수로 제공(발송 코드의 오타 방지용 준거).
    - ref_type/ref_id: 유발 원인 soft 링크(FK 아님 — order/exam/clinic 등
      어느 도메인이든 값으로 가리킨다). 원본 삭제에도 이력은 남는다.
    - status: 대기 → 성공/실패(→ 전달확인). 실패 재발송 배치는
      idx_notif_status 부분 인덱스 스캔(§4.5).
    - **sent_to_phone 은 발송 시점 연락처의 스냅샷**(FLOW 2-5·3-8). 대상 행
      (users.phone·parents.phone)을 따라가면 "지금 저장된 번호"가 나오는데,
      번호를 고친 뒤에는 그 값이 **옛 발송이 나간 번호와 다르다** — "못 받았다"는
      연락에 답하려면 그때 어디로 나갔는지가 있어야 한다. 채우는 것은 발송
      경로(`sending.deliver`) 한 곳뿐이고, 값이 없던 시절의 행은 **빈 값으로
      둔다**(소급해 채우면 지금 번호를 그때 번호인 척 적는 것이 된다).
    - 발송 이력은 감사 기록 — 대상 삭제로 유실되지 않게 PROTECT(개인정보
      파기 시 이력 처리는 관리자 수동 절차 소관 — 8-1 연계).
    """

    class Channel(models.TextChoices):
        KAKAO = "카카오알림톡", "카카오알림톡"
        SMS = "문자", "문자"
        PUSH = "앱푸시", "앱푸시"

    class Type(models.TextChoices):
        """알려진 type 값 상수 — 필드 미바인딩(개방 값집합, 위 docstring 참조).

        baseline(성적/영상권한/결제/리포트/클리닉출결/계정발급/노쇼경고…) +
        2026-07-15 delta(동보/결석상담/상담신청/클리닉리마인더). 클리닉대상은
        판정 확정 즉시 신청 안내(PRD 3.1.2), 영상만료예고는 8.1-1(D-2 사전
        알림). 7/29 확정 목록 수신 시 상수만 추가한다.

        **FLOW 3-11 의 여덟 시점은 값이 서로 달라야 한다.** 알림톡 템플릿은
        `NOTIFICATION_KAKAO_TEMPLATE_CODES` 가 **type 으로** 찾으므로
        (aligo._alimtalk_payload), 두 시점이 같은 값을 쓰면 한쪽 문구로만
        나간다. 그래서 교재청구는 결제(취소·환불)와, 클리닉확정·반려·
        리마인더·미참석은 서로 갈라져 있다.
        """

        GRADE = "성적", "성적"
        VIDEO_GRANT = "영상권한", "영상권한"
        VIDEO_EXPIRY = "영상만료예고", "영상만료예고"
        PAYMENT = "결제", "결제"
        BILLING = "교재청구", "교재청구"
        REPORT = "리포트", "리포트"
        CLINIC_TARGET = "클리닉대상", "클리닉대상"
        CLINIC_ATTENDANCE = "클리닉출결", "클리닉출결"
        CLINIC_APPROVED = "클리닉확정", "클리닉확정"
        CLINIC_REJECTED = "클리닉반려", "클리닉반려"
        CLINIC_REMINDER = "클리닉리마인더", "클리닉리마인더"
        CLINIC_NOSHOW_CHECK = "클리닉미참석", "클리닉미참석"
        ACCOUNT_ISSUED = "계정발급", "계정발급"
        NOSHOW_WARNING = "노쇼경고", "노쇼경고"
        MAKEUP = "동보", "동보"
        ABSENCE_COUNSEL = "결석상담", "결석상담"
        COUNSEL_REQUEST = "상담신청", "상담신청"

    class Status(models.TextChoices):
        PENDING = "대기", "대기"
        SUCCESS = "성공", "성공"
        FAILED = "실패", "실패"
        CONFIRMED = "전달확인", "전달확인"

    notif_id = models.BigAutoField(primary_key=True)
    student = models.ForeignKey(
        "accounts.Student",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        db_column="student_id",
        related_name="notifications",
        verbose_name="대상 학생",
    )
    parent = models.ForeignKey(
        "accounts.Parent",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        db_column="parent_id",
        related_name="notifications",
        verbose_name="대상 학부모",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        db_column="user_id",
        related_name="notifications",
        verbose_name="대상 직원",
    )
    channel = models.CharField("채널", max_length=15, choices=Channel.choices)
    type = models.CharField("알림 유형", max_length=20)  # 개방 값집합 — Type 상수 참조
    title = models.CharField("제목", max_length=200, null=True, blank=True)  # noqa: DJ001
    body = models.TextField("본문", null=True, blank=True)  # noqa: DJ001
    ref_type = models.CharField("원인 유형", max_length=20, null=True, blank=True)  # noqa: DJ001
    ref_id = models.BigIntegerField("원인 ID", null=True, blank=True)
    sent_at = models.DateTimeField("발송 시각", null=True, blank=True)
    # 앱 안 알림의 읽음(FLOW 3-11). 발송 결과와 다른 축이다 — 문자가 실패해도
    # 앱에는 남고, 받는 사람이 열면 읽힌다. NULL = 아직 안 읽음.
    read_at = models.DateTimeField("읽은 시각", null=True, blank=True)
    sent_to_phone = models.CharField("보낸 번호", max_length=20, blank=True, default="")
    status = models.CharField(
        "상태", max_length=15, choices=Status.choices, default=Status.PENDING
    )
    error_msg = models.CharField("실패 사유", max_length=300, null=True, blank=True)  # noqa: DJ001
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    class Meta:
        db_table = "notifications"
        verbose_name = "알림"
        verbose_name_plural = "알림"
        indexes = [
            # 설계 §4.5: 대상별 최신순 조회 — NULL 다수라 부분 인덱스
            models.Index(
                fields=["student", "-sent_at"],
                name="idx_notif_student_sent",
                condition=models.Q(student__isnull=False),
            ),
            models.Index(
                fields=["parent", "-sent_at"],
                name="idx_notif_parent_sent",
                condition=models.Q(parent__isnull=False),
            ),
            # 설계 §4.5: 실패 재발송 배치 — 대기/실패만 부분 인덱스
            models.Index(
                fields=["status"],
                name="idx_notif_status",
                condition=models.Q(status__in=["대기", "실패"]),
            ),
        ]

    def __str__(self):
        target = self.student_id or self.parent_id or self.user_id
        return f"알림 {self.type}→{target}({self.status})"

    def clean(self):
        """대상 3분기 강제 — 셋 중 정확히 하나만(DB CHECK 대신 앱 레벨)."""
        targets = [self.student_id, self.parent_id, self.user_id]
        if sum(1 for t in targets if t is not None) != 1:
            raise ValidationError("알림 대상은 학생/학부모/직원 중 정확히 하나만 지정한다.")
