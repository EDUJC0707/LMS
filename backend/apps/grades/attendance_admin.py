"""출결 입력 서비스 — SSOT 쓰기 + 파생 트리거 (PRD 3.1.6·3.1.4①·3.2.3, §4 배치 ③④).

담임의 출결 입력 한 번(Attendance upsert)이 파생 소비자 셋을 **동기로, 같은
트랜잭션 안에서** 갱신한다(Celery 보류 결정 — 태스크 없음):
  ① `출석`·`결석(현보)` 확정 → videos.VideoGrant(source=출석자동, 그 회차 주차, +7일)
  ② `결석` 확정 → boards.AbsenceCounseling 대기열 행(1차 통화 대상=학부모)
  ③ `결석(동보)` 확정 → videos.MakeupGrant(지급완료) + VideoGrant(source=동보)
     — 살아있는 신청이 붙은 `결석` 도 여기서 `결석(동보)` 로 올라가며 지급된다

**쓰기 문은 둘이다.** `apply_entries` 는 보내온 행만 도는 부분 upsert 이고
(OMR·현보·동보 체크가 쓴다), `confirm_session` 은 조교의 `출결 확정` 이다 —
같은 트리거를 **명단 전체**에 태우고 첫 확정에만 통지를 건다(FLOW 3-5·3-11).

**값집합 4종의 트리거 판정 근거** (2026-07-29 개편 — `지각` 제거, 결석 3분화).

| status | 복습영상 | 상담 대기열 | 동보 체인 |
|---|---|---|---|
| `출석` | 지급(출석자동) | — | — |
| `결석` | — | **생성** | 신청이 있으면 **지급완료**(→ `결석(동보)`) |
| `결석(동보)` | 동보 근거로 지급 | — | **지급완료** |
| `결석(현보)` | 지급(출석자동) | — | — |

- **상담 대기열은 `결석` 만.** 이 대기열은 "결석했다"의 대기열이 아니라 **"보강이
  정해지지 않았다"의 대기열**이다 — PRD 3.1.9·3.2.3 의 흐름이 `결석 → 전화상담 →
  보강 방법 확정` 이기 때문이다. `결석(동보)`·`결석(현보)` 는 담임이 찍는 순간
  보강 방법이 이미 확정(동영상)·완료(현장)된 상태라 전화할 사유가 없다. 통화
  이력이 남은 행은 결석 아님으로 정정돼도 보존한다(아래 정정 정책).
- **`결석(현보)` 도 복습영상을 준다.** 자동지급의 근거는 "그 주 수업을 실제로
  들었다"이지 출결 라벨 자체가 아니다(PRD 3.1.4 ① 이 `출석` 을 트리거로 삼는
  이유). 영상 보강(동보)조차 "출석생과 동일한 그 주 복습영상 권한"을 받는데
  (PRD 3.2.3) 현장에서 실제로 들은 학생을 빼면 앞뒤가 맞지 않는다. source 는
  `출석자동` 그대로 쓴다 — 이 값은 "담임의 출결 입력이 자동으로 낸 지급"을
  뜻하며 수동·동보·학생신청과 구분하는 축이고, 현보 지급도 정확히 그 축이다
  (부분 UQ `uq_video_grants_attendance` 도 출결 1건당 1행으로 그대로 성립).

**`결석(동보)` 와 학생 동보 신청 흐름의 겹침 정리 (2026-07-29).**
같은 사실("이 결석은 동영상으로 보강한다")에 입구가 셋이었다:
  (a) 담임의 출결 값 `결석(동보)`   (b) POST /api/admin/attendance/makeup(관리자 체크)
  (c) 학생·학부모 신청(videos.views)
셋을 그대로 두면 "출결은 `결석` 인데 동보만 지급된" / "동보로 찍혔는데 신청
레코드는 `신청` 인 채 남은" 갈린 상태가 생긴다. **끝 상태를 하나로 못 박는다** —
어느 입구로 들어와도 `attendance.status == 결석(동보)` **그리고** 그 결석에
`MakeupGrant(지급완료)` 1건 **그리고** 그 동보에 `VideoGrant(동보)` 1건:
  - (a) 는 트리거 ③ 이 지급 체인을 만든다. 그 결석에 **이미 신청 중인
    MakeupGrant 가 있으면 새로 만들지 않고 그 행을 지급완료로 전이**한다 —
    담임이 동보로 찍은 것이 곧 그 신청의 확정이다(source 는 신청 경로 그대로
    보존 — 누가 시작했는지가 감사 이력이다).
  - (b) 는 `grant_makeup()` 이 **출결 값을 `결석(동보)` 로 올린 뒤** 같은 트리거를
    태운다. 즉 (a) 의 축약일 뿐 별도 경로가 아니다.
  - (c) 도 `promote_to_makeup_absence()` 로 출결을 올린다(videos.views). **승인
    단계는 없다**(FLOW 3-4) — 결석이 이미 확정돼 있으면 신청받는 자리에서 바로,
    아직이면 트리거 ③ 이 결석 확정 시점에 낸다.

**원자성 판단 — 출결 저장과 트리거를 한 트랜잭션으로 묶는다.**
근거: 출결은 SSOT(grades.Attendance 계약)이고 지급·대기열은 그 파생이다.
"출결은 저장됐는데 지급이 누락된" 부분 성공은 SSOT 와 파생의 불일치 —
사본 금지 원칙(key_considerations §6)이 막으려는 바로 그 상태다. 트리거는
순수 DB 쓰기뿐이라(외부 API 없음 — DRM 반영은 sync_status 후순위, PRD 3.1.3)
실패는 곧 DB 장애이며, 그 경우 출결 저장도 함께 롤백해 관리자가 화면에서
재시도하는 편이 안전하다(수업 당일 현장 대응 불가 전제 — key_considerations §5).

**퇴원생은 명단에 남기되 입력 대상에서 뺀다** (2026-07-29 사용자 지시 "한번에
찍고 그 이후에는 이미 퇴원함"). 출결 값집합에 `퇴원` 을 넣지 않는 결정은 그대로다
(퇴원은 회차마다 바뀌는 게 아니라 한 번 일어나는 사건이라 회차별로 찍게 하면
"3회차는 퇴원인데 5회차는 출석" 같은 모순이 저장된다 — 모델 계약). 대신 화면에서
5종처럼 보이도록 명단에 행을 남기고 `is_withdrawn` 을 실어 보낸다. 그 행에는
출결 레코드를 만들지 않으며(쓰기는 400) 집계에서도 별도 칸으로 뺀다.

**정정 시나리오 정책** (PRD 3.1.1 발송 후 수정 가능 — 정정은 언제든 온다):
- 출석 → 결석 계열: 자동지급(출석자동) revoke(revoked_at 스탬프 — 행 보존, 이력).
- 결석 계열 → 출석: revoke 된 자동지급을 **재활성**(revoked_at 해제 + 지급/만료
  재산정). 부분 UQ(uq_video_grants_attendance)가 출석 1건당 1행을 강제하므로
  행 복제가 아니라 재활성이 계약에 맞는 형태다. `결석(현보)` 도 같은 축을 쓴다.
- 결석(동보) → 다른 값: 동보 지급(VideoGrant source=동보)을 revoke 한다. 다시
  `결석(동보)` 로 돌아오면 재활성(부분 UQ `uq_video_grants_makeup` — 동보 1건당
  지급 1행). MakeupGrant 행 자체는 `지급완료` 로 남긴다 — 누가 언제 동보를
  확정했는지는 감사 이력이고, 권한을 실제로 끄는 것은 VideoGrant 쪽이다.
- 결석 → 결석 아님(출석·동보·현보): 대기열 행 중 **사람 손이 닿지 않은 행만** 삭제
  (status=대기 AND called_at IS NULL). 통화 이력이 남은 행(완료·미연결,
  called_at 존재)은 감사 이력이므로 보존한다. 삭제 근거: 대기열은 SSOT 파생
  데이터라 잘못된 대기 행을 남기면 비결석 학생 학부모에게 전화가 나간다.
  "파괴적 작업은 수동"(key_considerations §5) 원칙과의 관계 — 이 삭제는
  관리자의 수동 정정 행위에 종속된 파생 정리이지 독립 자동화가 아니다.
- 정정 추적: 값이 실제로 바뀐 경우에만 updated_at 을 앱 레이어에서 채운다
  (모델 계약 — auto_now 금지, 값 존재 = 정정된 레코드). 동일 값 재저장은
  정정이 아니며 지급 만료도 연장하지 않는다(멱등).

중복 백스톱: 자동지급은 부분 UQ(attendance), 동보 지급은 부분 UQ(makeup)가
DB 레벨에서 이중 생성을 차단한다(get_or_create 패턴 — 조회 후 없을 때만 생성,
동시성 충돌은 UQ 가 최종 방어).

시간 의미론: 기준 시각은 요청당 timezone.now() 1회로 고정(2차 슬라이스 home
선례 — Asia/Seoul). 만료 = 지급 + 7일 기본(2026-07-15 회의, 관리자 설정 변경은
후순위 — 기본값 산정은 앱 레이어 몫이라는 VideoGrant 모델 계약 이행).
"""
from django.db import models, transaction
from django.utils import timezone

