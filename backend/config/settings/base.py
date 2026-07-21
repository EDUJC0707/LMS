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

# --- CORS ---------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:5173"])
CORS_ALLOW_CREDENTIALS = True

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
