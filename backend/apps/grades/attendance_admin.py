"""출결 입력 서비스 — SSOT 쓰기 + 파생 트리거 (PRD 3.1.6·3.1.4①·3.2.3, §4 배치 ③④).

담임의 출결 입력 한 번(Attendance upsert)이 파생 소비자 둘을 **동기로, 같은
트랜잭션 안에서** 갱신한다(Celery 보류 결정 — 태스크 없음):
  ① `출석` 확정 → videos.VideoGrant(source=출석자동, 그 회차 주차, 지급+7일)
  ② `결석` 확정 → boards.AbsenceCounseling 대기열 행(1차 통화 대상=학부모)

**원자성 판단 — 출결 저장과 트리거를 한 트랜잭션으로 묶는다.**
근거: 출결은 SSOT(grades.Attendance 계약)이고 지급·대기열은 그 파생이다.
"출결은 저장됐는데 지급이 누락된" 부분 성공은 SSOT 와 파생의 불일치 —
사본 금지 원칙(key_considerations §6)이 막으려는 바로 그 상태다. 트리거는
순수 DB 쓰기뿐이라(외부 API 없음 — DRM 반영은 sync_status 후순위, PRD 3.1.3)
실패는 곧 DB 장애이며, 그 경우 출결 저장도 함께 롤백해 관리자가 화면에서
재시도하는 편이 안전하다(수업 당일 현장 대응 불가 전제 — key_considerations §5).

**정정 시나리오 정책** (PRD 3.1.1 발송 후 수정 가능 — 정정은 언제든 온다):
- 출석 → 결석/지각: 자동지급(출석자동) revoke(revoked_at 스탬프 — 행 보존, 이력).
- 결석/지각 → 출석: revoke 된 자동지급을 **재활성**(revoked_at 해제 + 지급/만료
  재산정). 부분 UQ(uq_video_grants_attendance)가 출석 1건당 1행을 강제하므로
  행 복제가 아니라 재활성이 계약에 맞는 형태다.
- 결석 → 출석/지각: 대기열 행 중 **사람 손이 닿지 않은 행만** 삭제
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
import datetime

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Student
from apps.boards.models import AbsenceCounseling
from apps.curriculum.models import CourseEnrollment
from apps.videos.models import MakeupGrant, VideoGrant

from .models import Attendance, ClassSession

# 시청 기간 기본 7일(PRD 3.1.4 ⑥) — 관리자 설정화 전까지의 앱 레이어 기본값.
GRANT_DURATION = datetime.timedelta(days=7)


# --- 조회 ----------------------------------------------------------------


def load_session(session_id):
    """회차 + 주차·강좌 1쿼리 로드. 없으면 None."""
    return (
        ClassSession.objects.select_related("course_week__course")
        .filter(pk=session_id)
        .first()
    )


def load_roster(session):
    """회차 명단 = 그 주차 강좌의 활성 수강생(`수강`), **퇴원 제외**.

    예비등록생은 포함한다 — 1주차 실제 출석이 '등록' 전환의 근거(PRD 3.1.5·
    3.1.6)이므로 명단에 있어야 첫 출석을 입력할 수 있다. 주차 미매핑 회차는
    명단 산정 불가([]) — 쓰기는 뷰에서 400 처리.
    """
    if session.course_week is None:
        return []
    return list(
        Student.objects.filter(
            course_enrollments__course=session.course_week.course,
            course_enrollments__status=CourseEnrollment.Status.ENROLLED,
        )
        .exclude(enrollment_status=Student.EnrollmentStatus.WITHDRAWN)
        .select_related("user")
        .order_by("student_id")
    )


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
        "session_no": session.session_no,
        "target_grade": session.target_grade,
        "memo": session.memo,
        "week_no": week.week_no if week else None,
        "course": (
            {"course_id": week.course.course_id, "name": week.course.name} if week else None
        ),
    }


def build_detail_payload(session, roster, attendance_by_student):
    """상세·PUT 공용 응답 — 명단 + 출결 값 + 집계(프런트 재조회 불필요)."""
    students = []
    counts = {status: 0 for status in Attendance.Status.values}
    for student in roster:
        att = attendance_by_student.get(student.student_id)
        if att is not None:
            counts[att.status] += 1
        students.append(
            {
                "student_id": student.student_id,
                "name": student.user.name if student.user else None,
                "unique_id": student.unique_id,
                "current_class": student.current_class,
                "enrollment_status": student.enrollment_status,
                "attendance": _attendance_block(att),
            }
        )
    entered = sum(counts.values())
    summary = dict(counts)
    summary["미입력"] = len(roster) - entered
    summary["total"] = len(roster)
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
    triggers = {
        "video_grants_created": 0,
        "video_grants_revoked": 0,
        "video_grants_reactivated": 0,
        "counselings_created": 0,
        "counselings_removed": 0,
    }
    student_ids = [entry["student_id"] for entry in entries]
    with transaction.atomic():
        att_map = load_attendance_map(session, roster_ids)
        for entry in entries:
            _upsert_row(session, entry, att_map, actor, now)
        touched = [att_map[sid] for sid in student_ids]
        _sync_video_grants(session, touched, actor, now, triggers)
        _sync_counseling_queue(touched, triggers)
    return att_map, triggers


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


def _sync_video_grants(session, attendances, actor, now, triggers):
    """트리거 ① — 자동지급은 status=`출석` 인 동안만 활성(PRD 3.1.4 ①).

    지각은 지급 대상이 아니다 — SSOT 계약이 `출석` 확정만 트리거로 명시.
    기존 지급 1쿼리 로드 후 상태별 생성/재활성/revoke(모듈 docstring 정책).
    """
    grant_map = {
        g.attendance_id: g
        for g in VideoGrant.objects.filter(attendance_id__in=[a.id for a in attendances])
    }
    for att in attendances:
        grant = grant_map.get(att.id)
        if att.status == Attendance.Status.PRESENT:
            if grant is None:
                VideoGrant.objects.create(
                    student_id=att.student_id,
                    course_week=session.course_week,
                    source=VideoGrant.Source.ATTENDANCE_AUTO,
                    attendance=att,
                    granted_by=actor,
                    granted_at=now,
                    expires_at=now + GRANT_DURATION,
                )
                triggers["video_grants_created"] += 1
            elif grant.revoked_at is not None:
                grant.revoked_at = None
                grant.granted_at = now
                grant.expires_at = now + GRANT_DURATION
                grant.granted_by = actor
                grant.save(
                    update_fields=["revoked_at", "granted_at", "expires_at", "granted_by"]
                )
                triggers["video_grants_reactivated"] += 1
        elif (
            grant is not None
            and grant.source == VideoGrant.Source.ATTENDANCE_AUTO
            and grant.revoked_at is None
        ):
            grant.revoked_at = now
            grant.save(update_fields=["revoked_at"])
            triggers["video_grants_revoked"] += 1


def _sync_counseling_queue(attendances, triggers):
    """트리거 ② — 결석 상담 대기열(PRD §4 배치 ④, 동기 구현).

    결석 1건당 대기열 1행(기존 행 존재 시 상태 불문 미생성 — 중복 금지).
    1차 통화 대상=학부모(PRD 3.1.9). 결석 아님 정정 시 미통화 대기 행만 삭제
    (모듈 docstring 정책).
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
    """동보 지급 체인 — MakeupGrant(관리자체크→지급완료) + VideoGrant(동보).

    MakeupGrant 모델의 지급 체인 계약 이행: status 가 `지급완료` 로 전이될 때
    VideoGrant(source=동보, makeup=이 레코드) 를 같은 트랜잭션에서 생성한다
    (출석생과 동일한 그 주 권한 — PRD 3.2.3 1차 경로). requested_by 에는 체크한
    관리자를 남긴다(신청 주체 감사 이력). 중복은 뷰의 지급완료 선재 검사 +
    부분 UQ(uq_video_grants_makeup)가 이중 방어.
    """
    now = timezone.now()
    with transaction.atomic():
        makeup = MakeupGrant.objects.create(
            student_id=attendance.student_id,
            attendance=attendance,
            source=MakeupGrant.Source.ADMIN_CHECK,
            requested_by=actor,
            status=MakeupGrant.Status.GRANTED,
            granted_at=now,
        )
        grant = VideoGrant.objects.create(
            student_id=attendance.student_id,
            course_week=attendance.session.course_week,
            source=VideoGrant.Source.MAKEUP,
            makeup=makeup,
            granted_by=actor,
            granted_at=now,
            expires_at=now + GRANT_DURATION,
        )
    return makeup, grant
