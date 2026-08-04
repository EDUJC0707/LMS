# 외부 서비스 연동 — 에이전트 인계 프롬프트

각 절을 **통째로 복사해서** 다른 에이전트에게 준다. 저장소 루트는
`/Users/seanpark/Desktop/edujc/LMS` 이며, 프롬프트마다 읽을 파일이 명시돼 있다.

---

## 0. 모든 연동에 공통 (각 프롬프트 앞에 붙는다)

```
저장소: /Users/seanpark/Desktop/edujc/LMS
한종철 LMS — Django/DRF 백엔드 + Vite/React 프런트. 코드·주석·값집합이 전부 한국어다.

## 시작 전에 반드시 읽어라 (순서대로)

1. `.claude/CLAUDE.md` — 이 저장소의 규칙. 특히:
   §1 저장소 구조(작업 표면 밖에 파일 만들지 마라) · §2 커밋/삭제 ·
   §7 에이전트·스킬 · §8 UI 문구 금지 · §9 소통(한국어, 결과·판단 중심)
2. `.claude/key_considerations.md` — 설계 태도. **§4 추상화 경계**가 이 작업의 핵심이다.
3. `docs/decisions.md` — 확정된 것. 뒤집힌 결정도 표시돼 있다.
4. `.claude/to-do.md` — 지금 무엇이 막혀 있는지. 네 작업 항목이 여기 있다.

## 이 저장소의 절대 규칙 — 업체 종속 금지

**외부 업체 이름이 DB 스키마에 새어 들어가면 안 된다.** 이건 이 저장소에서 가장
강하게 지켜지는 계약이고, 테스트가 실제로 막고 있다.

읽어라: `backend/apps/notifications/models.py` 첫 docstring(§채널 추상화 계약)과
`backend/apps/notifications/tests.py:65` 부근 — `solapi_message_id`,
`kakao_template_code`, `biztalk_ref` 같은 컬럼이 **존재하면 실패하는 테스트**가 있다.

선례도 읽어라: `backend/apps/payments/models.py`, `backend/apps/videos/models.py`
(Video 클래스 docstring "Provider 중립 계약"). 패턴은 항상 같다 —
**`provider` 값 + 중립 참조 ID만 저장하고, 업체별 구현은 앱 레이어의 어댑터가 진다.**

## 작업 방식

- 스킬은 **반드시 Skill 툴로 invoke**한다. 파일을 Read 해서 흉내내는 것은 금지다.
  구현 전 `superpowers:test-driven-development`, 완료 주장 전
  `superpowers:verification-before-completion` 을 invoke하고,
  **보고에 invoke 증빙(로드된 경로)을 포함**해라.
- 테스트 먼저 → 구현 → 검증. 813개 기존 테스트를 깨뜨리지 마라.
- 검증 명령: `cd backend && .venv/bin/python manage.py test apps -v 0` (전체)
  · `.venv/bin/ruff check apps config` · 프런트는 `cd frontend && npm run typecheck && npm run build`
- DB가 안 떠 있으면 `docker compose up -d` (postgres + redis).
- **커밋은 논리 단위로 해도 되지만 push는 하지 마라.**
- **UI에 설명 문구를 넣지 마라**(§8). 로딩·에러·결과 문구만 허용되고,
  부제·요약·집계·도움말은 금지다. 기본값은 아무것도 넣지 않는 것이다.
- 값(API 키·DSN 등)이 없어서 막히면 **거기서 멈추고 무엇이 필요한지 보고**해라.
  가짜 값으로 진행하지 마라.
```

---

## 1. 솔라피 (알림톡·SMS) — 가장 크고 가장 막혀 있다

