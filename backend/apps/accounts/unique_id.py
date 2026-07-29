"""원번(`students.unique_id`) 생성 규칙 — **유일한 준거** (2026-07-29 사용자 확정).

원번은 관리자가 손으로 적어 넣는 값이 아니라 **(학년, 이름, 휴대폰)에서 계산되는
파생값**이다. 계정 일괄 발급(`provisioning.py`)·시드(`seed_demo`)·학년 승급
(`promote_grade`)이 전부 이 모듈을 경유한다 — 규칙이 두 곳에 흩어지면 발급
경로마다 원번 체계가 갈린다(`login_id.py` 와 같은 결).

## 규칙

| 대상 | 형식 | 예 |
|---|---|---|
| 원번 | `{학년숫자}{이름}{휴대폰 뒷4자리}` | `3김하늘4821` |
| OMR 숫자부 | `{학년숫자}{휴대폰 뒷4자리}` | `34821` |

로그인 아이디가 `{이름}{뒷4}`(`김하늘4821`)이므로 **원번 = 학년 + 로그인아이디
몸통**이다. 이름 정규화·뒷4자리 추출은 `login_id.py` 함수를 그대로 재사용한다
(무전화 학생이 학부모 번호 뒷4자리를 쓰는 8-3 규칙도 그 함수가 이미 가진다).

## 원번은 가변, 아이디와 학생번호는 불변

학년이 원번의 일부이므로 **학년이 오르면 원번이 바뀐다**(구 PRD 3.1.1 의 "원번
불변"은 2026-07-29 뒤집혔다). 반면 `users.login_id` 와 `students.student_id` 는
승급이 건드리지 않는다 — 아이디가 바뀌면 재로그인 혼란·계정정보 재발송이
생기고, `student_id` 는 전 도메인 FK 의 대상이라 애초에 바뀔 수 없다.

## OMR 이 읽는 것은 숫자부뿐 (설계 근거)

이름은 한글이라 OMR 버블(0~9)로 마킹할 수 없다. 그래서 답안지는 **숫자부
5칸(학년 1 + 뒷4 = 5자리)만 마킹**하고 **이름은 손으로** 쓴다. 즉 원번의 숫자부가
기계가 읽는 키이고, 이름은 사람이 확인하는 축이다 — `numeric_key()` 가 그
숫자부이며 OMR 매칭이 이 값을 쓴다.

## 원번은 단독 UNIQUE 가 아니다

같은 학년·같은 이름·같은 뒷4자리가 이론상 가능하다. 그래서 원번은 **이름과
함께 쓰는 매칭키**이고 컬럼에는 인덱스만 있다(`models.Student.unique_id` 계약).
아이디처럼 접미사로 충돌을 해소하지 않는 이유가 여기 있다 — 원번은 학년에서
재계산되는 값이라, 접미사를 붙이면 승급 때마다 접미사가 재추첨되어 같은
사람의 원번이 이유 없이 흔들린다.

## 학년 파싱

`students.grade` 는 `고1`·`고2`·`고3`·`N수` 형태의 자유 문자열이다.

| 학년 | 자리값 |
|---|---|
| 고1 | 1 |
| 고2 | 2 |
| 고3 | 3 |
| **N수·재수** | **4** |

`N수` 는 숫자가 없으므로 이름으로 알아본다(2026-07-29 사용자 확정 — "n수는
학년이 4야 그게 끝"). 그 밖의 표기는 **숫자 한 자리**를 뽑는다(`중3` 처럼 다른
표기도 숫자가 하나면 통과). 숫자가 없거나 둘 이상이면 어느 쪽이 학년인지 알 수
없으므로 `UniqueIdError` 를 던지고, 호출자가 그 행만 실패시킨다(일괄 발급은 행
단위 savepoint 구조) — 조용히 틀린 원번을 만드는 것보다 낫다.

**`고4` 는 없다.** 자리값 4 는 오직 N수를 뜻한다.

## 순수성

전 함수가 순수하다. DB 도 `is_taken` 같은 술어도 필요 없다 — 원번은 충돌을
해소하지 않으므로 "이미 쓰는 값인가"를 물을 이유가 없다.
"""
import re

from .login_id import normalize_name, student_phone_tail4

_DIGITS = re.compile(r"\d")

# 숫자 없는 학년 표기 → 자리값. N수 = 4 (2026-07-29 사용자 확정).
# 공백을 지우고 대문자로 맞춘 뒤 대조하므로 `n수`·`N 수`·`재수` 가 모두 걸린다.
_NAMED_GRADES = {"N수": "4", "재수": "4", "N": "4"}


class UniqueIdError(ValueError):
    """원번을 만들 수 없다 — 메시지가 발급·승급 리포트의 실패 사유로 나간다."""


def grade_digit(grade) -> str:
    """학년 문자열 → 자리값 한 자리. `고2` → `2`, `N수` → `4`.

    (모듈 docstring 학년 파싱 절 — 표가 유일한 준거다.)
    """
    if not isinstance(grade, str):
        raise UniqueIdError("학년이 필요합니다.")
    named = _NAMED_GRADES.get("".join(grade.split()).upper())
    if named is not None:
        return named
    digits = _DIGITS.findall(grade)
    if not digits:
        raise UniqueIdError(f"학년에서 숫자를 찾지 못했습니다: {grade.strip() or '(빈값)'}")
    if len(digits) > 1:
        raise UniqueIdError(f"학년 표기에 숫자가 둘 이상입니다: {grade.strip()}")
    return digits[0]


def build_unique_id(grade, name, phone, parent_phone="") -> str:
    """원번 전체 = 학년숫자 + 정규화 이름 + 뒷4자리."""
    prefix = grade_digit(grade)
    tail = student_phone_tail4(phone, parent_phone)  # 번호 판정이 이름 정규화보다 먼저
    return f"{prefix}{normalize_name(name)}{tail}"


def numeric_key(grade, phone, parent_phone="") -> str:
    """OMR 이 읽는 숫자부 5자리 = 학년숫자 + 뒷4자리(모듈 docstring OMR 절)."""
    return f"{grade_digit(grade)}{student_phone_tail4(phone, parent_phone)}"
