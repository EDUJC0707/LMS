# 한종철 LMS

한국 학원 LMS 모노레포. React SPA(프런트) + Django/DRF/Celery(백엔드) 구조의 개발 스켈레톤.

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
cp .env.example .env           # VITE_API_URL 확인
npm install
npm run dev                    # http://localhost:5173
```

## 참고

- 도메인/데이터 모델 설계: `docs/db/lms-db-design-2026-07-15.md` (8도메인).
  현재 각 앱의 `models.py`는 **도메인 주석만** 있는 placeholder다. DB 설계 확정 후 모델을 채운다.
- 배포 설정: `infra/fly.toml`, `infra/Dockerfile`.