```
## 목표
알림 발송 파이프라인을 만든다. 지금 `notifications` 앱에는 **이력 모델만 있고
발송 코드가 0건**이며, Celery 태스크도 0건이다.

## 읽어라
- `backend/apps/notifications/models.py` 전문 — Notification 모델. **채널 추상화
  계약**과 `type` 이 개방 값집합인 이유(발송 시점 목록이 미결이라)를 반드시 이해해라.
- `backend/apps/notifications/tests.py` — 업체 종속 컬럼 부재 테스트
- `backend/apps/notifications/views.py`, `me_urls.py` — 기존 조회 API
- `docs/PRD.md` 3.1.2(알림 발송) 및 §8-17(미결 항목 표)
- `backend/config/celery.py` + `backend/config/settings/base.py:95-105`(CELERY_*)
- `infra/DEPLOY.md` 6장 — **Celery 워커가 왜 아직 안 떠 있는지**와 복구 3단계
- `.claude/to-do.md` 의 "외부 대기" 절

## 알아야 할 제약 (중요)
1. **발송 시점 전체 목록(PRD 8-17)이 아직 없다.** 카카오 알림톡은 템플릿 사전
   승인제라 문구가 확정돼야 템플릿 개발이 시작된다. 따라서 **"무엇을 언제 보낼지"는
   네 범위가 아니다.** 네가 만드는 것은 **관로**다 — 어댑터 인터페이스, 발송 태스크,
   재시도, 이력 기록.
2. **Celery 워커를 띄우면 돈이 나간다**(월 ~$3.3, auto_stop 대상이 아님).
   `infra/DEPLOY.md` 6장에 "해제 트리거 = 첫 `@shared_task` 작성 시점"이라고
   적혀 있다. 네가 첫 태스크를 쓰는 순간 그 트리거가 발동하므로,
   **워커 기동은 하지 말고 코드만 준비**하고 보고에 그 사실을 적어라.
3. 솔라피 API 키는 아직 없다. **어댑터 인터페이스와 가짜(fake) 구현까지** 만들고,
   실제 HTTP 호출부는 키가 오면 붙이도록 한 곳으로 좁혀 둬라.

## 만들 것
- 채널 어댑터 인터페이스 (문자/알림톡을 채널 값으로 구분, 업체 교체 가능)
- 발송 Celery 태스크 + 실패 시 재시도 + Notification 행 상태 전이(대기→성공/실패)
- 실패 재발송 배치가 쓸 수 있게 — 모델에 이미 부분 인덱스 `idx_notif_status` 가 있다
- 테스트: 어댑터 교체 가능성, 상태 전이, 재시도, **업체 종속 컬럼 부재 유지**

## 보고할 것
- 솔라피 계정·API 키 외에 사람이 줘야 할 값 목록
- 발송 시점 목록이 오면 어디에 무엇을 추가하면 되는지 (한 문단)
```

---

## 2. Sentry — 값 하나면 끝난다

```
## 목표
에러 추적을 붙인다. **코드는 이미 완료돼 있고 DSN 하나만 남았다.**

## 읽어라
- `backend/config/settings/prod.py` — `sentry_sdk.init()` 가 이미 있다.
  DSN 이 있으면 활성화, 없으면 비활성. `send_default_pii=False` 인 이유를 확인해라.
- `backend/pyproject.toml` — `sentry-sdk>=2.14` 의존성이 이미 있다
- `.claude/to-do.md` 의 "배포 전" 절 Sentry 항목 — **경위가 전부 적혀 있다.**
  특히 `fly ext sentry create` 는 **불가**하다(2026-07-28 확인: Fly.io 신규 통합 중단).
  sentry.io 에 직접 가입해야 한다.
- `infra/DEPLOY.md` — 배포·시크릿 설정 절차

## 막혀 있는 것
sentry.io 가입 → 프로젝트 생성(플랫폼 Django) → DSN. **사람이 해야 한다.**
DSN 을 받으면: `fly secrets set SENTRY_DSN="<DSN>" -a edujc-lms`

## 할 것
1. 현재 코드가 정말 완결인지 검증해라 (DSN 없을 때 조용히 비활성인지, 켜졌을 때
   PII 가 안 새는지). 부족하면 채워라.
2. **로컬에서 DSN 없이 부팅되는지** 확인해라 — 없다고 죽으면 안 된다.
3. DSN 을 받은 뒤의 검증 절차를 문서로 남겨라 — 실제 에러 1건을 일부러 내서
   Sentry 대시보드에 뜨는 것까지 확인하는 절차.
4. 이 작업의 **동기**를 잊지 마라: `fly logs` 가 ~30분치만 남아서
   "어제 왜 500 났지"를 사후 추적할 수 없다(2026-07-28 실제로 막혔다).

## 주의
`.env`·시크릿을 **절대 커밋하지 마라**(CLAUDE.md §5).
```

