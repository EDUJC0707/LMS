# 결제선생 트랙 — 시작 프롬프트

이 파일 전체를 새 세션에 붙여넣는다.

---

## 너는 결제 트랙을 맡는다

저장소: `/Users/seanpark/Desktop/edujc/LMS`
**네 작업 폴더**: `.claude/worktrees/payment` — 여기서만 일한다.
**네 브랜치**: `payment` (방금 통합된 `main` 에서 갈라져 나왔다)
**네 DB**: `lms_payment` — 이미 `migrate` + `seed_demo` 까지 돼 있다

### 시작 전에 반드시

1. **`.claude/CLAUDE.md` 를 읽어라.** 이 저장소의 규칙이고, 어기면 되돌리는 비용이 크다.
   특히 §1(저장소 구조) · §2(커밋·영어 커밋 메시지) · §7(스킬·에이전트) ·
   §8(UI 문구 금지) · §9(세션이 여럿일 때).
2. **`.claude/key_considerations.md` §4** — 추상화 경계. 이 트랙의 핵심이다.
3. **스킬은 반드시 Skill 툴로 invoke** 한다(§7). 파일을 Read 해서 흉내내는 것은 금지.
   구현 전 `superpowers:test-driven-development`,
   완료 주장 전 `superpowers:verification-before-completion`.
4. 메인 폴더(`/Users/.../LMS`)에서 일하지 마라. 개발 서버도 한 세션만 띄운다 —
   `lsof -ti:5173` / `:8000` 으로 먼저 확인해라.

---

## 지금 무엇이 있고 무엇이 없나

**있다** — 스키마는 이미 서 있고, 그것도 **업체 중립으로** 설계돼 있다.
`backend/apps/payments/models.py`:

- `Product`(상품) · `Order`(주문) · `Payment`(결제 트랜잭션)
- `Payment.provider` 는 값집합(`결제선생`), `external_ref` 는 **중립 외부 참조**
- 모델 docstring 에 계약이 적혀 있다: *"결제 로직은 앱 레이어의 Provider 인터페이스로
  감싸고, DB 는 provider 값과 중립 외부 참조만 저장한다 — 업체 종속 컬럼 금지"*

이 계약은 이 저장소에서 **가장 자주 인용되는 선례**다. 영상(`videos.Video`)도
알림(`notifications`)도 화상(`clinic`)도 전부 "payments 선례" 라고 적으며 같은 모양을 따랐다.
**네가 그 선례를 깨면 셋이 같이 흔들린다.**

**없다** — 소비할 수 있는 것이 하나도 없다.

    apps/payments/views.py    → View 클래스 0개
    apps/payments/urls.py     → 빈 DefaultRouter
    apps/payments/tests.py    → 모델 테스트만

주문·결제 화면도, 관리 API 도 없다. 시드가 주문 6건을 만들지만 아무도 못 본다.

**이 상태가 위험한 이유**를 영상 트랙이 먼저 겪었다(2026-08-04):
권한 모델·자동 지급 트리거·관리 화면이 다 있는데 **소비를 막는 코드가 한 줄도 없어서**,
번호만 알면 누구나 접근할 수 있었다. "관리 쪽이 다 됐다"를 완료로 착각한 것이 원인이다.
**완료 판정은 소비 엔드포인트가 게이트를 지나는 테스트가 있는가**로 한다.

---

## 막혀 있는 것 — 먼저 확인하고 시작해라

**결제선생 연동 스펙이 아직 없다.** `.claude/to-do.md` 에 "결제선생 연동 스펙" 이
미해결로 있고, `local/서비스-계정-현황.md` 의 결제선생 항목은 *"로그인: 미정 ·
비용: 상담 진행 중"* 이다.

**스펙이 없는 동안 살아남을 전제의 코드를 쓰지 마라**(CLAUDE.md 의 착수 원칙 —
"설계 문서가 확정되기 전에는 살아남을 전제의 코드를 쓰지 않는다").
지금 API 를 상상해서 만들면 스펙이 오는 순간 전부 버린다.

### 그래서 스펙 없이 할 수 있는 것

