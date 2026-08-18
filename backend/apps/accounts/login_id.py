"""로그인 아이디 생성 규칙 — **유일한 준거** (PRD 8-4 개정, 2026-07-28 사용자 지시).

구 규칙(아이디 = 휴대폰 번호)을 한글 기반으로 바꾼다. 계정 일괄 발급
(`provisioning.py`)·직원 생성(`staff_admin.py`)·시드(`seed_demo`)가 전부 이
모듈을 경유한다 — 규칙이 두 곳에 흩어지면 발급 경로마다 아이디 체계가 갈린다.

## 규칙

| 대상 | 형식 | 예 |
|---|---|---|
| 학생 | `{이름}{휴대폰 뒷4자리}` | `김하늘4821` |
| 학부모 | `{학생 아이디}p` | `김하늘4821p` |
| 직원(대표·관리자·조교) | `{이름}{휴대폰 뒷4자리}` | `한종철0001` |

- **무전화 학생**: 학부모 휴대폰 뒷4자리를 쓴다. 학생·학부모가 같은 뒷4자리를
  공유하되 `p` 로 구분된다(`김하늘4821` / `김하늘4821p`).
- **학부모는 자녀 이름을 빌린다**: 학부모 아이디는 학생 아이디에서 파생되므로
  학생 아이디가 유일하면 학부모 아이디도 자동으로 유일하다.

### 직원도 학생과 같은 축을 쓰는 근거(2026-07-28 판단)

① 규칙을 하나로 유지한다 — 직원만 휴대폰 아이디를 남기면 이 모듈이 두 체계를
   떠안고, "아이디 형식"이 역할별로 갈린다. ② 직원 아이디는 권한 매트릭스
   화면(`staff_admin.matrix_row`)에 그대로 노출되는데, 휴대폰 아이디는 직원
   연락처를 다른 직원에게 상시 노출한다(개인정보 최소 원칙). ③ 직원은 `p`
   접미사를 쓰지 않고 로그인 경로도 분리되어 있어 소비자 아이디와 섞이지 않는다.

### 다자녀 학부모 — 어느 자녀 이름을 쓰는가

**학부모 계정을 처음 만들게 한 자녀(최초 연결 자녀) 기준.** 학부모 계정은
전화번호로 식별되어 하나만 존재하고(`provisioning._link_parent`), 둘째부터는
`parent_students` 연결만 추가되므로 아이디는 최초 발급 시점 그대로 유지된다.
"가장 어린/최근 자녀" 같은 기준은 동생이 등록할 때마다 아이디가 바뀌어
재로그인 혼란·계정정보 재발송을 부르므로 택하지 않는다.

### 충돌 처리

동명이인 + 같은 뒷4자리가 가능하다. 충돌 시 뒤에 한 글자 접미사를 붙인다
(`김민준1234a`, `김민준1234b`, …). **원번(`matching_key.py`)은 이 접미사를 붙이지
않는다** — 원번 == 아이디에서 접미사를 뗀 값이고, 겹치는 원번은 매칭에서 중복으로
떨어뜨려 사람이 고른다(그쪽 모듈의 중복 절이 근거). **접미사 집합에서 `p` 를 제외**한다 —
`p` 를 허용하면 충돌 해소된 학생 아이디가 다른 학생의 학부모 아이디와 같은
문자열이 될 수 있다. 접미사는 한 글자뿐이므로 학부모 아이디(`…p`, `…ap`)는
어떤 학생 아이디와도 겹치지 않는다. 25개 소진 시 `LoginIdError`(발급 실패).

### 전화번호 정규화

번호는 **저장 전에** `normalize_phone` 을 통과한다. 아이디·대조키의 뒷4자리도,
계정 판정(`provisioning._match_existing`)도 같은 값을 봐야 하기 때문에
규칙이 여기 한 곳에 있다.

| | |
|---|---|
| `-` · 공백 · 괄호 · 점 | 뗀다 |
| `+82` | `0` 으로 바꾼다(`+82 10-…` · `+82 010-…` 둘 다) |
| 10자리이면서 `10` 으로 시작 | 앞에 `0` 을 되살린다 |

**엑셀이 전화번호를 숫자로 읽으면 `010…` 이 `10…` 이 된다**(FLOW 2-2). 그 한
자리가 빠진 채 저장되면 같은 학생이 둘로 갈린다.

되살리는 것은 **휴대폰뿐이다.** `02`·`070` 을 어떻게 볼지는 아직 정해지지
않았고(FLOW 질문 표 — 2-2), 자릿수를 건드리면 되돌릴 수 없다. 그래서 `10`+8자리
라는 한 가지 모양에만 `0` 을 붙이고 나머지는 자릿수를 그대로 둔다 — 국내 번호에
`10` 으로 시작하는 10자리는 휴대폰 말고 없다.

### 이름 정규화

**먼저 NFC 로 합친다**(FLOW 2-2 ①). 맥에서 만든 파일의 한글은 자모가 분해된
NFD 로 오는데(`김` = `ᄀ`+`ᅵ`+`ᆷ`), 그 자모는 아래 문자류에 없어 통째로 지워진다 —
이름이 빈 문자열이 되어 행이 실패하거나, 같은 학생이 NFC·NFD 두 벌로 갈린다.
눈에 같은 글자는 같은 값이어야 한다.

공백·특수문자·구두점을 모두 제거하고 한글·영문·숫자만 남긴다. 영문은 소문자로
통일한다(대소문자만 다른 아이디가 갈라지는 것을 막는다). 정규화 후 20자로
자른다 — `users.login_id` 가 50자이고 뒷4자리+`p`+접미사가 붙기 때문.

## 순수성

규칙 함수는 전부 순수하다. 충돌 해소만 "이미 쓰는 아이디인가"를 알아야 하므로
`is_taken` 술어를 주입받는다(미지정 시 users 테이블 조회). 덕분에 규칙 전수
테스트가 DB 없이 성립한다.
"""
import re
import unicodedata