---

## 3. 채널톡 — 랜딩의 유일한 전환 경로

```
## 목표
채널톡 위젯을 랜딩에 붙인다. 주입 자리는 이미 파여 있다.

## 읽어라
- `frontend/landing/chat.js` — `window.__CHANNEL_TALK_KEY__` 를 읽는 자리가
  이미 있다(11번째 줄 부근). 키가 비면 위젯이 안 뜬다.
- `frontend/landing/SPEC.md` — 랜딩 스펙. 채널톡이 3섹션 중 하나다.
- `docs/PRD.md` 3.3.3 — **채널톡이 랜딩의 유일한 전환 경로**다.
  이게 비면 상담 신청 자체가 불가능하다.
- `docs/PRD.md` 9.2 및 §8-18 — 결석생 전화 응대에서 채널톡 통화 기록을 쓰기로
  한 결정(2026-07-21). 즉 채널톡은 랜딩 위젯 이상의 역할이 예정돼 있다.
- `.claude/to-do.md` 의 랜딩 절

## 막혀 있는 것
채널톡 플러그인 키. **사람이 채널톡에 가입하고 발급해야 한다.**

## 할 것
1. 키 주입 경로를 확인해라 — 지금 `window.__CHANNEL_TALK_KEY__` 를 **누가 언제**
   넣는지. 빌드 타임인지 런타임인지 정해져 있지 않으면 정하고 문서화해라.
2. 키가 없을 때 **조용히 아무 일도 안 일어나는지** 확인해라(콘솔 에러 금지).
3. 랜딩은 로컬 정적 페이지다. 실제로 띄워서 위젯 자리가 레이아웃을 깨지 않는지
   **브라우저로 실측**해라 — 모바일 폭(390px)까지.
4. 키를 받은 뒤의 검증 절차를 남겨라.

## 주의
- 랜딩은 `frontend/landing/` 이고 SPA(`frontend/src/`)와 별개다. 섞지 마라.
- **배포 경로가 아직 미정**이다(`.claude/to-do.md` 참조). 결정하지 말고 보고만 해라.
```

---

## 4. Mux — 계정은 무료, DRM 은 런칭 직전

