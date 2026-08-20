"""계정 일괄 발급 서비스 — 학생·학부모 계정 생성·연결 (PRD 3.1.5, 8-3·8-4).

아이디 규칙은 **`login_id.py` 가 유일한 준거**다(8-4 개정 2026-07-28 — 한글
전환: 학생 `{이름}{뒷4자리}`, 학부모 `{학생 아이디}p`). 이 모듈은 규칙을
직접 만들지 않고 그 함수만 호출한다 — 규칙이 두 곳에 흩어지면 발급 경로마다
아이디 체계가 갈린다.

**원번도 같다 — `matching_key.py` 경유 파생값**(2026-07-29 재개정). 원번은 더 이상
명단의 입력 항목이 아니라 `{이름}{뒷4자리}` 계산값이다. 따라서:

- 행에 `matching_key` 가 들어오면 **그 행을 실패**시킨다. 무시하면 호출자는 자기가
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
- 발급 결과에 `matching_key` 를 실어 보낸다 — 관리자가 OMR 답안지·워크북에 적을
  값이라 발급 시점이 이 값을 확인하는 자리다.

**번호가 하나만 맞으면 아무것도 만들지 않는다**(FLOW 2-3). 판정은 번호로만 한다 —
이름은 후보를 좁히는 데 쓰지 않고, 번호가 맞은 뒤 "같은 사람인가"를 가를 때만 본다.

    셋 다 일치(이름·학생번호·학부모번호)  →  기존. 수강만 는다
    번호가 하나라도 일치                   →  **확인필요**. 아무것도 만들지 않는다
    번호가 하나도 안 맞음                  →  새 학생

확인필요 행은 `User`·`Student`·`CourseEnrollment` 를 하나도 만들지 않는다 —
아이디·비밀번호는 아직 임시일 뿐이고 PK 가 할당되지 않는다(FLOW 2-3·2-4).
반쪽 계정을 남기면 학생 관리 화면에 유령이 뜬다.

조교의 답은 **같은 행을 다시 보내는 것**으로 들어온다(`same_as_student_id` 로 그
학생에 수강만 추가하거나, `force_new` 로 새로 발급). 대기 상태를 어디에도 저장하지
않으므로 새 테이블이 없고, 발송 배치(FLOW 2-4)가 붙을 때 그 안으로 그대로 들어간다.

**행 단위 실패 판단(전체 롤백 아님)**: 명단은 엑셀 붙여넣기로 수십 행이
한 번에 들어온다. 한 행의 중복·누락 때문에 전체를 롤백하면 관리자는 실패
원인을 못 본 채 전량 재입력해야 한다 — 행마다 savepoint(중첩 atomic)를 걸어
성공 행은 확정하고 실패 행만 사유와 함께 리포트한다. 같은 요청 안의 선행
행이 만든 계정은 후행 행의 중복 검사에 그대로 보인다(동일 외부 트랜잭션).

**아이디·초기 비밀번호는 알림으로도 나간다**(FLOW 3-11 #1). 응답 반환만
하던 시절에는 화면을 닫는 순간 비밀번호가 사라졌다 — 해시만 저장되므로
다시 볼 방법이 없고, 학생은 들어올 길이 없었다. 발급마다 `계정발급` 알림을
**큐에 건다**(notifications.sending.queue).

- **학생 번호가 없으면 학부모에게 간다**(FLOW 2-4) — 학생 계정 안내까지.
- **학부모 안내는 계정을 만들 때만** 나간다. 둘째 자녀는 연결만 되므로
  아이디가 그대로이고 안내도 다시 가지 않는다(FLOW 2-4 의 "계정이 있으면
  안 나간다"와 같은 계약).
- **템플릿 승인 전이라 실제로는 안 나간다** — `NOTIFICATION_KAKAO_TEMPLATE_CODES`
  가 비어 있어 발송은 영구 실패로 닫히고 사유가 행에 남는다(8-17 대기).
  승인분이 들어오면 이 코드는 그대로 두고 설정만 채우면 나간다.
- credentials_sent_at 은 여전히 스탬프하지 않는다 — 큐에 걸린 것과 학부모
  손에 닿은 것은 다르다. 발송이 실제로 성공하는 날 그 자리에서 찍는다.

응답의 초기 비밀번호는 그대로 둔다(관리자가 그 자리에서 불러 줄 수 있는
유일한 값이고, 알림이 못 나가는 동안에는 이것이 유일한 전달 경로다).
"""
import secrets

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.curriculum.models import CourseEnrollment
from apps.notifications.models import Notification
from apps.notifications.sending import queue as queue_notification