from apps.accounts.models import ParentStudent, Student
from apps.boards.models import AbsenceCounseling
from apps.curriculum.models import CourseEnrollment, class_name_subquery
from apps.notifications.models import Notification
from apps.notifications.sending import queue as queue_notification

# GRANT_DURATION(시청 기간 기본 7일)은 동보 지급 체인과 공유하는 단일 기본값 —
# videos.makeup 이 원천이다(4차 슬라이스 공용 서비스 추출).
from apps.videos.makeup import (
    GRANT_DURATION,
    complete_makeup,
    held_video_ids,
    published_videos_of,
)
from apps.videos.models import MakeupGrant, VideoGrant

from .models import Attendance, ClassSession

# --- 조회 ----------------------------------------------------------------


def load_session(session_id):
    """회차 + 주차·강좌 1쿼리 로드. 없으면 None."""
    return (
        ClassSession.objects.select_related("course_week__course")
        .filter(pk=session_id)
        .first()
    )


def load_roster(session):
    """회차 명단 = 그 주차 강좌의 활성 수강생(`수강`) — **퇴원생도 남긴다**.

    예비등록생은 포함한다 — 1주차 실제 출석이 '등록' 전환의 근거(PRD 3.1.5·
    3.1.6)이므로 명단에 있어야 첫 출석을 입력할 수 있다.

    퇴원생은 2026-07-29 부터 **제외하지 않는다**(구 동작: `.exclude(퇴원)`).
    담임 화면이 4종 값 + 퇴원 표시로 5종처럼 보여야 하기 때문이며, 대신 그
    행은 표시 전용이다(`is_entry_target` 이 False → 쓰기 400). 주차 미매핑
    회차는 명단 산정 불가([]) — 쓰기는 뷰에서 400 처리.

    **반이 붙은 회차는 그 반만 본다**(2026-08-18). 같은 커리를 목반·화반이
    같이 듣기 때문에(FLOW 1-1) 커리로만 거르면 목반 출결표에 화반 학생이
    뜬다. 반이 없는 옛 회차는 종전대로 커리 전체다.

    **이 회차에 출결 행이 있는 학생은 수강이 없어도 명단에 든다**(2026-08-19).
    두 갈래로 그렇게 된다.

    - **현보**(FLOW 3-4) — 이 반 수강생이 아닌데 여기 와서 수업을 들었다.
      출결표에 보여야 조교가 그 자리에서 왜 이 학생이 있는지 안다.
      반 칸에는 원래 반이 뜬다(이 커리의 반을 읽으므로 — 아래 annotate)
    - **반 이동**(FLOW 3-9) — 명단이 지금 수강에서 나오므로 반을 옮기면 옛 반의
      지난 출결표에서 그 줄이 통째로 사라진다. 기록은 옛 반에 남는데 그것을 볼
      자리가 없어지는 셈이다
    """
    if session.course_week is None:
        return []
    course = session.course_week.course
    scope = (
        models.Q(course_enrollments__klass=session.klass_id)
        if session.klass_id
        else models.Q(course_enrollments__course=course)
    )
    return list(
        Student.objects.filter(
            (scope & models.Q(course_enrollments__status=CourseEnrollment.Status.ENROLLED))
            | models.Q(attendances__session=session)
        )
        .distinct()
        .select_related("user")
        # 반은 **이 회차 커리의 반**이다 — 다른 커리를 같이 듣는 학생이 있어도
        # 출결표에는 그 반이 뜨면 안 된다(학생↔반 N:M — FLOW 1-1).
        .annotate(class_name=class_name_subquery(course_id=course.course_id))
        .order_by("student_id")
    )


