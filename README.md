# 한종철 LMS

수능 강사 한종철의 LMS. React SPA(프런트) + Django/DRF/Celery(백엔드) 모노레포.

**돌고 있다.** fly.io(도쿄)에 web·worker·beat 가 상시 가동 중이고 도메인 셋이 붙어 있다
(`lms.hjcedu.com` · `api.hjcedu.com` · `hjcedu.com`). 아직 **오픈 전**이라 실제 학생은 없고,
문자·알림톡은 키가 없어 한 통도 안 나간다.

- **제품이 어떻게 흘러가는가**는 `docs/FLOW.md` 가 기준이다. 새 화면·모델을 설계하기 전에 거기부터 본다
- **남은 일**은 `.claude/to-do.md`, **해 온 일**은 `.claude/progress.md`

## 스택

| 영역 | 기술 |
|---|---|
| 프런트엔드 | React 18 + Vite + TypeScript, React Router, TanStack Query, axios |
| 백엔드 | Django 5 + DRF + Celery |
| 데이터 | PostgreSQL 16, Redis 7 |
| 스토리지 | Tigris/S3 (django-storages) |
| 배포 | Fly.io (도쿄 리전 `nrt`) |
| 파이썬 의존성 | uv (`backend/pyproject.toml`) |

## 저장소 구조

```
.
├── docker-compose.yml     # 로컬 인프라: PostgreSQL + Redis
├── Makefile               # up/down/dev-backend/dev-frontend/migrate/test/worker
├── backend/               # Django 프로젝트
│   ├── pyproject.toml     # uv 기반 의존성
│   ├── manage.py
│   ├── config/            # settings(base/dev/prod)·urls·celery·wsgi·asgi
│   └── apps/              # 8개 도메인 앱(accounts·grades·curriculum·videos·
│                          #   payments·clinic·boards·notifications)
├── frontend/              # Vite + React + TS SPA
│   └── src/               # main·App·api/client·routes(학생/학부모/관리자)
└── infra/                 # Dockerfile(백엔드) + fly.toml
```

## 로컬 개발 시작

사전 준비: Docker Desktop, [uv](https://docs.astral.sh/uv/), Node 20+.

### 1) 인프라(PostgreSQL + Redis) 기동

```bash
docker compose up -d          # 또는: make up
```

### 2) 백엔드 (Django)

```bash
cd backend
uv sync                        # .venv 생성 + 의존성 설치
# .env 없이도 기동된다 — settings 기본값이 docker-compose 자격증명과 일치.
# 값을 바꿀 때만 backend/.env 를 만들어 DATABASE_URL 등을 재정의한다.
uv run python manage.py migrate   # 모델(마이그레이션)이 있는 상태에서 실행
uv run python manage.py runserver
# Celery 워커는 별도 터미널: uv run celery -A config worker -l info  (또는 make worker)
```

- 헬스체크: http://localhost:8000/healthz
- API 루트: http://localhost:8000/api/
- 관리자: http://localhost:8000/admin/

### 3) 프런트엔드 (Vite)

```bash
cd frontend
npm install
npm run dev                    # http://localhost:5173

# 백엔드를 기본 포트가 아닌 데 띄웠으면
VITE_API_TARGET=http://127.0.0.1:8010 npm run dev -- --port 5180 --strictPort
```

## 참고

- 도메인/데이터 모델 설계: `docs/db/lms-db-design-2026-07-15.md` (8도메인).
  모델은 **다 들어가 있다** — 8개 앱 합쳐 약 3,000줄. 설계 문서와 어긋나는 곳은 코드가 맞다.
- 배포·운영 현황(머신·시크릿·비용): `infra/DEPLOY.md` 한 곳만 본다.
- 배포 설정: `infra/fly.toml`, `infra/Dockerfile`.
