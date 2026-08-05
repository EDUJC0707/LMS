# 개발 편의 타깃 모음. (Windows 는 `make` 미설치일 수 있으니 README 의 명령을 직접 실행해도 됨)
.PHONY: up down dev-backend dev-frontend migrate makemigrations test worker db-proxy deploy

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

# --- Fly 원격 DB 접속용 터널 (DBeaver 등) ---
# edujc-pg 는 private IPv6 만 있어 이 프록시 없이는 외부에서 못 붙는다.
# 포트 15432 인 이유: 5432 는 `make up` 의 로컬 postgres 가 점유한다.
#   (5432 로 붙으면 fly DB 가 아니라 로컬 도커 DB 에 조용히 연결됨 — infra/DEPLOY.md 7장)
# 이 창은 켜둔 채로 유지할 것. 닫으면 터널이 끊긴다.
db-proxy:
	PATH="$$HOME/.fly/bin:$$PATH" fly proxy 15432:5432 -a edujc-pg

# --- 손배포 (실서비스를 갈아치운다) ---
# 평소 배포는 main push 로 CI 가 한다. 이건 CI 를 못 기다릴 때만.
# GIT_SHA 를 반드시 함께 넘긴다 — 빠지면 배포는 성공하는데 Sentry 에서
# "어느 배포냐"를 잃는다(infra/Dockerfile 3번 절). 손으로 치면 잊는다.
deploy:
	PATH="$$HOME/.fly/bin:$$PATH" fly deploy -c infra/fly.toml -a edujc-lms \
	  --build-arg GIT_SHA="$$(git rev-parse HEAD)"