def is_entry_target(student):
    """출결을 입력할 수 있는 행인가 — 퇴원생은 표시만 하고 레코드를 만들지 않는다."""
    return student.enrollment_status != Student.EnrollmentStatus.WITHDRAWN


def entry_target_ids(roster):
    """명단 중 출결 입력 대상 student_id 목록(퇴원 제외) — 뷰의 검증 준거."""
    return [s.student_id for s in roster if is_entry_target(s)]


def withdrawn_ids(roster):
    """명단 중 퇴원 행의 student_id 집합 — 뷰가 오류 문구를 가르는 데 쓴다."""
    return {s.student_id for s in roster if not is_entry_target(s)}


def load_attendance_map(session, student_ids):
    """회차·학생들의 기존 출결 1쿼리 로드 — {student_id: Attendance}."""
    return {
        a.student_id: a
        for a in Attendance.objects.filter(session=session, student_id__in=student_ids)
    }


# --- 페이로드 조립 --------------------------------------------------------


def session_block(session):
    """회차 요약 블록 — 목록·상세·PUT 응답 공용."""
    week = session.course_week
    return {
        "session_id": session.session_id,
        "session_date": session.session_date.isoformat(),
        "confirmed_at": (
            timezone.localtime(session.confirmed_at).isoformat()
            if session.confirmed_at
            else None
        ),
        "session_no": session.session_no,
        "target_grade": session.target_grade,
        "memo": session.memo,
        "week_no": week.week_no if week else None,
        "course": (
            {"course_id": week.course.course_id, "name": week.course.name} if week else None
        ),
    }


def build_detail_payload(session, roster, attendance_by_student):
    """상세·PUT 공용 응답 — 명단 + 출결 값 + 집계(프런트 재조회 불필요).

    **응답 계약** (2026-07-29 개정 — 퇴원 행 포함으로 형태가 바뀌었다):

        {
          "session": {...},
          "students": [
            {
              "student_id": 1, "name": "김서연",
              "login_id": "김서연0001",     # 원번(유일). 화면에 보이는 번호
              "matching_key": "김서연0001", # 지면 대조 전용(중복 가능)
              "current_class": "수요반", "enrollment_status": "등록",
              "is_withdrawn": false,      # true = 표시 전용 행(출결 입력칸 없음)
              "attendance_id": 12|null,   # 동보 즉시 지급 API 의 body 키
              "attendance": {"status","exam_taken","marked_at","updated_at"}|null
            }, ...
          ],
          "summary": {"출석":n,"결석":n,"결석(동보)":n,"결석(현보)":n,
                      "미입력":n,"퇴원":n,"total":n}
        }

    - `students` 에는 **퇴원생도 들어온다**. `is_withdrawn` 이 true 인 행은
      출결 입력칸 대신 `퇴원` 을 표시하고 PUT 대상에서 뺀다(보내면 400).
    - `summary` 는 **입력 대상만** 센다: 값 5종의 합이 `total` 과 같고, 퇴원생은
      그 밖의 `퇴원` 칸에만 잡힌다. 퇴원생을 `미입력` 에 넣으면 "아직 n명
      남았다"가 영원히 0이 되지 않는 거짓 신호가 된다.
    - `미입력` 칸은 **레코드 없는 학생 + 명시적 `미입력` 행**을 합친 수다. 둘은
      같은 뜻인데(FLOW 3-4) 명시적 행을 빼면 조교가 해제한 만큼 "아직 n명" 이
      적게 떠서 다 봤다고 착각하게 된다.
    - `attendance_id` 는 동보 즉시 지급(POST /api/admin/attendance/makeup)의
      body 키다 — 명단에서 결석 학생에게 바로 지급하려면 기존 출결의 PK 가
      응답에 있어야 한다(2026-07-28 보강). 미입력 학생은 null(키는 항상 존재).
    """
    students = []
    counts = {status: 0 for status in Attendance.Status.values}
    withdrawn = 0
    for student in roster:
        att = attendance_by_student.get(student.student_id)
        entry_target = is_entry_target(student)
        if entry_target and att is not None:
            counts[att.status] += 1
        if not entry_target:
            withdrawn += 1
        students.append(
            {
                "student_id": student.student_id,
                "name": student.user.name if student.user else None,
                "login_id": student.user.login_id if student.user else None,
                "matching_key": student.matching_key,
                "current_class": student.class_name,
                "enrollment_status": student.enrollment_status,
                "is_withdrawn": not entry_target,
                "attendance_id": att.id if att is not None else None,
                "attendance": _attendance_block(att),
            }
        )
    total = len(roster) - withdrawn
    summary = dict(counts)
    summary["미입력"] = (
        total - sum(counts.values()) + counts[Attendance.Status.UNENTERED]
    )
    summary["퇴원"] = withdrawn
    summary["total"] = total
    return {"session": session_block(session), "students": students, "summary": summary}