1. **소비 경로를 만든다.** 결제선생과 무관하게, 우리 쪽에서 이미 결정된 것들:
   - 학생·학부모가 **자기 주문·결제 상태를 본다**(PRD 3.1.5)
   - 관리자가 **결제 내역·배부 상태를 조회한다**
   - 이건 우리 DB 안에서 끝나는 일이라 업체가 정해지지 않아도 만들 수 있다
2. **Provider 인터페이스를 세운다.** 어댑터 계약(추상 클래스 + 예외 종류)만 먼저.
   구현체는 스펙이 오면 그 뒤에 넣는다. 선례가 둘 있으니 그대로 따라라 —
   `apps/clinic/conferencing.py`(화상) · `apps/notifications/channels.py`(알림).
   둘 다 "어댑터는 ORM 을 모르고, 재시도 여부는 예외 종류가 말한다" 는 같은 모양이다.
3. **조사를 남긴다.** 결제선생 공개 문서를 찾을 수 있으면 조사해서
   `local/sources/research/YYYY-MM-DD-결제선생-조사.md` 로 남겨라(작업 표면에 만들지 마라 — §1·§3).
   **스펙이 오면 무엇을 물어야 하는지** 질문 목록을 만들어 두면 대표가 그대로 쓴다:
   웹훅 유무 · 부분 환불 · 대사(reconciliation) 방식 · 테스트 환경 · 정산 주기.

### 하지 마라

- 상상한 API 로 어댑터 **구현체**를 쓰는 것
- `Payment` 에 `payssam_*` 같은 업체 이름 컬럼을 더하는 것 — 계약 위반이고 선례를 무너뜨린다
- 돈이 나가는 계정을 만드는 것(§ 대표 확인 사항)

---

## 이 저장소에서 오늘 배운 것 (같은 함정을 피해라)

병합에서 **git 이 충돌 없이 합쳐 놓고 런타임에 죽은 것**이 셋 나왔다:

1. 두 트랙이 `CELERY_BEAT_SCHEDULE = {...}` 를 **각자 새로** 만들어 뒤엣것이 앞을 덮었다.
   → 주기 작업을 더할 때는 **새 대입이 아니라 기존 딕셔너리에 키를 더한다**
2. 한 트랙이 컬럼을 개명했는데(`unique_id` → `matching_key`) 먼저 갈라진 코드가
   옛 이름을 쓰고 있었다 → 합친 뒤 `TypeError`
3. `accounts/0004` 가 두 개 생겨 마이그레이션 리프가 둘이 됐다
   → **마이그레이션을 만들기 전에 `main` 의 현재 번호를 확인**해라.
   `git fetch && git log origin/main` 후 해당 앱의 마지막 번호를 보고 그다음을 쓴다

그리고 프런트에는 상시 함정이 하나 있다:
**`useApiAction` 은 첫 렌더의 클로저를 붙든다**(`frontend/src/api/useApi.ts`).
폼 값을 클로저로 읽으면 항상 빈 폼이 나간다 — **인자로 넘겨라.**
목록 행마다 버튼을 그릴 때 `loading={action.pending}` 을 물리면 **모든 행이 함께 돈다**
(그 훅의 pending 은 페이지에 하나뿐이다). 진행 중인 행 id 를 따로 들어라.

---

## 검증

    cd backend
    DATABASE_URL="postgres://lms:lms@localhost:5432/lms_payment" .venv/bin/python manage.py test apps -v 0
    .venv/bin/ruff check apps config
    cd ../frontend && npm run typecheck && npm run build && npm test

**전체가 1070건 통과하는 상태에서 시작한다.** 네가 깨뜨리면 네 것이다.
커밋은 검증 통과한 논리 단위마다(§2), **영어로, 표준 git 형식**으로.
push 는 사용자 지시가 있을 때만.

---

## 처음에 할 일

1. `.claude/CLAUDE.md` · `key_considerations.md` §4 읽기
2. `backend/apps/payments/models.py` 정독 — 계약이 무엇을 금지하는지
3. `apps/clinic/conferencing.py` 와 `apps/notifications/channels.py` 를 읽고
   **이 저장소의 어댑터 모양**을 익히기
4. `docs/PRD.md` 3.1.5(결제·교재 배부) 와 `docs/decisions.md` 에서 결제 관련 확정 사항 찾기
5. **무엇이 스펙 없이 가능하고 무엇이 아닌지**를 정리해 사용자에게 보고하고 시작
