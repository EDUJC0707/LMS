"""워크북 사진 열람 서비스 — 학생·학부모 공용 (7차 슬라이스, PRD 3.1.7·3.1.1·§4).

학생(/api/student/workbook)과 학부모(/api/parent/workbook)가 같은 조립 함수를
쓴다 — 이중 구현 금지(report 선례). 뷰는 역할 게이트·대상 학생 결정만 한다.

노출 규칙(§4 상태 기반 노출 — 닫힘 기본값, key_considerations §5):
- **매핑 확정(자동매칭·수동확정)된 것만** 노출한다. 대기(match_status NULL)·
  불일치·인식실패는 잠정 매핑일 수 있으므로 미노출 — 오매핑 사진이 타 학생
  학부모에게 새어나가는 사고를 구조적으로 차단한다.
- 사진은 storage url() 경유로만 내려준다(직접 경로 노출 대신) — 로컬은
  MEDIA_URL, 운영(Tigris)은 서명 URL 로 settings 가 알아서 갈린다(§6).
- 과제 수행 여부(assignments.done — PRD 3.1.1 '수행=사진 링크' 이원 관리)는
  같은 회차의 기록이 있으면 함께 내린다(없으면 null — 기록 없음).
"""
from django.core.files.storage import default_storage
from django.db.models import F
from django.utils import timezone

from .models import Assignment, WorkbookSubmission

# 소비자 노출 대상 — 매핑 확정 2종(모듈 docstring 노출 규칙)
CONFIRMED_STATUSES = (
    WorkbookSubmission.MatchStatus.AUTO_MATCHED,
    WorkbookSubmission.MatchStatus.MANUAL_CONFIRMED,
)


def build_workbook_payload(student):
    """열람 응답 — 확정 사진(최근 회차 우선) + 회차별 과제 수행 여부."""
    submissions = list(
        WorkbookSubmission.objects.filter(student=student, match_status__in=CONFIRMED_STATUSES)
        .select_related("session")
        .order_by(F("session__session_date").desc(nulls_last=True), "-submission_id")
    )
    done_map = _assignment_done_map(student, submissions)
    return {
        "workbooks": [
            {
                "submission_id": submission.pk,
                "session": session_block(submission.session),
                "image_url": default_storage.url(submission.image_path),
                "performance_grade": submission.performance_grade,
                "assignment_done": done_map.get(submission.session_id),
                "uploaded_at": iso(submission.created_at),
            }
            for submission in submissions
        ]
    }


def _assignment_done_map(student, submissions):
    """{session_id: done} — 회차 일괄 조회(N+1 방지). 기록 없는 회차는 미포함."""
    session_ids = {s.session_id for s in submissions if s.session_id is not None}
    if not session_ids:
        return {}
    return dict(
        Assignment.objects.filter(student=student, session_id__in=session_ids).values_list(
            "session_id", "done"
        )
    )


def session_block(session):
    """회차 표기 블록 — 관리자·소비자 공용(없으면 None)."""
    if session is None:
        return None
    return {
        "session_id": session.session_id,
        "session_date": session.session_date.isoformat(),
        "session_no": session.session_no,
    }


def iso(value):
    """aware datetime → Asia/Seoul 로컬 ISO 문자열(2차 슬라이스 표기 선례)."""
    return timezone.localtime(value).isoformat() if value else None