def _attendance_block(att):
    if att is None:
        return None
    return {
        "status": att.status,
        "exam_taken": att.exam_taken,
        "marked_at": timezone.localtime(att.created_at).isoformat() if att.created_at else None,
        "updated_at": timezone.localtime(att.updated_at).isoformat() if att.updated_at else None,
    }


# --- SSOT 쓰기 + 트리거 ---------------------------------------------------


def apply_entries(session, entries, actor, roster_ids):
    """검증 완료된 entries 를 upsert 하고 파생 트리거를 동기 실행한다.

    한 트랜잭션(모듈 docstring 의 원자성 판단). 반환: (attendance_map, triggers).
    - attendance_map 은 **명단 전체**의 최신 출결({student_id: Attendance}) —
      부분 upsert 응답도 전체 명단 상태를 담아야 하므로(재조회 불필요 계약)
      트랜잭션 안에서 한 번에 로드해 upsert 를 겹쳐 쓴다.
    - triggers 는 응답용 카운터 — 관리자 화면이 "지급 n건" 피드백을 재조회
      없이 표시할 수 있게 한다.
    """
    now = timezone.now()
    triggers = empty_triggers()
    student_ids = [entry["student_id"] for entry in entries]
    with transaction.atomic():
        att_map = load_attendance_map(session, roster_ids)
        for entry in entries:
            _upsert_row(session, entry, att_map, actor, now)
        touched = [att_map[sid] for sid in student_ids]
        _run_triggers(session, touched, actor, now, triggers)
    return att_map, triggers


def confirm_session(session, entries, actor, roster):
    """`출결 확정` — 손으로 고친 값을 저장하고 **이제 내보낸다**(FLOW 3-5·3-11).

    저장 버튼이 아니다. 출결표는 OMR 이 다시 돌 때마다 스스로 바뀌고
    (`scoring.mark_present` 가 같은 upsert 를 탄다), 이 함수가 뜻하는 것은
    "내보낸다" 하나다. 그래서 **손댄 것이 없어도 할 일이 남는다**:

    - 트리거를 **명단 전체**에 태운다. `apply_entries` 처럼 보내온 행만 돌면
      OMR 이 찍어 준 학생(조교가 손댈 것이 없어 entries 에 없는 학생)의 영상이
      영영 안 나간다. 이미 가진 학생은 트리거가 알아서 건너뛴다(FLOW 3-5).
    - **문자는 처음 확정할 때만** 나간다. `confirmed_at` 이 비어 있는지로 가르며
      날짜로 판정하지 않는다 — 누른 그 시점이 곧 부여 시점이다(FLOW 3-11).

    확정은 잠금이 아니다. 뒤에 출결이 또 바뀌면 다시 눌러 영상을 채운다.
    """
    now = timezone.now()
    triggers = empty_triggers()
    roster_ids = entry_target_ids(roster)
    with transaction.atomic():
        att_map = load_attendance_map(session, roster_ids)
        for entry in entries:
            _upsert_row(session, entry, att_map, actor, now)
        _run_triggers(session, list(att_map.values()), actor, now, triggers)
        # 조건부 UPDATE 로 첫 확정을 가른다 — 읽고 나서 쓰면 두 조교가 동시에
        # 누를 때 둘 다 "처음"이 돼 문자가 두 번 나간다.
        if ClassSession.objects.filter(pk=session.pk, confirmed_at__isnull=True).update(
            confirmed_at=now
        ):
            session.confirmed_at = now
            triggers["notifications_queued"] = _notify_confirmed(session, roster, att_map)
    return att_map, triggers


