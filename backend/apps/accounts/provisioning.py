"""계정 일괄 발급 서비스 — 학생·학부모 계정 생성·연결 (PRD 3.1.5, 8-3·8-4).

아이디 규칙은 **`login_id.py` 가 유일한 준거**다(8-4 개정 2026-07-28 — 한글
전환: 학생 `{이름}{뒷4자리}`, 학부모 `{학생 아이디}p`). 이 모듈은 규칙을
직접 만들지 않고 그 함수만 호출한다 — 규칙이 두 곳에 흩어지면 발급 경로마다
아이디 체계가 갈린다.

**원번도 같다 — `unique_id.py` 경유 파생값**(2026-07-29 재개정). 원번은 더 이상
명단의 입력 항목이 아니라 `{이름}{뒷4자리}` 계산값이다. 따라서:

- 행에 `unique_id` 가 들어오면 **그 행을 실패**시킨다. 무시하면 호출자는 자기가
  준 원번이 저장됐다고 믿는데, 실제로는 다른 값이 들어가고 확인할 방법도 없다 —
  조용한 불일치보다 즉시 실패가 낫다. 전체 400 이 아니라 행 실패인 이유는 이
  모듈의 실패 단위가 행이기 때문이고, 옛 서식을 통째로 붙여넣으면 모든 행이
  같은 사유로 떠서 서식이 바뀐 사실이 그대로 드러나기 때문이다.
- **`grade` 는 필수가 아니다**(2026-07-29 재개정 판단). 학년이 원번에서 빠지면서
  "비면 조용히 못 찾는 학생이 생긴다"는 이유가 소멸했다. 학생 정보로서의 학년이
  필요한 것과 원번을 만들기 위해 필요한 것은 다른 문제인데, 발급을 막던 근거는
  후자뿐이었다. 이제 비면 빈 문자열로 저장되고(`Student.grade` 는 blank),
  명단 화면에서 눈에 보이며 `promote_grade` 가 "다음 학년이 없습니다"로 건너뛰어
  드러난다 — 나중에 채울 수 있는 값 하나 때문에 계정 발급 전체를 막지 않는다.
  표기도 파싱하지 않는다(`고등부`·`N수` 무엇이든 적힌 대로 저장).
- 발급 결과에 `unique_id` 를 실어 보낸다 — 관리자가 OMR 답안지·워크북에 적을
  값이라 발급 시점이 이 값을 확인하는 자리다.

**행 단위 실패 판단(전체 롤백 아님)**: 명단은 엑셀 붙여넣기로 수십 행이
한 번에 들어온다. 한 행의 중복·누락 때문에 전체를 롤백하면 관리자는 실패
원인을 못 본 채 전량 재입력해야 한다 — 행마다 savepoint(중첩 atomic)를 걸어
성공 행은 확정하고 실패 행만 사유와 함께 리포트한다. 같은 요청 안의 선행
행이 만든 계정은 후행 행의 중복 검사에 그대로 보인다(동일 외부 트랜잭션).

**초기 비밀번호 응답 반환(임시 정책)**: SMS(알림톡) 발송은 채널 연동 대기
(솔라피 검토 — key_considerations §4)라서, 이번 슬라이스는 초기 비밀번호를
**응답으로 반환**해 관리자가 수동 전달한다. credentials_sent_at 은 발송
연동이 붙을 때 스탬프한다(D-1 배치 계약 — Student 모델 docstring). 해시만
저장되므로 응답의 1회 노출이 비밀번호를 볼 수 있는 유일한 시점이다.
"""
import secrets

from django.db import IntegrityError, transaction
from django.utils import timezone

from .login_id import LoginIdError, issue_parent_login_id, issue_student_login_id
from .models import Parent, ParentStudent, Student, User
from .unique_id import build_unique_id

# 혼동 문자(0/O/1/l/I) 제외 — SMS 로 받아 손으로 입력하는 비밀번호라
# 시인성이 보안 엔트로피만큼 중요하다(최초 로그인 후 변경 강제가 안전망).
_PASSWORD_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
_PASSWORD_LENGTH = 8


def generate_initial_password() -> str:
    """랜덤 초기 비밀번호 — 일괄 발급·직원 생성 공용(PRD 3.1.5 랜덤 생성)."""
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(_PASSWORD_LENGTH))