# 충돌 접미사 — p 는 학부모 표식이라 제외(모듈 docstring 충돌 처리 절).
COLLISION_SUFFIXES = "abcdefghijklmnoqrstuvwxyz"
PARENT_SUFFIX = "p"

# 정규화 후 남길 문자: 한글(음절·자모)·영숫자.
_KEEP = re.compile(r"[^0-9a-z가-힣ㄱ-ㅎㅏ-ㅣ]")
_DIGITS = re.compile(r"\D")
_NAME_MAX = 20
_PHONE_TAIL = 4

# 정규화 시 남길 문자 — 숫자와 국가번호 `+`(하이픈·공백·괄호·점을 뗀다).
_PHONE_KEEP = re.compile(r"[^0-9+]")
_MOBILE_LEN = 11  # 010 + 8자리


class LoginIdError(ValueError):
    """아이디를 만들 수 없다 — 메시지가 발급 리포트의 실패 사유로 나간다."""


def nfc(raw) -> str:
    """맥에서 오는 분해형(NFD) 한글을 합친다 — 이름이 들어오는 자리마다 통과시킨다."""
    return unicodedata.normalize("NFC", raw) if isinstance(raw, str) else raw


def normalize_name(raw) -> str:
    """이름 정규화 — NFC 합성 · 공백·특수문자 제거 · 영문 소문자화 · 20자 상한."""
    if not isinstance(raw, str):
        raise LoginIdError("이름이 필요합니다.")
    cleaned = _KEEP.sub("", nfc(raw).strip().lower())
    if not cleaned:
        raise LoginIdError("이름에서 아이디로 쓸 수 있는 글자를 찾지 못했습니다.")
    return cleaned[:_NAME_MAX]