def _notify_confirmed(session, roster, att_map):
    """출결 통지 — 그 주에 관한 것을 **한 통으로** 학생·학부모에게(FLOW 3-11 ④).

    본문은 비워 둔다. 카카오 템플릿이 사전 승인제라 문구가 확정돼야 채울 수 있고
    (FLOW 3-11 고려사항), 승인된 템플릿 코드가 아직 없어 운영에서는 발송이 영구
    실패로 닫힌다 — 이 자리가 하는 일은 **나갈 것을 큐에 남기는 것**뿐이다.

    `미입력` 은 뺀다(FLOW 3-4). 아무도 안 본 학생의 학부모에게 그 주 통지가
    나가면 안 된다 — 안 찍은 것과 없었던 것을 구별하는 것이 그 값의 존재 이유다.

    **결석 계열도 뺀다**(FLOW 3-11, 2026-08-19). 결석한 집에는 다음날 조교가
    전화를 걸므로(3-12) 문자가 먼저 가면 같은 이야기를 두 번 하는 셈이다.
    그래서 이 통지에 담기는 것도 온 학생 기준이다 — "안 왔다" 를 적을 자리가 없다.
    """
    sent_to = {Attendance.Status.PRESENT}
    targets = [
        student
        for student in roster
        if is_entry_target(student)
        and att_map.get(student.student_id) is not None
        and att_map[student.student_id].status in sent_to
    ]
    parents = {}
    for link in ParentStudent.objects.filter(student__in=targets).select_related("parent"):
        parents.setdefault(link.student_id, []).append(link.parent)
    queued = 0
    for student in targets:
        recipients = [{"student": student}]
        recipients += [{"parent": p} for p in parents.get(student.student_id, [])]
        for recipient in recipients:
            queue_notification(
                type=Notification.Type.REPORT,
                channel=Notification.Channel.KAKAO,
                title="출결 통지",
                ref_type="class_sessions",
                ref_id=session.session_id,
                **recipient,
            )
            queued += 1
    return queued


def empty_triggers():
    """응답용 트리거 카운터 초기값 — 응답 형태가 값 유무에 따라 흔들리지 않게 한다.

    `video_grants_*` 는 경로(출석자동·동보)를 가리지 않고 이번 저장이 만든/회수한/
    되살린 시청 권한 수다 — 화면이 "복습영상 n건 지급"으로 옮기는 값이므로 학생이
    체감하는 단위(권한)와 같아야 한다. `makeups_granted` 는 그중 동보 확정 건수다.

    `notifications_queued` 는 확정 경로에서만 0 이 아니다 — 처음 확정할 때 한 번
    쌓이고 두 번째부터는 0 이다(FLOW 3-11).
    """
    return {
        "video_grants_created": 0,
        "video_grants_revoked": 0,
        "video_grants_reactivated": 0,
        "counselings_created": 0,
        "counselings_removed": 0,
        "makeups_granted": 0,
        "notifications_queued": 0,
    }


def _run_triggers(session, attendances, actor, now, triggers):
    """파생 트리거 ①②③ 을 정해진 순서로 태운다(호출측이 트랜잭션을 소유).

    순서가 의미를 갖는 지점은 없다 — 셋은 서로 다른 표를 건드리고 같은 출결
    스냅샷만 읽는다. 한 곳에 모아 둔 이유는 출결 값이 바뀌는 **모든 경로**가
    같은 파생을 태우게 하기 위함이다(담임 입력 · 관리자 동보 체크 · 신청 승인).
    """
    _sync_video_grants(session, attendances, actor, now, triggers)
    _sync_makeup_grants(attendances, actor, now, triggers)
    _sync_counseling_queue(attendances, triggers)


def _upsert_row(session, entry, att_map, actor, now):
    """출결 1행 upsert — 최초 입력은 updated_at NULL, 실변경만 정정 스탬프."""
    sid = entry["student_id"]
    att = att_map.get(sid)
    if att is None:
        att_map[sid] = Attendance.objects.create(
            session=session,
            student_id=sid,
            status=entry["status"],
            exam_taken=entry.get("exam_taken"),
            marked_by=actor,
        )
        return
    changed = att.status != entry["status"]
    if "exam_taken" in entry and att.exam_taken != entry["exam_taken"]:
        changed = True
    if not changed:
        return  # 동일 값 재저장은 정정이 아니다(멱등 — updated_at 불변)
    att.status = entry["status"]
    if "exam_taken" in entry:
        att.exam_taken = entry["exam_taken"]
    att.marked_by = actor
    att.updated_at = now
    att.save(update_fields=["status", "exam_taken", "marked_by", "updated_at"])


#: 출결 근거 복습영상 지급(source=출석자동)이 활성인 값들 — 모듈 docstring 의
#: 판정표 ①. `결석(현보)` 가 여기 있는 근거도 같은 곳에 적혀 있다.
_REVIEW_VIDEO_STATUSES = frozenset(
    {Attendance.Status.PRESENT, Attendance.Status.ABSENT_ONSITE}
)


