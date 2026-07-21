# EduJC 인프라 구조 (living doc)

> 최종 갱신: 2026-07-21 — empty 배포 완료 시점 기준.
> 상세 셋업 명령·순서는 [`infra/DEPLOY.md`](../../infra/DEPLOY.md) 참조. 이 문서는 **"지금 뭐가 어디에 떠 있는가"**의 단일 기준.

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

## 2. 현재 상태 (2026-07-21)

| 리소스 | 값 | 상태 |
|---|---|---|
| Fly org | `EDUJC` (slug `edujc`) · 카드 등록됨 · Pay-As-You-Go | ✅ |
| `edujc-lms` | https://edujc-lms.fly.dev — web 1대(shared-cpu-1x 512MB), `/healthz` 200 | ✅ 배포 |
| — worker | Celery 프로세스 그룹 **0대로 꺼둠**(설계는 유지) | ⏸ |
| `edujc-pg` | postgres-flex, nrt, shared-cpu-1x 256MB, 볼륨 3GB, 단일 노드 | ✅ |
| — database `lms` | user `lms`, `DATABASE_URL`은 edujc-lms 시크릿에 자동 주입 | ✅ 마이그레이션 적용됨 |
| — database `qbank` | user `qbank`, `DATABASE_URL`은 edujc-qbank 시크릿에 주입 | ✅ (빈 DB) |
| `edujc-qbank` | 앱 생성만 됨. 배포는 도훈 레포에서 (`Dockerfile`+`fly.toml` 추가 후 `fly deploy`) | 🔲 |
| Tigris 스토리지 | 미생성 — 파일 업로드 기능 붙일 때 `fly storage create` (앱별 버킷) | 🔲 |
| Upstash Redis | 미생성 — 첫 백그라운드 작업(알림톡 일괄발송·OMR 채점) 때 | 🔲 |
| 프런트 (LMS) | `frontend/`(Vite+React) → **Vercel** 배포 예정. 미연결 | 🔲 |
| GitHub Actions | `.github/workflows/fly-deploy.yml` 준비됨. repo secret `FLY_API_TOKEN` 등록 시 push=자동배포 | 🔲 |

### edujc-lms 시크릿 (fly secrets)
`DJANGO_SECRET_KEY` · `DATABASE_URL`(attach 자동) · `DJANGO_DEBUG=False` · `ALLOWED_HOSTS=*`(임시 — §4) · `CSRF_TRUSTED_ORIGINS` · `DJANGO_SECURE_SSL_REDIRECT=False`(임시)

## 3. 배포 방법

```bash
# LMS 백엔드 (이 레포 루트에서 — 로컬 소스 빌드, GitHub 안 거침)
fly deploy -c infra/fly.toml -a edujc-lms --remote-only

# worker 켜기/끄기 (Celery 필요해질 때)
fly scale count worker=1 -a edujc-lms   # + REDIS_URL 시크릿 필요
fly scale count worker=0 -a edujc-lms
```

- Docker 로컬 불필요(원격 빌더). 이미지: `infra/Dockerfile` (uv, `.venv/bin/*` 직접 실행 — 부팅 지연 방지).
- 배포마다 release command로 `migrate --noinput` 자동 실행.
- qbank: 도훈 레포에서 동일 패턴으로. 앱·DB는 이미 있으므로 `fly deploy -a edujc-qbank`만 하면 됨.

## 4. 임시 설정 (되돌릴 것)

| 항목 | 현재 | 조일 시점 |
|---|---|---|
| `ALLOWED_HOSTS=*` | health check(Host: 127.0.0.1)가 400 나는 문제 회피용 | 실제 도메인 확정 시 도메인 목록으로 (또는 check에 Host 헤더 지정) |
| `DJANGO_SECURE_SSL_REDIRECT=False` | fly-proxy가 이미 force_https | 그대로 둬도 무방 (프록시가 처리) |
| PG 단일 노드·256MB | 개발용 최소 | 오픈 전 HA(2노드)·스케일업 검토 |

## 5. 비용 (대략)

- 현재(개발): web 1대 + PG 1대 ≈ **월 $5~10**. Tigris/Redis 미사용 = $0.
- 오픈 후(수백 명): web 상시 1~2대 + worker + PG + 스토리지 ≈ **월 $15~40** 수준.
- Redis(Upstash) 무료 티어로 시작 가능. Tigris는 저장 $0.02/GB, egress 무료.

## 6. 계정·권한 메모

- Fly 로그인: seanpark98@gmail.com (인프라 담당). 팀원 초대: `fly orgs invite <email> --org edujc`.
- 나중에 담당자가 org에서 빠질 때: admin 1명 + 결제카드 주체 남기고 `fly auth logout`. CI/머신에는 **deploy 토큰**만(`fly tokens create deploy -a edujc-lms`). 리소스는 org 소유라 유지됨.
- personal org(`beonto`)는 사용 안 함(삭제 불가, 방치). 리소스 전부 EDUJC로 이전 완료.

## 7. 남은 TODO

1. 프런트 Vercel 프로젝트 생성 → `frontend/` 연결, API 도메인/CORS(`CORS_ALLOWED_ORIGINS`) 설정
2. GitHub repo에 `FLY_API_TOKEN` secret → push 자동배포 활성화 (repo admin 권한 필요)
3. qbank 레포에 Dockerfile/fly.toml → 첫 배포 (도훈)
4. 파일 업로드 시작 시: `fly storage create` (lms/qbank 각자 버킷) + django-storages 연결(설정은 이미 env 기반으로 준비됨)
5. 알림톡/OMR 등 첫 비동기 기능 시: Upstash Redis + worker=1
6. 커스텀 도메인 + `ALLOWED_HOSTS` 조이기
