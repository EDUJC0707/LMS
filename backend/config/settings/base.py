"""공통 설정(base). dev.py / prod.py 가 상속한다.

환경변수는 django-environ 으로 읽는다(.env 또는 OS 환경).
민감정보·환경별 값(DB/Redis/스토리지/Sentry)은 코드에 넣지 않고 env 로 주입한다.
"""
from pathlib import Path

import environ

# backend/ 디렉터리. 이 파일 기준 3단계 위: base.py -> settings -> config -> backend
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:5173"]),
)

# backend/.env 가 있으면 로드(없으면 OS 환경변수만 사용).
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    env.read_env(str(_env_file))

# --- 코어 ---------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-insecure-change-me")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# --- 앱 -----------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
THIRD_PARTY_APPS = [
    "rest_framework",
    "corsheaders",
]
# 로컬 앱 — 등록명은 각 앱 AppConfig.name(`apps.<name>`)과 반드시 일치시킨다.
LOCAL_APPS = [
    "apps.accounts",       # 계정·학생·학부모·RBAC
    "apps.grades",         # 성적·OMR·과제·약점체크
    "apps.curriculum",     # 강좌·주차·캘린더
    "apps.videos",         # 복습영상·동보
    "apps.payments",       # 교재결제·수강료
    "apps.clinic",         # 클리닉
    "apps.boards",         # 게시판·문의·상담
    "apps.notifications",  # 알림
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# 커스텀 유저 모델 (accounts.User, 세션 인증 — docs/db 도메인 1 · PRD §5)
AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # CORS 는 가능한 상단에
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- 데이터베이스 (PostgreSQL, DATABASE_URL) -----------------------------
DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://lms:lms@localhost:5432/lms",
    ),
}

# --- 캐시 / Celery (Redis) ----------------------------------------------
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TIMEZONE = "Asia/Seoul"
CELERY_TASK_TRACK_STARTED = True
# 주기 작업 — **한 딕셔너리에 모은다.** 트랙마다 각자 `CELERY_BEAT_SCHEDULE = {...}`
# 를 새로 쓰면 git 은 충돌 없이 합쳐 놓고 **나중 대입이 앞의 것을 통째로 덮는다**
# (2026-08-05 병합에서 실제로 retry-failed-notifications 가 조용히 사라졌다).
# 항목을 추가할 때는 새 대입이 아니라 이 딕셔너리에 키를 더한다.
# beat 프로세스는 아직 안 뜬다 — 켜는 시점은 infra/DEPLOY.md 6장.
CELERY_BEAT_SCHEDULE = {
    # 실패·정체 알림 재발송(apps.notifications.tasks)
    "retry-failed-notifications": {
        "task": "notifications.retry_failed_notifications",
        "schedule": 60 * 60,
    },
    # 클리닉 감독 자료 수집. 멱등이라 헛돌아도 되고 두 번 돌아도 된다.
    # 20분 주기인 이유: 회의가 끝나고 자료가 생기기까지 몇 분 걸리고 수집은
    # 거기에 30분을 더 기다린다. 주기가 그보다 성기면 대기가 주기만큼 통째로
    # 늘어난다. 한 번 걸러도 다음 차례가 메운다.
    "clinic-supervision": {
        "task": "apps.clinic.tasks.collect_clinic_supervision",
        "schedule": 20 * 60,
    },
}

# --- 알림 채널 (PRD 6-8 채널 추상화 — apps/notifications/channels.py) --------
# 채널 값 → 어댑터 dotted path. **기본값은 비어 있다(닫힘)**: 아무것도 안 물린
# 환경에서 발송은 실패하고 사유가 남는다. Fake 를 기본으로 두면 운영에서 알림이
# 조용히 증발하고 발송내역에는 성공만 쌓인다. dev/prod 가 각자 물린다.
NOTIFICATION_CHANNEL_BACKENDS = {}
# 알림 유형 → 승인된 카카오 알림톡 템플릿 코드. **비어 있다 — 8-17 대기**
# (발송 시점 목록이 확정돼야 템플릿 승인이 시작된다). 승인분이 나오면 여기에
# `"성적": "TPL_…"` 를 추가하는 것이 연동의 전부다.
NOTIFICATION_KAKAO_TEMPLATE_CODES = {}
NOTIFICATION_MAX_RETRIES = env.int("NOTIFICATION_MAX_RETRIES", default=5)
# 재발송 배치 선정창 — 새 행(재시도 중)과 지난 행(보내도 의미 없음)을 뺀다.
NOTIFICATION_RETRY_GRACE_MINUTES = env.int("NOTIFICATION_RETRY_GRACE_MINUTES", default=30)
NOTIFICATION_RETRY_MAX_AGE_HOURS = env.int("NOTIFICATION_RETRY_MAX_AGE_HOURS", default=24)
NOTIFICATION_RETRY_BATCH_SIZE = env.int("NOTIFICATION_RETRY_BATCH_SIZE", default=200)

# 알리고 자격증명 — **아직 없다**(대표 전달 대기, docs/decisions.md §3-1).
# 업체 이름이 나오는 것은 이 층까지고 DB 스키마에는 새지 않는다
# (apps/notifications/models.py 채널 추상화 계약).
ALIGO_API_KEY = env("ALIGO_API_KEY", default="")
ALIGO_USER_ID = env("ALIGO_USER_ID", default="")
ALIGO_SENDER_PHONE = env("ALIGO_SENDER_PHONE", default="")  # 사전 등록된 발신번호
ALIGO_SENDER_KEY = env("ALIGO_SENDER_KEY", default="")  # 카카오 발신프로필키(senderkey)

