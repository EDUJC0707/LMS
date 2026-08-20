# EduJC 인프라 구조 (living doc)

> 최종 갱신: 2026-08-20 — `flyctl machines list` 실측 반영.
> **가동 현황의 기준은 [`infra/DEPLOY.md`](../../infra/DEPLOY.md) 다.** 머신·시크릿·비용은 거기 한 곳에만 적는다 —
> 2026-07-21 부터 이 문서가 따로 들고 있다가 한 달 내내 틀린 값을 말했다.
> 이 문서에 남는 것은 **구조 그림과 계정·권한**이다.

## 1. 전체 구조

**레포 2개 · 백엔드 앱 2개 · DB 서버 1대 · 프런트는 Vercel.**

```
                        ┌─ GitHub (레포 2개) ─────────────────┐
                        │  EDUJC0707/LMS      → edujc-lms     │
                        │  (도훈 레포)         → edujc-qbank   │
                        └─────────────────────────────────────┘

Vercel ──────────────┐            Fly.io org: EDUJC (slug: edujc, 도쿄 nrt)
  LMS 프런트          │   API      ┌──────────────────────────────────────────┐
  (React SPA,        ├──────────▶ │ app edujc-lms    Django+DRF  ✅ 배포됨     │
   frontend/ 디렉터리) │            │ app edujc-qbank  Django      🔲 앱만 생성  │
                     │            │ app edujc-pg     PostgreSQL  ✅            │
                     │            │   ├ database lms   (user lms)   ← LMS 전용 │
                     │            │   └ database qbank (user qbank) ← 문제툴 전용│
                     │            └──────────────────────────────────────────┘
                     │            (예정) Tigris 버킷 2개 · Upstash Redis
```

**원칙**
- 같은 인프라(org·리전·DB서버)를 공유하되, **앱·데이터베이스·레포는 각자 분리**. 한쪽 배포가 다른 쪽에 영향 없음.
- LMS는 `lms` database만 사용. **LMS 스키마에 문제은행(qbank) 표는 없다** — 문제 DB는 전적으로 도훈 레포/`qbank` database 소유.
- 큰 파일(이미지·PDF)은 DB에 넣지 않고 오브젝트 스토리지에, DB에는 경로만.

## 2. 현재 상태

**표는 [`infra/DEPLOY.md`](../../infra/DEPLOY.md#6-celery-워커--beat--redis) 에 있다.** 요약만 적는다(2026-08-20):

- `edujc-lms` web · worker · beat 가 **전부 돌고 있다**. Celery 는 2026-08-12 부터 가동
- `edujc-pg` postgres-flex 단일 노드 256MB + 볼륨 3GB. database `lms`·`qbank` 공용
- Tigris 버킷 2개, Upstash Redis `edujc-redis`(Fixed 250MB) **모두 생성됨**
- 프런트는 Vercel, 도메인은 `lms.hjcedu.com`·`api.hjcedu.com`·`hjcedu.com` 셋 다 연결됨
- `edujc-qbank` 는 배포됨(도훈 레포). 같은 org·같은 PG 볼륨을 쓴다
- `jc-search` 라는 **이 레포와 무관한 앱**이 같은 org 에서 상시 가동 중이라 청구서에 같이 실린다

> **PG 단일 노드 256MB 는 그대로다.** 오픈 전 HA·스케일업 검토는 아직 안 했다.
> 볼륨 3GB 를 qbank 와 나눠 쓰는 것도 그대로다 — 저쪽이 부으면 우리가 같이 좁아진다.

## 5. 비용

**표는 [`infra/DEPLOY.md`](../../infra/DEPLOY.md) 에 있다.** 여기 적지 않는다 — 두 군데 있으면 한쪽이 낡는다.

2026-08-20 실측 요약: fly 전체 **~$34.76/월**(이 레포 몫 $20.76 · qbank+jc-search $13.85),
Google Workspace 별도 $16.80. **전부 정액이고 손님 0명일 때도 나간다.**
오픈 때 켜지는 종량 항목은 `docs/2026-08-04-영상호스팅-비용재계산.md`(Mux) 와
`docs/2026-08-05-알림발송-비용과-업체선정.md`(알리고) 에 있다.

## 6. 계정·권한 메모

- Fly 로그인: seanpark98@gmail.com (인프라 담당). 팀원 초대: `fly orgs invite <email> --org edujc`.
- 나중에 담당자가 org에서 빠질 때: admin 1명 + 결제카드 주체 남기고 `fly auth logout`. CI/머신에는 **deploy 토큰**만(`fly tokens create deploy -a edujc-lms`). 리소스는 org 소유라 유지됨.
- personal org(`beonto`)는 사용 안 함(삭제 불가, 방치). 리소스 전부 EDUJC로 이전 완료.

## 7. 남은 TODO

2026-07-21 에 적어 둔 여섯은 **전부 끝났다** — Vercel 연결 · `FLY_API_TOKEN` 자동배포 ·
qbank 첫 배포 · Tigris 버킷 · Redis+worker · 커스텀 도메인과 `ALLOWED_HOSTS`.

인프라에 남은 것은 둘이다.

1. **PG 를 오픈 전에 키운다.** 단일 노드 256MB · 볼륨 3GB 이고 qbank 와 나눠 쓴다.
2. **`jc-search` 가 필요한지 정한다.** 이 레포 것이 아닌데 shared-cpu-2x 로 상시 가동이라
   fly 청구서에서 제일 큰 머신이다.

나머지 할 일은 인프라가 아니라 제품이라 `.claude/to-do.md` 에 있다.
