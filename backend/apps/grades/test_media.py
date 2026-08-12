"""버킷 안 자리 계약 (apps/grades/media.py).

경로가 네 파일에 f-string 으로 흩어져 있었고, 시드 정리가 지울 접두사를 손으로
따라 적고 있었다 — 한쪽만 고치면 안 지워지는 쓰레기가 남는다. 여기서 고정한다.
"""
from django.test import SimpleTestCase

from . import media


class LayoutTests(SimpleTestCase):
    def test_omr_pieces_live_under_one_branch(self):
        """스캔과 업로드 원본이 형제로 흩어져 있으면 한 시험 것을 한 번에 못 짚는다."""
        scan = media.omr_scan(7, "abc123")
        batch = media.omr_batch(7, "deadbeef")

        self.assertTrue(scan.startswith("omr/"))
        self.assertTrue(batch.startswith("omr/"))
        self.assertNotEqual(scan.split("/")[1], batch.split("/")[1])

    def test_a_scan_path_is_its_content_address(self):
        """같은 지면이면 같은 자리 — 재업로드가 장을 늘리지 않는 근거다."""
        self.assertEqual(media.omr_scan(3, "d1"), media.omr_scan(3, "d1"))
        self.assertNotEqual(media.omr_scan(3, "d1"), media.omr_scan(4, "d1"))

    def test_workbook_pages_split_by_month(self):
        """한 폴더가 무한정 커지지 않게. 한 자리 월도 0 을 채운다."""
        self.assertEqual(
            media.workbook_page(2026, 8, "tok", "jpg"), "workbook/pages/2026/08/tok.jpg"
        )


class DemoIsolationTests(SimpleTestCase):
    """시드는 최상위 `demo/` 아래에만 쓴다 — 실물과 절대 안 겹친다."""

    def test_demo_paths_start_with_the_demo_prefix(self):
        self.assertTrue(media.demo("omr", 3, "x.png").startswith(f"{media.DEMO}/"))
        self.assertTrue(media.demo("workbook", "y.png").startswith(f"{media.DEMO}/"))

    def test_real_paths_never_fall_under_it(self):
        """`demo/` 하나만 지우면 되는 근거. 예전엔 `omr/demo/` 라 실물과 한 가지였다."""
        real = (
            media.omr_scan(1, "d"),
            media.omr_batch(1, "t"),
            media.workbook_page(2026, 8, "t", "jpg"),
        )

        for path in real:
            self.assertFalse(path.startswith(f"{media.DEMO}/"), path)

    def test_an_exam_named_demo_cannot_collide(self):
        """시험 id 는 정수라 `omr/scans/demo/` 가 나올 수 없다 — 그래도 접두사로 확인."""
        self.assertNotIn(f"/{media.DEMO}/", media.omr_scan(11, "d"))