def normalize_phone(raw) -> str:
    """전화번호 정규화 — 구분자 제거 · `+82`→`0` · 사라진 앞자리 `0` 복원.

    읽을 수 없는 값은 빈 문자열이다(호출자가 "번호 없음"으로 다룬다).
    """
    if not isinstance(raw, str):
        return ""
    value = _PHONE_KEEP.sub("", raw)
    if value.startswith("+82"):  # +82 10-… 도 +82 010-… 도 국내 표기로 되돌린다
        value = "0" + value[3:].lstrip("0")
    digits = _DIGITS.sub("", value)
    if len(digits) == _MOBILE_LEN - 1 and digits.startswith("10"):
        digits = "0" + digits  # 엑셀이 숫자로 읽어 떨어뜨린 앞자리
    return digits


def phone_tail4(phone) -> str:
    """휴대폰 뒷4자리 — 하이픈·공백 등 구분자를 지우고 마지막 4자리."""
    if not isinstance(phone, str):
        raise LoginIdError("휴대폰 번호가 필요합니다.")
    digits = _DIGITS.sub("", phone)
    if len(digits) < _PHONE_TAIL:
        raise LoginIdError("휴대폰 번호가 올바르지 않습니다.")
    return digits[-_PHONE_TAIL:]


def student_phone_tail4(phone, parent_phone="") -> str:
    """학생의 뒷4자리 — 본인 번호 우선, 없으면 학부모 번호(8-3 무전화 학생).

    아이디와 **원번(`matching_key.py`)이 공유하는 규칙**이라 여기 한 곳에 둔다 —
    두 모듈이 각자 "번호가 없으면 학부모 번호" 를 구현하면 언젠가 갈린다.
    """
    source = phone if _has_digits(phone) else parent_phone
    if not _has_digits(source):
        raise LoginIdError("학생 또는 학부모의 휴대폰 번호가 필요합니다.")
    return phone_tail4(source)


def person_base(name, phone) -> str:
    """사람 아이디의 원형 = 정규화 이름 + 뒷4자리 (충돌 미해소)."""
    return f"{normalize_name(name)}{phone_tail4(phone)}"


def resolve_collision(base, is_taken=None) -> str:
    """비어 있으면 base 그대로, 아니면 첫 빈 접미사를 붙인다. 소진 시 오류."""
    taken = _default_is_taken if is_taken is None else is_taken
    if not taken(base):
        return base
    for suffix in COLLISION_SUFFIXES:
        candidate = f"{base}{suffix}"
        if not taken(candidate):
            return candidate
    raise LoginIdError(f"아이디 접미사가 소진되었습니다: {base}")


def issue_student_login_id(name, phone, parent_phone="", is_taken=None) -> str:
    """학생 아이디 — 본인 휴대폰 뒷4자리, 없으면 학부모 번호 뒷4자리(8-4)."""
    tail = student_phone_tail4(phone, parent_phone)  # 번호 판정이 이름 정규화보다 먼저
    return resolve_collision(f"{normalize_name(name)}{tail}", is_taken)


def issue_parent_login_id(student_login_id, is_taken=None) -> str:
    """학부모 아이디 — 자녀(최초 연결 자녀) 아이디 + p(모듈 docstring)."""
    if not (isinstance(student_login_id, str) and student_login_id):
        raise LoginIdError("학생 아이디가 필요합니다.")
    return resolve_collision(f"{student_login_id}{PARENT_SUFFIX}", is_taken)


def issue_staff_login_id(name, phone, is_taken=None) -> str:
    """직원 아이디 — 학생과 동일 축(모듈 docstring 직원 근거 절)."""
    return resolve_collision(person_base(name, phone), is_taken)


def _has_digits(value) -> bool:
    return isinstance(value, str) and bool(_DIGITS.sub("", value))


def _default_is_taken(login_id) -> bool:
    """기본 술어 — users 테이블이 준거. 임포트 순환을 피해 지연 임포트한다."""
    from .models import User

    return User.objects.filter(login_id=login_id).exists()
