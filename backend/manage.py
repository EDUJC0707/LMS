#!/usr/bin/env python
"""Django 관리 명령 진입점."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django 를 임포트할 수 없습니다. 가상환경(.venv) 활성화와 `uv sync` 를 확인하세요."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