def _sync_video_grants(session, attendances, actor, now, triggers):
    """트리거 ① — 출결 근거 자동지급은 `출석`·`결석(현보)` 인 동안만 활성.

    `결석(현보)` 를 포함하는 근거는 모듈 docstring(그 주 수업을 실제로 들었으므로
    출석과 동등). `결석(동보)` 는 여기가 아니라 트리거 ③ 이 동보 근거로 지급한다 —
    한 결석에 출결 근거·동보 근거 지급이 겹치면 같은 주차 권한이 2행이 된다.
    기존 지급 1쿼리 로드 후 상태별 생성/재활성/revoke(모듈 docstring 정책).
    """
    videos = published_videos_of(session.course_week)
    grant_map = {
        (g.attendance_id, g.video_id): g
        for g in VideoGrant.objects.filter(attendance_id__in=[a.id for a in attendances])
    }
    # 이미 가진 영상은 건너뛴다(FLOW 3-5) — 이 출석 근거로 만든 행이 아니라
    # **학생이 지금 들고 있는 권한**을 본다. 같은 주차 회차가 둘 이상이거나
    # 동보로 이미 받은 영상이 여기서 걸린다.
    held = held_video_ids(
        [a.student_id for a in attendances],
        videos,
        now,
        exclude_attendances=[a.id for a in attendances],
    )
    created = []
    for att in attendances:
        if att.status in _REVIEW_VIDEO_STATUSES:
            for video in videos:
                grant = grant_map.get((att.id, video.video_id))
                if grant is None:
                    if (att.student_id, video.video_id) in held:
                        continue
                    created.append(
                        VideoGrant(
                            student_id=att.student_id,
                            video=video,
                            source=VideoGrant.Source.ATTENDANCE_AUTO,
                            attendance=att,
                            granted_by=actor,
                            granted_at=now,
                            expires_at=now + GRANT_DURATION,
                        )
                    )
                    triggers["video_grants_created"] += 1
                elif grant.revoked_at is not None:
                    grant.revoked_at = None
                    grant.granted_at = now
                    grant.expires_at = now + GRANT_DURATION
                    grant.granted_by = actor
                    grant.save(
                        update_fields=[
                            "revoked_at",
                            "granted_at",
                            "expires_at",
                            "granted_by",
                        ]
                    )
                    triggers["video_grants_reactivated"] += 1
        else:
            # 출석 계열이 아니게 되면 이 출석 근거의 자동지급을 **전부** 회수한다.
            # 영상 단위가 된 뒤로 한 출석이 여러 행을 낳으므로 하나만 끄면 남는다.
            for (att_id, _video_id), grant in grant_map.items():
                if (
                    att_id == att.id
                    and grant.source == VideoGrant.Source.ATTENDANCE_AUTO
                    and grant.revoked_at is None
                ):
                    grant.revoked_at = now
                    grant.save(update_fields=["revoked_at"])
                    triggers["video_grants_revoked"] += 1
    if created:
        VideoGrant.objects.bulk_create(created)


def _sync_makeup_grants(attendances, actor, now, triggers):
    """트리거 ③ — 동보 지급 확정 (2026-07-29 입구 단일화, 2026-08-18 승인 제거).

    담임이 `결석(동보)` 를 찍는 순간 MakeupGrant `지급완료` + VideoGrant(동보)까지
    간다. 학생 신청을 기다리지 않는 근거는 모듈 docstring — 담임이 찍는 값과 학생
    신청이 같은 사실을 가리키므로 둘을 한 레코드로 합친다:
      - 그 결석에 아직 MakeupGrant 가 없으면 `관리자체크` 로 새로 만든다.
      - **신청 중인 행이 있으면 그 행을 지급완료로 전이**한다(새로 만들지 않는다).
        source 는 신청 경로 그대로 둔다 — 누가 시작했는지가 감사 이력이다.
      - 이미 지급완료면 아무것도 하지 않는다(멱등 — 만료를 연장하지 않는다).

    **`결석` 도 여기서 지급된다 — 살아있는 신청이 붙어 있을 때만**(FLOW 3-4).
    지급 조건은 신청 + 결석 확인 둘뿐이고 순서는 상관없으므로, 미리 신청해 둔
    결석이 출결표 저장으로 확정되는 이 자리가 "신청이 먼저인" 쪽의 지급 시점이다.
    승인 단계는 없앴다 — 결석했다는 근거가 이미 출결에 있다. 지급과 함께 출결 값을
    `결석(동보)` 로 올린다(입구 셋의 끝 상태 단일화). 상담 대기열 정리는 바로 뒤에
    도는 트리거 ② 가 그 값을 보고 한다.

    `결석(동보)` 가 아니게 정정되면 동보 지급을 revoke, 되돌아오면 재활성한다.
    """
    makeup_by_att = {}
    for makeup in MakeupGrant.objects.filter(
        attendance_id__in=[a.id for a in attendances]
    ).order_by("makeup_id"):
        # 같은 결석에 거절 후 재신청이 쌓일 수 있다 — 지급완료 행이 있으면 그것이
        # 사실이고(부분 UQ 가 지급 1건을 보장), 없으면 최신 행을 재사용 대상으로 본다.
        current = makeup_by_att.get(makeup.attendance_id)
        if current is None or current.status != MakeupGrant.Status.GRANTED:
            makeup_by_att[makeup.attendance_id] = makeup
    # 동보 1건이 **영상 수만큼** VideoGrant 를 낳는다(2026-08-04 지급 단위 개정).
    # makeup_id 를 단일 키로 잡으면 행 하나만 남고 나머지가 버려져, 정정 시
    # 한 영상만 회수되고 **남은 영상은 학생에게 열린 채로 남는다.**
    grant_by_makeup = {}
    if makeup_by_att:
        for g in VideoGrant.objects.filter(
            makeup_id__in=[m.makeup_id for m in makeup_by_att.values()]
        ):
            grant_by_makeup.setdefault(g.makeup_id, []).append(g)
    for att in attendances:
        makeup = makeup_by_att.get(att.id)
        # 신청 + 결석 확인이 둘 다 찼다 — 승인 없이 여기서 나간다(FLOW 3-4).
        if (
            att.status == Attendance.Status.ABSENT
            and makeup is not None
            and makeup.status == MakeupGrant.Status.REQUESTED
        ):
            _mark_makeup_absence(att, actor, now)
        if att.status == Attendance.Status.ABSENT_MAKEUP:
            if makeup is None:
                makeup = MakeupGrant.objects.create(
                    student_id=att.student_id,
                    attendance=att,
                    source=MakeupGrant.Source.ADMIN_CHECK,
                    requested_by=actor,
                )
            if makeup.status != MakeupGrant.Status.GRANTED:
                # 카운터는 **행 수**다 — empty_triggers 계약이 "학생이 체감하는
                # 단위(권한)와 같아야 한다"고 못박는다. 1 을 더하면 영상 3개를
                # 지급하고도 응답이 1 이라 화면이 거짓을 말한다.
                triggers["makeups_granted"] += 1
                triggers["video_grants_created"] += len(
                    complete_makeup(makeup, actor, now)
                )
                continue
            for grant in grant_by_makeup.get(makeup.makeup_id, []):
                if grant.revoked_at is None:
                    continue
                grant.revoked_at = None
                grant.granted_at = now
                grant.expires_at = now + GRANT_DURATION
                grant.granted_by = actor
                grant.save(
                    update_fields=["revoked_at", "granted_at", "expires_at", "granted_by"]
                )
                triggers["video_grants_reactivated"] += 1
            continue
        if makeup is None or makeup.status != MakeupGrant.Status.GRANTED:
            continue
        # 정정 시에도 그 동보의 지급을 **전부** 회수한다(위 주석 참조).
        for grant in grant_by_makeup.get(makeup.makeup_id, []):
            if grant.revoked_at is None:
                grant.revoked_at = now
                grant.save(update_fields=["revoked_at"])
                triggers["video_grants_revoked"] += 1