# beat 주기 작업. **워커가 아직 안 떠 있어서 지금은 아무도 안 부른다** —
# 켜는 절차는 infra/DEPLOY.md 6장(Redis 프로비저닝 → 시크릿 → 워커 프로세스).
# 여기 선언해 두는 이유는 주기가 코드에 남아 버전 관리되게 하기 위해서다.

# --- 비밀번호 검증 -------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- 국제화 -------------------------------------------------------------
LANGUAGE_CODE = "ko-kr"
TIME_ZONE = "Asia/Seoul"
USE_I18N = True
USE_TZ = True

# --- 정적/미디어 --------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- DRF ----------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
}

# --- CORS / CSRF --------------------------------------------------------
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:5173"])
CORS_ALLOW_CREDENTIALS = True
# Vite(5173) → Django 세션 인증 쓰기 요청이 CSRF 403으로 막히는 것 실측 → 신뢰 오리진 등록.
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=["http://localhost:5173"])

# --- 관측(Sentry) -------------------------------------------------------
# 수집 확인용 /sentry-debug 의 열쇠. 비어 있으면 그 경로는 404 다(기본값 = 닫힘).
# DSN 자체는 prod.py 에서만 읽는다 — 로컬·테스트에서 Sentry 는 켜지지 않는다.
SENTRY_DEBUG_TOKEN = env("SENTRY_DEBUG_TOKEN", default="")

# ── Mux 서명 재생 (apps.videos.mux) ──────────────────────────────────
# Playback ID 정책이 `signed` 면 서버가 RS256 JWT 를 서명해야 재생된다.
# 비어 있으면 서명하지 않는다 — 로컬·시드는 데모/공개 영상으로 돌기 때문
# (없다고 죽이면 키 없는 개발 환경에서 재생 화면 자체가 못 뜬다).
# 개인키는 Mux 가 base64 로 주며 **시크릿이다** — .env 로만 넣고 커밋 금지.
MUX_SIGNING_KEY_ID = env("MUX_SIGNING_KEY_ID", default="")
MUX_SIGNING_PRIVATE_KEY = env("MUX_SIGNING_PRIVATE_KEY", default="")

# Mux REST API 자격증명 — **서명 키와 다른 것이다.**
# 서명 키(위)는 재생 토큰용이고, 이건 업로드·자산 관리용이다
# (대시보드 Settings → Access Tokens). 업로드 커맨드만 쓴다.
MUX_TOKEN_ID = env("MUX_TOKEN_ID", default="")
MUX_TOKEN_SECRET = env("MUX_TOKEN_SECRET", default="")

# 재생 제한 규칙 id — 서명 토큰에 실어 보내면 Mux 가 Referer·User-Agent 를 함께 본다.
# 비어 있으면 claim 을 넣지 않는다(제한 없음). `manage.py mux_restriction` 으로 만든다.
MUX_PLAYBACK_RESTRICTION_ID = env("MUX_PLAYBACK_RESTRICTION_ID", default="")

# 시드 영상이 대신 재생할 실제 자산의 Playback ID(개발 편의).
# 시드는 `seed-*` 라는 가짜 참조를 넣는데 그건 재생될 수 없다. 이 값이 있으면
# 서버가 **대체와 서명을 같은 자리에서** 처리한다 — 프런트가 따로 갈아치우면
# "서명은 seed-1-1 앞으로, 재생은 다른 자산" 이 되어 Mux 가 거부한다(2026-08-04 실측).
# 비어 있으면 대체하지 않는다(운영에는 시드 데이터가 없다).
MUX_DEMO_PLAYBACK_ID = env("MUX_DEMO_PLAYBACK_ID", default="")

# --- 오브젝트 스토리지 (Tigris/S3, django-storages) ----------------------
# 버킷명이 있으면 S3(Tigris) 사용, 없으면 로컬 파일시스템(MEDIA_ROOT).
AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default="")
AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="")
AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default="")  # Tigris 엔드포인트
AWS_S3_REGION_NAME = env("AWS_S3_REGION_NAME", default="auto")

if AWS_STORAGE_BUCKET_NAME:
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }

# --- 화상(클리닉) — key_considerations §4 추상화 경계 --------------------
# 업체 교체는 이 경로 한 줄이다(apps.clinic.conferencing 계약).
CLINIC_CONFERENCE_BACKEND = env(
    "CLINIC_CONFERENCE_BACKEND", default="apps.clinic.google_meet.GoogleMeetAdapter"
)
# 구글 미트는 **사용자 인증만** 받는다(서비스 계정은 워크스페이스 도메인 위임
# 한정) — 계정 1개로 한 번 동의받은 갱신 토큰을 서버가 들고 쓴다.
# 발급: `manage.py meet_authorize`. 셋 중 하나라도 비면 스페이스 생성은
# 막히고 배정은 관리자 수동 입력으로만 성립한다(닫힘이 안전 기본값 — §5).
GOOGLE_MEET_CLIENT_ID = env("GOOGLE_MEET_CLIENT_ID", default="")
GOOGLE_MEET_CLIENT_SECRET = env("GOOGLE_MEET_CLIENT_SECRET", default="")
GOOGLE_MEET_REFRESH_TOKEN = env("GOOGLE_MEET_REFRESH_TOKEN", default="")
