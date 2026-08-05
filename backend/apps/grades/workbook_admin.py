"""워크북 업로드·매핑 관리자 서비스 — 조교 업로드·보정 화면 근거 (7차, PRD 3.1.7).

저장 계약(§6 큰 파일은 스토리지, DB엔 경로만):
- 파일은 Django default_storage 로 저장한다 — 코드는 스토리지 중립이고,
  운영은 settings(AWS_STORAGE_BUCKET_NAME)가 Tigris S3 로 알아서 갈린다.
- DB(image_path)엔 스토리지 상대 경로만 남긴다. 노출은 storage url() 경유.

파일 검증 판단 근거:
- 확장자 jpg/jpeg/png/webp — 브라우저가 직접 표시 가능한 사진 포맷만
  (PRD 3.1.7 "사진 이미지 자체를 그대로 보여준다" — 표시 불가 포맷이
  들어오면 열람 단계에서 깨진다. HEIC 등은 프런트에서 변환 후 업로드).
- 크기 상한 10MB/장 — 스마트폰 기본 화질 사진(통상 2~8MB)을 여유 있게
  덮으면서, 수기 코멘트·ABC 도장 판독(PRD 3.1.7 열람 목적)에 불필요한
  원본 초과 화질로 스토리지·전송이 낭비되는 것을 막는 값.
- 빈 파일(0바이트) 거부, 전량 검증 후에만 저장(원자성 — 출결 PUT 선례).

매칭 계약(8-9 결정·설계 원칙):
- 업로드 시 OCR 3컬럼(recognized_*·match_status)은 전부 NULL(=매핑 대기).
  student 는 설계(도메인 2 NN)에 따라 업로드 본문으로 받는 **잠정 매핑**이며,
  확정(자동매칭·수동확정) 전에는 소비자에 노출되지 않는다(workbook 서비스).
- OCR 인식 엔진은 범위 밖 — 인식 결과 수용(apply_recognition)만 둔다. 엔진이
  붙거나 관리자가 수동 입력하면 원번+이름 대조로 자동 매칭을 시도한다.
  **원번(matching_key)은 단독 UQ 가 아니다 — 이름과 함께 매칭키**(accounts 설계).
  (원번, 이름) 정확히 1명 일치 시에만 자동매칭, 그 외(미존재·이름 불일치·
  동일 원번+동명 중복)는 불일치로 두고 관리자 수동 지정(수동확정)으로 보정.
"""
import uuid

from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import Student

from . import workbook
from .models import WorkbookSubmission

ALLOWED_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp"})
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB/장 — 모듈 docstring 판단 근거
PENDING_STATUS = "대기"  # match_status NULL 의 조회 표기(필터 파라미터 전용)

_MS = WorkbookSubmission.MatchStatus
# 미매핑(보정 잔량) = 확정 아닌 전부 — NULL(대기)·불일치·인식실패.
# exclude(__in=확정)은 NULL 행을 SQL 3치 논리로 떨어뜨리므로 명시 필터로 센다.
_UNMATCHED_FILTER = Q(match_status__isnull=True) | Q(
    match_status__in=(_MS.MISMATCH, _MS.OCR_FAILED)
)


def validate_files(files):
    """업로드 파일 전량 검증 — 오류 메시지 또는 None(원자성: 하나라도 불량이면 전체 거부)."""
    if not files:
        return "이미지 파일이 필요합니다."
    for file in files:
        extension = _extension(file.name)
        if extension not in ALLOWED_EXTENSIONS:
            return "이미지 파일(jpg/jpeg/png/webp)만 업로드할 수 있습니다."
        if not file.size:
            return "빈 파일은 업로드할 수 없습니다."
        if file.size > MAX_FILE_SIZE:
            return "파일 크기는 장당 10MB 이하여야 합니다."
    return None


def create_submissions(files, student, session, user):
    """스토리지 저장 + 매핑 대기 제출 행 생성(검증 통과 전제).

    파일명은 uuid 로 발급(업로드 원본명 미신뢰 — 경로 주입 차단). 행 생성이
    실패하면 이미 저장한 파일을 걷어낸다(스토리지는 트랜잭션 밖이므로 수동 보상).
    """
    saved_paths = []
    try:
        for file in files:
            target = (
                f"workbook/{timezone.localdate():%Y/%m}/{uuid.uuid4().hex}.{_extension(file.name)}"
            )
            saved_paths.append(default_storage.save(target, file))
        with transaction.atomic():
            return [
                WorkbookSubmission.objects.create(
                    student=student,
                    session=session,
                    image_path=path,
                    uploaded_by=user,
                )
                for path in saved_paths
            ]
    except Exception:
        for path in saved_paths:
            default_storage.delete(path)
        raise


