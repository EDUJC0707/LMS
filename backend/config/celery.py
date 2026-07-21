"""Celery 앱. 이름은 `config` — 실행: `celery -A config worker -l info`."""
import os

from celery import Celery

# 워커 단독 실행 시 기본 설정 모듈(운영은 env 로 prod 주입).
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("config")

# settings 의 CELERY_ 접두 항목을 설정으로 로드.
app.config_from_object("django.conf:settings", namespace="CELERY")

# 각 앱의 tasks.py 자동 탐색.
app.autodiscover_tasks()
