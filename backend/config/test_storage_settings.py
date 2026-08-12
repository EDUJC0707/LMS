"""오브젝트 스토리지 설정 (config/settings/base.py).

워크북 사진(PRD 3.1.7)이 실제로 어디에 저장되는지를 정하는 자리다. 2026-08-11 까지
**운영에서 미디어가 통째로 안 서빙됐다** — 버킷이 없어 로컬 파일시스템으로 떨어졌는데
`config/urls.py` 는 `DEBUG` 에서만 `MEDIA_ROOT` 를 열기 때문이다. 올린 사진이 컨테이너
임시 디스크에 앉아 아무도 못 받고, 재배포 때 사라졌다. 로컬은 `DEBUG=True` 라 멀쩡해
보여서 **운영에서만 조용히 실패하는** 종류였다.

확인 축:
- **fly 가 주는 이름으로 켜진다** — `fly storage create` 는 AWS CLI 관례
  (`BUCKET_NAME`·`AWS_ENDPOINT_URL_S3`·`AWS_REGION`)로 꽂는데 django-storages 가 읽는
  이름은 다르다. 여기가 어긋나면 시크릿이 다 있는데도 로컬 저장으로 떨어진다.
- **옛 이름도 계속 받는다** — 로컬 `.env` 가 django-storages 이름을 쓰고 있을 수 있다.
- **버킷이 없으면 S3 로 켜지지 않는다** — 켜지면 자격증명 없이 저장을 시도해 터진다.
"""
from django.test import SimpleTestCase

from config.settings import base


def _reread(**environ):
    """설정 모듈을 주어진 환경변수로 다시 읽는다."""
    import importlib
    import os
    from unittest import mock

    clear = {k: "" for k in (
        "BUCKET_NAME", "AWS_STORAGE_BUCKET_NAME",
        "AWS_ENDPOINT_URL_S3", "AWS_S3_ENDPOINT_URL",
        "AWS_REGION", "AWS_S3_REGION_NAME",
    )}
    # `reload` 는 이전 로드가 남긴 이름을 지우지 않는다 — `STORAGES` 는 버킷이 있을
    # 때만 대입되므로, 지우지 않으면 "버킷 없음" 경우에 앞 테스트의 값이 그대로 남아
    # 통과해 버린다. 운영은 모듈을 한 번만 읽으니 실제 동작과는 무관하다.
    if hasattr(base, "STORAGES"):
        del base.STORAGES
    with mock.patch.dict(os.environ, {**clear, **environ}):
        return importlib.reload(base)


class StorageSettingsTests(SimpleTestCase):
    def tearDown(self):
        _reread()  # 다른 테스트가 오염된 모듈을 보지 않게 되돌린다

    def test_fly_names_turn_on_object_storage(self):
        """`fly storage create` 가 꽂아 주는 이름 그대로 켜져야 한다."""
        s = _reread(
            BUCKET_NAME="edujc-lms-media",
            AWS_ENDPOINT_URL_S3="https://fly.storage.tigris.dev",
            AWS_REGION="auto",
        )
        self.assertEqual(s.AWS_STORAGE_BUCKET_NAME, "edujc-lms-media")
        self.assertEqual(s.AWS_S3_ENDPOINT_URL, "https://fly.storage.tigris.dev")
        self.assertEqual(s.STORAGES["default"]["BACKEND"], "storages.backends.s3.S3Storage")

    def test_django_storages_names_still_work(self):
        """로컬 `.env` 가 옛 이름을 쓰고 있어도 깨지지 않는다."""
        s = _reread(
            AWS_STORAGE_BUCKET_NAME="legacy-bucket",
            AWS_S3_ENDPOINT_URL="https://example.invalid",
            AWS_S3_REGION_NAME="apac",
        )
        self.assertEqual(s.AWS_STORAGE_BUCKET_NAME, "legacy-bucket")
        self.assertEqual(s.AWS_S3_ENDPOINT_URL, "https://example.invalid")
        self.assertEqual(s.AWS_S3_REGION_NAME, "apac")

    def test_fly_name_wins_when_both_are_set(self):
        """두 벌이 다 있으면 운영이 실제로 쓰는 쪽(fly)을 따른다."""
        s = _reread(BUCKET_NAME="fly-bucket", AWS_STORAGE_BUCKET_NAME="legacy-bucket")
        self.assertEqual(s.AWS_STORAGE_BUCKET_NAME, "fly-bucket")

    def test_no_bucket_means_no_s3(self):
        """버킷이 없는데 S3 로 켜지면 자격증명 없이 저장을 시도해 터진다."""
        s = _reread()
        self.assertEqual(s.AWS_STORAGE_BUCKET_NAME, "")
        self.assertFalse(hasattr(s, "STORAGES") and s.STORAGES.get("default", {}).get(
            "BACKEND") == "storages.backends.s3.S3Storage")

    def test_region_falls_back_to_auto(self):
        """Tigris 는 지역을 `auto` 로 받는다 — 비면 빈 문자열이 아니라 auto 여야 한다."""
        s = _reread(BUCKET_NAME="edujc-lms-media")
        self.assertEqual(s.AWS_S3_REGION_NAME, "auto")