class RowError(Exception):
    """행 단위 실패 — reason 이 결과 리포트의 error 로 나간다."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def bulk_issue(rows):
    """명단 일괄 발급 — 행별 결과 리스트와 집계를 반환한다(모듈 docstring).

    행 결과: {index, name, status 생성|실패, login_id, initial_password,
    student_id, parent{...}|None, error}. 실패 행은 savepoint 롤백으로
    잔재(User/Student 반쪽 생성)를 남기지 않는다.
    """
    results = []
    summary = {"created": 0, "failed": 0, "parents_created": 0, "parents_linked": 0}
    for index, row in enumerate(rows):
        try:
            with transaction.atomic():  # 행 단위 savepoint
                result = _issue_row(row)
        except RowError as exc:
            summary["failed"] += 1
            results.append(
                {
                    "index": index,
                    "name": row.get("name") if isinstance(row, dict) else None,
                    "status": "실패",
                    "error": exc.reason,
                }
            )
            continue
        summary["created"] += 1
        if result.get("parent"):
            key = "parents_created" if result["parent"]["created"] else "parents_linked"
            summary[key] += 1
        results.append({"index": index, "status": "생성", **result})
    return {"results": results, "summary": summary}


def _issue_row(row):
    """행 1건 처리 — 학생 User+Student 생성, 학부모 생성/연결. 실패는 RowError."""
    if not isinstance(row, dict):
        raise RowError("행 형식이 올바르지 않습니다.")
    if str(row.get("unique_id") or "").strip():
        raise RowError("원번은 이름·휴대폰에서 자동으로 만들어집니다 — 입력할 수 없습니다.")
    name = row.get("name")
    if not (isinstance(name, str) and name.strip()):
        raise RowError("name이 필요합니다.")
    name = name.strip()
    phone = _clean_phone(row.get("phone"))
    parent_phone = _clean_phone(row.get("parent_phone"))
    if not phone and not parent_phone:
        raise RowError("phone 또는 parent_phone이 필요합니다.")
    grade = (row.get("grade") or "").strip()

    try:
        login_id = issue_student_login_id(name, phone, parent_phone)
        unique_id = build_unique_id(name, phone, parent_phone)
    except LoginIdError as exc:
        raise RowError(str(exc)) from exc
    student_user, initial_password = _create_user(login_id, User.Role.STUDENT, name, phone)
    student = Student.objects.create(
        user=student_user,
        unique_id=unique_id,
        grade=grade,
        school=(row.get("school") or "").strip(),
    )

    parent_block = None
    if parent_phone:
        parent_block = _link_parent(parent_phone, name, login_id, student)

    return {
        "name": name,
        "login_id": login_id,
        "initial_password": initial_password,
        "student_id": student.student_id,
        "unique_id": student.unique_id,
        "parent": parent_block,
    }


def _clean_phone(value):
    if not isinstance(value, str):
        return ""
    return value.strip()


def _create_user(login_id, role, name, phone):
    """User 생성 — 중복 아이디는 RowError(사전 조회 + IntegrityError 이중 방어)."""
    if User.objects.filter(login_id=login_id).exists():
        raise RowError(f"이미 사용 중인 아이디입니다: {login_id}")
    password = generate_initial_password()
    try:
        user = User.objects.create_user(
            login_id=login_id, password=password, name=name, role=role, phone=phone or ""
        )
    except IntegrityError as exc:  # 동시 요청 경합 백스톱
        raise RowError(f"이미 사용 중인 아이디입니다: {login_id}") from exc
    return user, password


def _link_parent(parent_phone, student_name, student_login_id, student):
    """학부모 생성/연결 — **중복 전화면 기존 학부모에 자녀 연결만**(PRD 3.4).

    parents.phone 이 매칭 키(청구서·SMS 수신 번호 — 모델 계약). 신규면
    학부모 User(아이디=**이 자녀의 아이디 + p** — login_id 모듈)+Parent 를
    만들고, User.name 은 NN 이라 "{학생명} 학부모"로 표시명을 채운다
    (Parent.name 은 설계상 NULL 유지 — 실명 미상).

    **다자녀는 아이디가 바뀌지 않는다**: 둘째부터는 이 분기의 앞쪽(기존 학부모)
    으로 들어와 연결만 추가되므로, 아이디는 계정을 만들게 한 최초 연결 자녀
    기준으로 고정된다(login_id 모듈의 다자녀 절과 같은 계약).
    """
    parent = Parent.objects.filter(phone=parent_phone).order_by("parent_id").first()
    if parent is not None:
        _, link_created = ParentStudent.objects.get_or_create(
            parent=parent, student=student
        )
        return {
            "parent_id": parent.parent_id,
            "login_id": parent.user.login_id if parent.user else None,
            "created": False,
            "linked": link_created,
        }
    try:
        parent_login_id = issue_parent_login_id(student_login_id)
    except LoginIdError as exc:
        raise RowError(str(exc)) from exc
    parent_user, parent_password = _create_user(
        parent_login_id, User.Role.PARENT, f"{student_name} 학부모", parent_phone
    )
    parent = Parent.objects.create(user=parent_user, phone=parent_phone)
    ParentStudent.objects.create(parent=parent, student=student)
    return {
        "parent_id": parent.parent_id,
        "login_id": parent_login_id,
        "initial_password": parent_password,
        "created": True,
        "linked": True,
    }


def register_student(student):
    """예비등록→등록 전환 — 1주차 실제 출석 확인 후 관리자가 누른다(PRD 3.1.5).

    출석 여부를 여기서 재검증하지 않는다 — 판단은 출결 화면을 본 관리자 몫이고,
    수동 우회 수단을 막지 않는 것이 원칙(key_considerations §5 견고성).
    전환 불가 상태(이미 등록·퇴원)는 ValueError — 뷰가 400 으로 옮긴다.
    """
    if student.enrollment_status != Student.EnrollmentStatus.PRE_REGISTERED:
        raise ValueError(f"예비등록 상태가 아닙니다({student.enrollment_status}).")
    student.enrollment_status = Student.EnrollmentStatus.REGISTERED
    student.registered_at = timezone.now()
    student.save(update_fields=["enrollment_status", "registered_at"])
    return student
