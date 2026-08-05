"""수집 태스크 — beat 가 주기적으로 부르는 자리.

태스크 본문은 얇다(서비스 한 줄 호출). 그래서 여기서 잡는 것은 로직이 아니라
**배선**이다: 이름이 안 바뀌었는가, beat 일정에 실제로 등록돼 있는가, 예외가
새어 나가 워커를 죽이지 않는가.
"""
from unittest import mock

from django.test import SimpleTestCase, override_settings

from .conferencing import PermanentConferenceError
from .tasks import COLLECT_TASK_NAME, collect_clinic_supervision


class CollectTaskTests(SimpleTestCase):
    def test_delegates_to_the_service(self):
        counts = {"collected": 2, "waiting": 0, "failed": 0}
        with mock.patch("apps.clinic.tasks.supervision.collect") as collect:
            collect.return_value = counts
            self.assertEqual(collect_clinic_supervision(), counts)
        collect.assert_called_once_with()

    def test_a_broken_provider_does_not_kill_the_worker(self):
        # 어댑터 자체를 못 만드는 경우(설정 누락·자격증명 만료)는 다음 주기에
        # 다시 걸린다. 예외를 그대로 올리면 워커 로그가 그걸로 덮인다.
        with mock.patch("apps.clinic.tasks.supervision.collect") as collect:
            collect.side_effect = PermanentConferenceError("자격증명이 없습니다")
            result = collect_clinic_supervision()
        self.assertIn("자격증명", result["error"])


class BeatScheduleTests(SimpleTestCase):
    def test_task_is_on_the_beat_schedule(self):
        # 태스크만 쓰고 일정에 안 걸면 아무도 안 부른다 — 조용히 안 도는 종류다
        from django.conf import settings

        entries = settings.CELERY_BEAT_SCHEDULE.values()
        self.assertIn(COLLECT_TASK_NAME, [entry["task"] for entry in entries])

    @override_settings()
    def test_runs_at_least_twice_an_hour(self):
        # 회의가 끝나고 자료가 생기기까지 몇 분, 수집은 30분을 기다린다.
        # 주기가 그보다 성기면 대기 시간이 주기만큼 통째로 늘어난다.
        from django.conf import settings

        entry = next(
            e for e in settings.CELERY_BEAT_SCHEDULE.values() if e["task"] == COLLECT_TASK_NAME
        )
        self.assertLessEqual(entry["schedule"], 30 * 60)
