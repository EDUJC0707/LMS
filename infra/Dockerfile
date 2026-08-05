# 백엔드 이미지 — Django + Gunicorn. 의존성은 uv 로 설치.
# 빌드 컨텍스트 = 저장소 루트(‘COPY backend/’ 접근 위해). fly.toml 이 이 경로를 dockerfile 로 지정.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    DJANGO_SETTINGS_MODULE=config.settings.prod

# uv 정적 바이너리(astral 공식 이미지에서 복사)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# supercronic — 주기 작업 실행기(Fly 공식 블루프린트 권장).
# **왜 일반 cron 이 아닌가**: 컨테이너에서 cron 은 PID 1 로 안 맞고, 로그를 syslog 로
# 보내 `fly logs` 에 안 잡히며, 환경변수를 물려받지 못한다. supercronic 은 표준
# crontab 문법을 쓰면서 로그를 표준출력으로 내보내 셋 다 해결한다.
# 버전·체크섬을 박아 둔다 — latest 를 쓰면 빌드마다 다른 바이너리가 들어온다.
ARG SUPERCRONIC_VERSION=v0.2.33
ARG SUPERCRONIC_SHA1SUM=71b0d58cc53f6bd72cf2f293e09e294b79c666d8
ADD https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64 /usr/local/bin/supercronic
RUN echo "${SUPERCRONIC_SHA1SUM}  /usr/local/bin/supercronic" | sha1sum -c - \
    && chmod +x /usr/local/bin/supercronic

WORKDIR /app

# 1) 의존성 레이어(캐시 최적화) — 소스보다 먼저 매니페스트/락만 복사.
#    uv.lock 을 커밋하면 재현 가능 빌드가 되며 CI 에서는 `--frozen` 권장.
COPY backend/pyproject.toml backend/uv.lock* /app/
RUN uv sync --no-dev

# 2) 앱 소스
COPY backend/ /app/

# 2-1) 주기 작업표. `cron` 프로세스 그룹이 supercronic 으로 이 파일을 돈다.
COPY infra/crontab /app/crontab

# 3) 이 이미지가 어느 커밋인지 — Sentry 의 release 태그.
#    **여기 위치가 중요하다**: ARG/ENV 는 뒤따르는 레이어의 캐시를 무효화하므로,
#    커밋마다 값이 바뀌는 이 줄은 의존성 설치(uv sync) 뒤에 와야 한다.
#    이미지에는 `.git` 이 없어 SDK 가 스스로 추론할 방법이 없다 — 빌드가 안 넣어 주면
#    release 없이 뜨고, "어제 500 났는데 어느 배포냐"에 답할 수 없다.
#    넘기는 쪽: CI 는 `.github/workflows/fly-deploy.yml`, 손배포는 `make deploy`.
ARG GIT_SHA=""
ENV SENTRY_RELEASE=$GIT_SHA

EXPOSE 8000

# 웹 프로세스 기본 커맨드(워커는 fly.toml [processes] 에서 커맨드만 교체).
# .venv 바이너리 직접 실행 — uv run 의 부팅 시 재동기화/다운로드 지연 제거.
CMD [".venv/bin/gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