def build_admin_list(session_id=None, status=None):
    """목록 + 미매핑 카운트 — 보정 화면 근거(PRD 3.1.7 수동 보정).

    total/unmatched 카운트는 session 필터만 반영한다(해당 회차의 보정 잔량) —
    status 필터는 행 목록에만 적용(배지 숫자가 필터 조작에 흔들리지 않게).
    """
    base = WorkbookSubmission.objects.all()
    if session_id is not None:
        base = base.filter(session_id=session_id)
    submissions = base.select_related("student__user", "session", "uploaded_by")
    if status == PENDING_STATUS:
        submissions = submissions.filter(match_status__isnull=True)
    elif status is not None:
        submissions = submissions.filter(match_status=status)
    return {
        "submissions": [
            admin_row(submission)
            for submission in submissions.order_by("-submission_id")
        ],
        "total_count": base.count(),
        "unmatched_count": base.filter(_UNMATCHED_FILTER).count(),
    }


def apply_manual_match(submission, student):
    """관리자 수동 지정 — 학생 확정(수동확정). 인식값은 보존한다(보정 이력 근거)."""
    submission.student = student
    submission.match_status = _MS.MANUAL_CONFIRMED
    submission.save(update_fields=["student", "match_status"])
    return submission


def apply_recognition(submission, matching_key, name):
    """원번 인식 결과 수용 — 원번+이름 대조(모듈 docstring 매칭 계약).

    (원번, 이름) 정확히 1명 일치 시에만 학생 갱신 + 자동매칭. 그 외(미존재·
    이름 불일치·동일 원번+동명 중복·이름 미인식)는 불일치 — 잠정 매핑(student)은
    유지하되 확정이 아니므로 소비자엔 미노출(workbook 노출 규칙). 인식값은
    결과와 무관하게 저장한다(보정 화면의 대조 근거). 이름 없는 학생 행(user
    NULL — 계정 발급 전)은 user__name 조인에서 자연 제외된다.
    """
    submission.recognized_matching_key = matching_key
    submission.recognized_name = name
    matched = None
    if name:
        candidates = list(Student.objects.filter(matching_key=matching_key, user__name=name)[:2])
        if len(candidates) == 1:
            matched = candidates[0]
    if matched is not None:
        submission.student = matched
        submission.match_status = _MS.AUTO_MATCHED
    else:
        submission.match_status = _MS.MISMATCH
    submission.save(
        update_fields=["student", "recognized_matching_key", "recognized_name", "match_status"]
    )
    return submission


def delete_submission(submission):
    """행 삭제 + 스토리지 파일 제거 — 잘못 올린 사진 정리(파일 잔존 금지).

    DB 행을 먼저 지운다(행이 남고 파일만 사라지는 깨진 링크 방지가 우선).
    """
    path = submission.image_path
    submission.delete()
    default_storage.delete(path)


def admin_row(submission):
    """관리자 행 페이로드 — 업로드 응답·목록 공용."""
    student = submission.student
    uploaded_by = submission.uploaded_by
    return {
        "submission_id": submission.pk,
        "student": {
            "student_id": student.pk,
            "name": student.user.name if student.user else None,
            "login_id": student.user.login_id if student.user else None,
            "matching_key": student.matching_key,
        },
        "session": workbook.session_block(submission.session),
        "image_url": default_storage.url(submission.image_path),
        "recognized_matching_key": submission.recognized_matching_key,
        "recognized_name": submission.recognized_name,
        "match_status": submission.match_status,
        "performance_grade": submission.performance_grade,
        "uploaded_by": (
            {"user_id": uploaded_by.pk, "name": uploaded_by.name} if uploaded_by else None
        ),
        "uploaded_at": workbook.iso(submission.created_at),
    }


def _extension(filename):
    """소문자 확장자('.' 없으면 빈 문자열) — 검증·저장 파일명 공용."""
    _, dot, extension = filename.rpartition(".")
    return extension.lower() if dot else ""
