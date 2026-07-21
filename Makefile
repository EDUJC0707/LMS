# 개발 편의 타깃 모음. (Windows 는 `make` 미설치일 수 있으니 README 의 명령을 직접 실행해도 됨)
.PHONY: up down dev-backend dev-frontend migrate makemigrations test worker

# --- 로컬 인프라 (PostgreSQL + Redis) ---
up:
	docker compose up -d

down:
	docker compose down

# --- 개발 서버 ---
dev-backend:
	cd backend && uv run python manage.py runserver

dev-frontend:
	cd frontend && npm run dev

# --- DB 마이그레이션 ---
migrate:
	cd backend && uv run python manage.py migrate

makemigrations:
	cd backend && uv run python manage.py makemigrations

# --- 테스트 ---
test:
	cd backend && uv run pytest

# --- Celery 워커 ---
worker:
	cd backend && uv run celery -A config worker -l info