def _sync_counseling_queue(attendances, triggers):
    """트리거 ② — **보강 미정 결석**(`결석`)만 상담 대기열(PRD §4 배치 ④, 동기).

    `결석(동보)`·`결석(현보)` 는 대기열 대상이 아니다 — 이 대기열은 "결석했다"가
    아니라 **"보강이 정해지지 않았다"**의 대기열이라서다(근거는 모듈 docstring).
    결석 1건당 대기열 1행(기존 행 존재 시 상태 불문 미생성 — 중복 금지).
    1차 통화 대상=학부모(PRD 3.1.9). 대기열 대상 아님으로 정정 시 미통화 대기
    행만 삭제(모듈 docstring 정책).
    """
    existing = {
        c.attendance_id: c
        for c in AbsenceCounseling.objects.filter(
            attendance_id__in=[a.id for a in attendances]
        )
    }
    removable = []
    for att in attendances:
        row = existing.get(att.id)
        if att.status == Attendance.Status.ABSENT:
            if row is None:
                AbsenceCounseling.objects.create(
                    student_id=att.student_id,
                    attendance=att,
                    target=AbsenceCounseling.Target.PARENT,
                    status=AbsenceCounseling.Status.PENDING,
                )
                triggers["counselings_created"] += 1
        elif (
            row is not None
            and row.status == AbsenceCounseling.Status.PENDING
            and row.called_at is None
        ):
            removable.append(row.counsel_id)
    if removable:
        AbsenceCounseling.objects.filter(counsel_id__in=removable).delete()
        triggers["counselings_removed"] += len(removable)


# --- 동보(관리자 체크) ----------------------------------------------------


def grant_makeup(attendance, actor):
    """관리자 동보 체크 — **출결을 `결석(동보)` 로 올리고** 지급 체인을 태운다.

    2026-07-29 개편 전에는 MakeupGrant 만 만들었다. 그러면 출결은 `결석` 인데
    동보만 지급된 상태가 남아 **출결 SSOT 만 보고는 이 학생이 동보인지 알 수
    없었다.** 이제 이 엔드포인트는 담임이 `결석(동보)` 를 찍는 것의 축약이며,
    지급·상담 대기열 정리는 같은 트리거(_run_triggers)를 그대로 탄다.
    중복은 뷰의 지급완료 선재 검사 + 부분 UQ(uq_video_grants_makeup)가 이중 방어.
    """
    now = timezone.now()
    with transaction.atomic():
        promote_to_makeup_absence(attendance, actor, now)
        # 살아있는 신청이 있으면 그 행을 승인한다(새로 만들지 않는다 — 트리거 ③과
        # 같은 규칙). 뷰가 지급완료 선재 검사를 마쳤으므로 여기 오는 행은 신청·승인
        # 상태이거나 아예 없다. 거절된 행은 재사용하지 않는다(이력이므로).
        makeup = (
            MakeupGrant.objects.filter(attendance=attendance)
            .exclude(status=MakeupGrant.Status.REJECTED)
            .order_by("makeup_id")
            .first()
        )
        if makeup is None:
            makeup = MakeupGrant.objects.create(
                student_id=attendance.student_id,
                attendance=attendance,
                source=MakeupGrant.Source.ADMIN_CHECK,
                requested_by=actor,
            )
        grants = complete_makeup(makeup, actor, now)
    return makeup, grants


def _mark_makeup_absence(attendance, actor, now):
    """출결 값만 `결석(동보)` 로 올린다 — 상담 대기열 정리는 호출측 몫.

    트리거 ③ 안에서는 바로 뒤에 트리거 ② 가 도므로 여기서 대기열을 건드리면
    같은 삭제를 두 번 계산하게 된다(응답 카운터가 어긋난다).
    """
    if attendance.status == Attendance.Status.ABSENT_MAKEUP:
        return False
    attendance.status = Attendance.Status.ABSENT_MAKEUP
    attendance.marked_by = actor
    attendance.updated_at = now
    attendance.save(update_fields=["status", "marked_by", "updated_at"])
    return True