```
## 목표
영상 호스팅을 Mux 실계정에 연결한다. 재생기는 이미 붙어 있고 **공개 데모 ID로**
돌고 있다.

## 읽어라
- `backend/apps/videos/models.py` — Video 클래스 docstring **"Provider 중립 계약"**.
  `provider` + `external_ref`(Mux asset id) 만 저장하고 업체 종속 컬럼은 금지다.
  부분 UQ `uq_videos_provider_ref` 도 확인해라.
- `backend/apps/videos/playback.py` — 재생 판정과 워터마크 조립. **왜 워터마크를
  서버가 완성해서 내리는지** 그 docstring에 적혀 있다(DRM 은 파일 다운로드를 막고,
  워터마크는 화면 녹화를 추적한다 — 서로 다른 구멍).
- `frontend/src/pages/student/StudentVideoPage.tsx` — `playbackIdOf()` 가
  **실계정 전환 지점**이다. `provider`·`external_ref` 가 채워지면 자동으로 그 값을 쓴다.
- `frontend/src/pages/student/video.css` — 워터마크 CSS. 실측으로 세 번 고친
  주석이 있으니 반드시 읽어라(없는 슬롯 / line-height 상속 / 레터박스).
- `docs/decisions.md` §3 — Mux 확정 경위와 **결제를 런칭 직전으로 미룬 결정**
- `.claude/to-do.md` 의 "돈이 나가는 시점" 절

## 절대 하지 마라
**본 영상 라이브러리를 올리지 마라.** Mux 는 무료 등급(`basic`)에 DRM 을 걸 수
없어 `plus` 로 올려야 하는데, basic 으로 먼저 올리면 **전부 다시 올려야 한다**
(4K 100시간 재인코딩 약 $600). `.claude/to-do.md` 에 명시돼 있다.

## 할 수 있는 것
1. **무료 계정 개설**(전송 10만 분 무료)은 돈이 안 든다. 사람이 해야 한다.
2. 실제 강의 영상 **한두 개만** 올려 **한국 재생 품질**을 확인한다.
3. 서버 쪽 Provider 어댑터 — 업로드·자산 조회를 앱 레이어 인터페이스로 만든다.
   `payments.Payment` 선례를 따라라.
4. FairPlay: 재생 환경이 전부 웹인데 iOS 는 브라우저 무관 WebKit 이라
   Widevine 이 안 돈다 → **FairPlay 필요 확정**. Apple Developer 가입이
   리드타임 최장(승인 수일)이고 D-U-N-S 는 회사에 이미 있다.

## 주의
**현재 `provider`/`external_ref` 를 넣을 관리 화면이 없다**(2026-08-04 확인).
그 작업은 메인 세션에서 진행 중이니 **손대지 마라** — 겹친다.
```

---

## 5. 결제선생 — 스펙부터

```
## 목표
결제 연동. 지금은 스펙 자체가 없다.

## 읽어라
- `backend/apps/payments/models.py` 전문 — **이 저장소의 provider 중립 선례**가
  바로 여기다. 다른 연동들이 이 패턴을 인용한다.
- `docs/PRD.md` 3.1.5(결제·교재 배부) — 요구사항
- `docs/decisions.md` — 결제 관련 확정 사항이 있는지 확인
- `.claude/to-do.md` — "결제선생 연동 스펙"이 막힌 항목으로 있다

## 막혀 있는 것
결제선생 연동 스펙(API 문서·계약 조건). **사람이 받아와야 한다.**

## 할 것
스펙이 없으므로 **코드를 쓰지 마라.** 대신:
1. `payments` 앱의 현재 모델이 무엇을 이미 표현하고 있는지 정리해라.
2. 결제선생 공개 문서를 찾을 수 있으면 조사하고 `local/sources/research/` 에
   `YYYY-MM-DD-결제선생-조사.md` 로 남겨라(작업 표면에 만들지 마라 — CLAUDE.md §1·§3).
3. **스펙이 오면 무엇을 물어봐야 하는지** 질문 목록을 만들어라
   (웹훅 유무, 부분 환불, 대사(reconciliation) 방식, 테스트 환경 여부 등).
4. 기존 provider 중립 계약에 결제선생이 들어올 자리가 있는지 판정해라.

## 주의
설계 문서가 확정되기 전에 **살아남을 전제의 코드를 쓰지 마라**(이 저장소의 착수 원칙).
```

---

## 6. 알아둘 것 — 지금 메인 세션이 하는 일

에이전트들이 **겹치지 않도록** 알려 둘 것:

- 메인 세션은 지금 `backend/apps/videos/` 와 `backend/apps/grades/attendance_admin.py`,
  `backend/apps/curriculum/home.py` 를 고치고 있다 (**VideoGrant 지급 단위를
  주차 → 영상으로 바꾸는 리팩터** + 영상 등록 관리 API).
- 따라서 **4번(Mux) 담당은 서버 쪽 videos 파일을 건드리지 마라.** 계정 개설·품질
  확인·조사까지만 한다.
- 1·2·3·5번은 파일이 겹치지 않는다.