from .aliases import resolve_school, unknown_schools
from .login_id import (
    LoginIdError,
    issue_parent_login_id,
    issue_student_login_id,
    nfc,
    normalize_phone,
    resolve_collision,
)
from .matching_key import build_matching_key
from .models import Parent, ParentStudent, Student, User

# 혼동 문자(0/O/1/l/I) 제외 — SMS 로 받아 손으로 입력하는 비밀번호라
# 시인성이 보안 엔트로피만큼 중요하다(최초 로그인 후 변경 강제가 안전망).
_PASSWORD_ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"
_PASSWORD_LENGTH = 8


def generate_initial_password() -> str:
    """랜덤 초기 비밀번호 — 일괄 발급·직원 생성 공용(PRD 3.1.5 랜덤 생성)."""
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(_PASSWORD_LENGTH))


_SUMMARY_KEY = {"생성": "created", "기존": "existing", "확인필요": "needs_review"}


class RowError(Exception):
    """행 단위 실패 — reason 이 결과 리포트의 error 로 나간다."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def bulk_issue(rows, klass):
    """명단 일괄 발급 — 행별 결과 리스트와 집계를 반환한다(모듈 docstring).

    행 결과: {index, name, status 생성|기존|확인필요|실패, login_id,
    initial_password, student_id, matched[...], parent{...}|None, error}.
    실패 행은 savepoint 롤백으로 잔재(User/Student 반쪽 생성)를 남기지 않고,
    확인필요 행은 애초에 아무것도 만들지 않는다.

    **어느 반인지는 조교가 고른 것이지 파일에 있는 것이 아니다**(FLOW 2-1) —
    그래서 명단이 아니라 인자로 받고, 모든 행이 그 반에 등록된다.
    """
    results = []
    summary = {
        "created": 0,
        "existing": 0,
        "needs_review": 0,
        "failed": 0,
        "parents_created": 0,
        "parents_linked": 0,
    }
    for index, row in enumerate(rows):
        try:
            with transaction.atomic():  # 행 단위 savepoint
                result = _issue_row(row, klass)
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
        summary[_SUMMARY_KEY[result["status"]]] += 1
        if result.get("parent"):
            key = "parents_created" if result["parent"]["created"] else "parents_linked"
            summary[key] += 1
        results.append({"index": index, **result})
    return {
        "results": results,
        "summary": summary,
        # 별칭표에 없던 학교 — 묶음이 스스로 뱉는다(FLOW 5-3). 행을 세우지 않고
        # 끝나고 모아 준다. 이게 없으면 조교는 무엇이 안 맞았는지 알 길이 없다.
        "unknown_schools": unknown_schools(
            row.get("school") for row in rows if isinstance(row, dict)
        ),
    }


def _issue_row(row, klass):
    """행 1건 처리 — 학생 User+Student 생성, 학부모 생성/연결, 반 등록.

    **이미 계정이 있으면 수강만 추가한다**(FLOW 2-4) — 계정은 한 번 만들면
    끝이고, 다른 반이어도 새 계정을 만들지 않는다. 그 행은 아이디·비밀번호를
    싣지 않는다(안내가 나갈 자리가 없다). 실패는 RowError.

    번호가 하나만 맞으면 확인필요로 돌려보내고 아무것도 만들지 않는다(모듈
    docstring). 조교가 답한 행은 `same_as_student_id`·`force_new` 를 달고 다시
    들어와 이 함수를 그대로 지나간다.
    """
    if not isinstance(row, dict):
        raise RowError("행 형식이 올바르지 않습니다.")
    if str(row.get("matching_key") or "").strip():
        raise RowError("원번은 이름·휴대폰에서 자동으로 만들어집니다 — 입력할 수 없습니다.")
    name = row.get("name")
    if not (isinstance(name, str) and name.strip()):
        raise RowError("name이 필요합니다.")
    # NFC 로 합쳐서 들어간다 — 맥 파일의 분해형 이름이 저장·판정·아이디에서
    # 갈리지 않게(FLOW 2-2 ①). `_match_existing` 의 이름 비교도 이 값을 본다.
    name = nfc(name).strip()
    phone = normalize_phone(row.get("phone"))
    parent_phone = normalize_phone(row.get("parent_phone"))
    if not phone and not parent_phone:
        raise RowError("phone 또는 parent_phone이 필요합니다.")
    grade = (row.get("grade") or "").strip()

    if row.get("same_as_student_id") is not None:  # 조교가 "같은 사람" 을 골랐다
        return _enrolled_result(_load_student(row["same_as_student_id"]), klass)

    existing, candidates = _match_existing(name, phone, parent_phone)
    if existing is not None:
        return _enrolled_result(existing, klass)
    if candidates and not row.get("force_new"):
        return {
            "status": "확인필요",
            "name": name,
            "matched": [_matched_block(student) for student in candidates],
        }

    try:
        login_id = issue_student_login_id(name, phone, parent_phone)
        matching_key = build_matching_key(name, phone, parent_phone)
    except LoginIdError as exc:
        raise RowError(str(exc)) from exc
    student_user, initial_password = _create_user(login_id, User.Role.STUDENT, name, phone)
    student = Student.objects.create(
        user=student_user,
        matching_key=matching_key,
        grade=grade,
        # 학교 별칭표를 서버에서 태운다(FLOW 2-2) — 붙여넣기 화면이 안 물어도
        # 아는 이름이면 정식 이름으로 들어가고, 모르는 학교는 온 그대로다.
        school=resolve_school(row.get("school")),
    )

    parent_block = None
    if parent_phone:
        parent_block = _link_parent(parent_phone, name, login_id, student)
    _enroll(student, klass)
    _notify_credentials(student, login_id, initial_password, parent_block)

    return {
        "status": "생성",
        "name": name,
        "login_id": login_id,
        "initial_password": initial_password,
        "student_id": student.student_id,
        "matching_key": student.matching_key,
        "parent": parent_block,
    }


def _match_existing(name, phone, parent_phone):
    """(통과할 학생, 확인이 필요한 후보들) — 판정은 **번호로만** 한다(FLOW 2-3).

    후보를 찾는 것은 번호뿐이다. 이름만 같은 것은 동명이인이라 물어봐야 소용이
    없다. 이름은 번호가 맞은 뒤 "같은 사람인가"를 가를 때만 본다 — 번호 둘이
    다 맞는데 이름이 다르면 오타이므로 묻는다.

    번호 한 짝은 **일치하거나, 양쪽 다 없거나** 두 경우만 다툼이 없다
    (`_agrees`). 학생 번호가 원래 없던 학생을 다시 올려도 학부모 번호 하나로
    통과하는 것이 그래서 성립한다 — 없는 것끼리는 어긋나지 않는다.
    """
    lookup = Q()
    if phone:
        lookup |= Q(user__phone=phone)
    if parent_phone:
        lookup |= Q(parent_students__parent__phone=parent_phone)
    if not lookup:
        return None, []
    candidates = list(
        Student.objects.select_related("user")
        .prefetch_related("parent_students__parent")
        .filter(lookup)
        .order_by("student_id")
        .distinct()
    )
    for student in candidates:
        parents = {link.parent.phone for link in student.parent_students.all()}
        if (
            _agrees(phone, {student.user.phone})
            and _agrees(parent_phone, parents)
            and student.user.name == name
        ):
            return student, []
    return None, candidates


def _agrees(value, stored):
    """번호 한 짝의 판정 — 일치하거나, 양쪽 다 비어 있거나."""
    stored = {item for item in stored if item}
    return value in stored if value else not stored


def _matched_block(student):
    """확인필요 행이 싣고 가는 값 — 조교는 이 값들을 보고 오타인지 형제인지 안다."""
    return {
        "student_id": student.student_id,
        "name": student.user.name,
        "login_id": student.user.login_id,
        "phone": student.user.phone,
        "parent_phone": next(
            (link.parent.phone for link in student.parent_students.all()), ""
        ),
    }


def _load_student(raw_student_id):
    """조교가 고른 학생 — 없으면 RowError(그 행만 실패한다)."""
    student = (
        Student.objects.select_related("user").filter(pk=raw_student_id).first()
        if isinstance(raw_student_id, int) and not isinstance(raw_student_id, bool)
        else None
    )
    if student is None:
        raise RowError(f"학생을 찾을 수 없습니다: {raw_student_id}")
    return student


def _enrolled_result(student, klass):
    """이미 있는 학생 — 수강만 는다. 아이디·비밀번호는 싣지 않는다(FLOW 2-4)."""
    _enroll(student, klass)
    return {
        "status": "기존",
        "name": student.user.name,
        "login_id": student.user.login_id,
        "student_id": student.student_id,
        "matching_key": student.matching_key,
        "parent": None,
    }


def _enroll(student, klass):
    """반에 등록한다 — 같은 반 재업로드는 멱등, 다른 반이면 수강이 하나 는다.

    학생↔반은 N:M 이고(FLOW 1-1) UQ 도 (student, klass) 라 반마다 한 행이다.
    요일은 개강일에서 얻는다(FLOW 1-2) — 0=일…6=토 로 옮겨 담는다.
    """
    weekday = None
    if klass.start_date:
        weekday = (klass.start_date.weekday() + 1) % 7
    CourseEnrollment.objects.get_or_create(
        student=student,
        klass=klass,
        defaults={"course": klass.course, "primary_weekday": weekday},
    )


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


def _notify_credentials(student, login_id, password, parent_block=None):
    """아이디·임시 비밀번호를 큐에 건다(FLOW 3-11 #1 — 모듈 docstring).

    학생 몫은 **번호가 있는 쪽**으로 간다: 학생 번호가 없으면 학부모가 대신
    받는다(FLOW 2-4). 대상 3분기는 정확히 하나여야 하므로 여기서 가른다.

    학부모 몫은 `parent_block` 이 새 계정일 때만이다 — 기존 학부모는 아이디가
    바뀌지 않았으니 보낼 것이 없다.
    """
    parent = _notify_target_parent(student) if not student.user.phone else None
    _queue_account_issued(
        student=None if parent else student,
        parent=parent,
        body=f"{student.user.name} 아이디 {login_id} 비밀번호 {password}",
        student_id=student.student_id,
    )
    if parent_block and parent_block.get("created"):
        _queue_account_issued(
            parent=Parent.objects.filter(pk=parent_block["parent_id"]).first(),
            body=(
                f"{student.user.name} 학부모 아이디 {parent_block['login_id']} "
                f"비밀번호 {parent_block['initial_password']}"
            ),
            student_id=student.student_id,
        )


def _notify_target_parent(student):
    """무전화 학생의 안내를 대신 받을 학부모 — 없으면 None(학생 앞으로 둔다)."""
    link = student.parent_students.select_related("parent").order_by("parent_id").first()
    return link.parent if link else None


def _queue_account_issued(*, student=None, parent=None, body, student_id=None):
    """대상이 없으면(연락처 주인이 아무도 없다) 걸지 않는다 — 대상 3분기 계약."""
    if student is None and parent is None:
        return
    queue_notification(
        type=Notification.Type.ACCOUNT_ISSUED,
        channel=Notification.Channel.KAKAO,
        student=student,
        parent=parent,
        title="계정 발급",
        body=body,
        ref_type="students" if student_id else None,
        ref_id=student_id,
    )


def reset_password(user):
    """임시 비밀번호 재발급 — **사람이 되돌린다**(FLOW 2-4).

    학생·학부모가 스스로 복구하는 길은 두지 않기로 했으므로(자기 확인 수단이
    번호 하나뿐이라 탈취에 그대로 열린다), 잊은 사람은 직원에게 말하고 직원이
    이걸 누른다. 새 비밀번호는 **다시 변경 강제** 상태로 나간다 — 임시값이
    영구 비밀번호로 굳는 것을 막는다.

    발급 때와 같은 알림을 건다(같은 값이 같은 경로로 나가야 한다). 응답에도
    1회 실린다 — 해시만 저장되므로 지금이 아니면 볼 수 없다.
    """
    password = generate_initial_password()
    user.set_password(password)
    user.must_change_password = True
    user.save(update_fields=["password", "password_changed_at", "must_change_password"])
    student = Student.objects.filter(user=user).select_related("user").first()
    if student is not None:
        _notify_credentials(student, user.login_id, password)
    else:
        parent = Parent.objects.filter(user=user).first()
        _queue_account_issued(
            parent=parent,
            body=f"{user.name} 아이디 {user.login_id} 비밀번호 {password}",
        )
    return password


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


@transaction.atomic
def update_student(student, *, name=None, school=None, grade=None, phone=None, parent_phone=None):
    """학생 정보 수정 — **번호가 바뀌면 아이디·대조키가 다시 만들어진다**(FLOW 2-6).

    지금까지 고칠 자리가 없어서, 번호가 한 자리 틀리게 들어온 학생은 계속 남의
    번호로 문자·청구를 받았고 아이디·대조키도 그 틀린 번호에서 나온 채였다.
    남은 수단이 "지우고 다시 발급" 인데 그러면 출결·성적이 딸려 나간다.

    **아이디를 다시 만드는 기준은 대조키다.** 대조키 = `{이름}{뒷4자리}` 이고
    아이디는 거기에 충돌 접미사만 붙인 값이라(login_id·matching_key 모듈),
    "대조키가 달라졌다" 와 "아이디의 근거가 달라졌다" 는 같은 말이다. 학교·학년만
    고치면 아무것도 다시 만들지 않는다.

    | 바뀐 것 | 하는 일 |
    |---|---|
    | 학교·학년 | 저장만 |
    | 이름·학생 번호(대조키가 달라짐) | 대조키·아이디·비밀번호 재생성 → 안내 재발송 |
    | 학부모 번호 | 학부모 번호 정정 → 그 학부모 안내 재발송 |

    **이미 낸 답안지는 건드리지 않는다**(FLOW 2-6). OMR·워크북은 제출 시점에
    학생 행을 이미 물었고(answer_sheets.student), 지면에서 읽은 값은 그때 읽은
    그대로(`recognized_matching_key`) 남는다 — 소급해 다시 대조하면 조교가 손으로
    고른 것까지 뒤집힌다. 수강·출결·성적도 그대로다: 계정을 다시 만드는 것이
    아니라 아이디와 비밀번호만 다시 만든다.

    **청구 재발송은 하지 않는다.** 학부모 번호가 틀렸으면 청구서도 엉뚱한 번호로
    간 것이지만(FLOW 2-6), 그건 업체를 부르는 일이고 부분 환불이 안 돼 취소+재청구
    한 쌍이다 — 결제 관리 화면에서 사람이 취소하고 다시 청구한다. 이미 나간 주문의
    `billed_to_phone` 은 그때 번호 그대로 남는다(스냅샷).

    돌려주는 것은 **한 번만 볼 수 있는 값**뿐이다(`initial_password` —
    해시만 저장되므로 응답을 닫으면 다시 볼 수 없다. 알림 템플릿 승인 전까지는
    이것이 유일한 전달 경로다 — 모듈 docstring).
    """
    user = student.user
    if user is None:
        raise ValueError("계정이 없는 학생입니다.")

    if school is not None:
        student.school = school.strip()
    if grade is not None:
        student.grade = grade.strip()

    name = nfc(name).strip() if name is not None else user.name
    if not name:
        raise ValueError("이름이 필요합니다.")
    phone = normalize_phone(phone) if phone is not None else user.phone
    current_parent = _notify_target_parent(student)
    # 빈 학부모 번호는 "안 고친다" 로 읽는다 — 연결을 끊는 것은 수정이 아니다.
    new_parent_phone = normalize_phone(parent_phone) if parent_phone else ""
    parent_phone_now = new_parent_phone or (current_parent.phone if current_parent else "")

    try:
        matching_key = build_matching_key(name, phone, parent_phone_now)
    except LoginIdError as exc:
        raise ValueError(str(exc)) from exc

    reissue = matching_key != student.matching_key
    user.name = name
    user.phone = phone
    if reissue:
        try:
            user.login_id = resolve_collision(matching_key)
        except LoginIdError as exc:
            raise ValueError(str(exc)) from exc
        student.matching_key = matching_key
    user.save(update_fields=["name", "phone", "login_id"])
    student.save(update_fields=["school", "grade", "matching_key"])

    # 학부모를 먼저 정리한다 — 번호 없는 학생의 계정 안내는 학부모에게 가므로
    # (`_notify_credentials`), 순서가 뒤바뀌면 방금 고친 번호가 아니라 틀린
    # 번호로 다시 나간다.
    parent_needs_notice = bool(new_parent_phone) and _set_parent_phone(
        student, current_parent, new_parent_phone, name, user.login_id
    )
    result = {"initial_password": None, "parent_initial_password": None}
    if reissue:
        result["initial_password"] = reset_password(user)
    if parent_needs_notice:
        parent = _notify_target_parent(student)
        if parent is not None and parent.user is not None:
            result["parent_initial_password"] = reset_password(parent.user)
    return result


def _set_parent_phone(student, current, parent_phone, student_name, student_login_id):
    """학부모 번호를 고친다 — 계정 안내를 다시 보내야 하면 True.

    **그 번호를 이미 쓰는 학부모가 있으면 새로 만들지 않고 그쪽으로 옮긴다.**
    형제가 먼저 등록해 둔 경우가 그렇다(FLOW 2-3) — 한 번호에 학부모 계정이 둘
    생기면 청구도 알림도 둘로 갈린다. 그 계정의 안내는 이미 맞는 번호로 나갔으니
    다시 보낼 것이 없다(False).

    번호를 제자리에서 고친 경우와 새로 만든 경우는 True 다 — 어느 쪽이든 그
    학부모는 **자기 번호로 아이디를 받은 적이 없다**.
    """
    if current is None:
        return _link_parent(parent_phone, student_name, student_login_id, student)["created"]
    if current.phone == parent_phone:
        return False
    other = (
        Parent.objects.filter(phone=parent_phone)
        .exclude(pk=current.pk)
        .order_by("parent_id")
        .first()
    )
    if other is not None:
        ParentStudent.objects.get_or_create(parent=other, student=student)
        ParentStudent.objects.filter(parent=current, student=student).delete()
        return False
    current.phone = parent_phone
    current.save(update_fields=["phone"])
    if current.user is not None:
        current.user.phone = parent_phone
        current.user.save(update_fields=["phone"])
    return True