def promote_to_makeup_absence(attendance, actor, now):
    """동보 지급이 확정된 결석의 출결 값을 `결석(동보)` 로 올린다.

    관리자 동보 체크(grant_makeup)와 학생·학부모 신청이 호출한다 — 지급은 났는데
    출결은 `결석` 인 갈린 상태를 남기지 않기 위함(모듈 docstring 의 입구 단일화).
    지급 체인 자체는 호출측이 이미 태웠으므로 여기서는 출결 값과 **상담 대기열
    정리**만 맞춘다. 트랜잭션은 호출측 소유.
    """
    if _mark_makeup_absence(attendance, actor, now):
        _sync_counseling_queue([attendance], empty_triggers())


# --- 현보(다른 반 학생이 여기로 보강을 왔다) ------------------------------


def origin_session(session, student):
    """현보로 온 학생의 **원래 반 같은 주차 회차**. 못 찾으면 None.

    **반의 주차가 곧 회차다**(FLOW 1-1 — 주 1회라 1:1). 그래서 원래 반만 알면
    회차는 `week_no` 로 바로 집힌다: `UQ(klass, week_no)` 가 반마다 그 주차를
    하나로 못박으므로 고를 것이 없다. 날짜로 찾지 않는다 — 목반과 화반은 같은
    주차라도 날짜가 다르고(그래서 현보가 성립한다), 휴강으로 밀리면 더 벌어진다.

    원래 반은 **이 회차 커리를 듣는 다른 반**이다. 학생↔반이 N:M 이라(FLOW 1-1)
    수능 반과 내신 반을 같이 듣는 학생이 있는데, 현보는 같은 커리의 다른 요일로
    가는 것이므로 커리로 좁히면 갈래가 하나만 남는다. 그 커리를 아예 안 듣는
    학생이면 현보가 아니라 새 학생이다(FLOW 3-4 의 두 갈래 중 조교의 판단).
    """
    if session.week_no is None or session.course_week is None:
        return None
    origin_class_id = (
        CourseEnrollment.objects.filter(
            student=student,
            course=session.course_week.course,
            status=CourseEnrollment.Status.ENROLLED,
        )
        .exclude(klass_id=session.klass_id)
        .order_by("enrollment_id")
        .values_list("klass_id", flat=True)
        .first()
    )
    if origin_class_id is None:
        return None
    return ClassSession.objects.filter(
        klass_id=origin_class_id, week_no=session.week_no
    ).first()


def mark_onsite(session, student, origin, actor):
    """현보 확정 — 방문한 반에 `출석`, 원래 반에 `결석(현보)` (FLOW 3-4).

    **행은 두 반에 다 생긴다.** 방문한 반은 실제로 와서 들었으니 `출석` 이고,
    원래 반은 그 수업에 안 왔으니 결석이되 보강이 끝났으므로 `결석(현보)` 다.
    원래 반을 그냥 `결석` 으로 두면 결석생 연락 대기열이 생겨 보강을 이미 끝낸
    학생의 학부모에게 전화가 나간다(FLOW 3-12).

    **영상은 그래도 한 번만 나간다.** 방문한 반을 먼저 저장하고 원래 반이 뒤를
    잇는데, 뒤쪽의 `_sync_video_grants` 가 `held_video_ids` 로 **학생이 지금 들고
    있는 권한**을 보므로 앞에서 나간 그 주차 영상을 건너뛴다(FLOW 3-5). 반 평균은
    출결이 아니라 `Score` 에서 세고 그쪽은 시험당 학생당 한 줄이다.

    두 반의 트리거 카운터는 합쳐서 돌려준다 — 화면이 "복습영상 n건 지급"으로
    옮기는 값이라 한쪽만 실으면 거짓을 말한다.
    """
    entry = [{"student_id": student.pk, "status": Attendance.Status.PRESENT}]
    with transaction.atomic():
        _, triggers = apply_entries(session, entry, actor, [student.pk])
        _, origin_triggers = apply_entries(
            origin,
            [{"student_id": student.pk, "status": Attendance.Status.ABSENT_ONSITE}],
            actor,
            [student.pk],
        )
    for key, value in origin_triggers.items():
        triggers[key] += value
    return triggers


# --- 퇴원 처리 -------------------------------------------------------------


def withdraw_student(student, actor, now, reason=None):
    """퇴원 처리 (PRD 3.1.6) — 출결 화면에서 담임이 누른다.

    출결 값집합에 `퇴원` 을 넣지 않기로 한 결정(모델 계약)의 짝이다: 값 대신
    **학생 생애주기 상태**를 한 번 바꾸고, 이후 회차 명단에서는 표시 전용 행으로
    자동으로 뜬다("한번에 찍고 그 이후에는 이미 퇴원함" — 2026-07-29 사용자).

    이미 퇴원인 학생은 **덮어쓰지 않는다**(멱등) — 최초 퇴원 시각·처리자가
    감사 이력이므로 재요청이 그것을 지우면 안 된다.
    """
    if student.enrollment_status == Student.EnrollmentStatus.WITHDRAWN:
        return student
    student.enrollment_status = Student.EnrollmentStatus.WITHDRAWN
    student.withdrawn_at = now
    student.withdrawn_by = actor
    student.withdrawn_reason = reason or None
    student.save(
        update_fields=[
            "enrollment_status",
            "withdrawn_at",
            "withdrawn_by",
            "withdrawn_reason",
        ]
    )
    return student
