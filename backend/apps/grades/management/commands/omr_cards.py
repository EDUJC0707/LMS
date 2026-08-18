"""인쇄용 OMR 카드 PDF 를 뽑는다 — 온라인 인쇄 발주에 그대로 올리는 파일.

    python manage.py omr_cards --out local/cards
    python manage.py omr_cards --layout 답안25 --exam "2027 OMEGA black 3회"

회차명을 주면 지면에 박히고, 비우면 **손으로 적는 줄**이 남는다 — 시험마다
카드를 생성해 주는 것이 기본이고(대표 2026-08-18), 미리 찍어 둘 수도 있다.

**배율 조정 없이(100%) 인쇄해야 한다.** 호모그래피가 배율을 흡수하므로 판독 자체는
축소돼도 되지만, 버블이 펜보다 작아지면 학생이 칠할 수가 없다.
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.grades.omr import generate, layout


class Command(BaseCommand):
    help = "인쇄용 OMR 카드 PDF 생성(판형 5종 + 성적 조사)"

    def add_arguments(self, parser):
        parser.add_argument("--out", default="local/cards", help="출력 폴더")
        parser.add_argument("--layout", action="append", help="판형 이름(여러 번 가능)")
        parser.add_argument("--title", default="한종철 생명과학")
        parser.add_argument("--exam", default="", help="회차명 — 비우면 손으로 적는 줄이 남는다")

    def handle(self, *args, **options):
        names = options["layout"] or [card.name for card in layout.LAYOUTS]
        unknown = [name for name in names if name not in layout.BY_NAME]
        if unknown:
            raise CommandError(
                f"모르는 판형: {', '.join(unknown)} — 가능한 값: {', '.join(layout.BY_NAME)}"
            )

        out = Path(options["out"])
        out.mkdir(parents=True, exist_ok=True)
        for name in names:
            card = layout.BY_NAME[name]
            path = out / f"omr-{name}.pdf"
            path.write_bytes(
                generate.render(card, title=options["title"], exam=options["exam"])
            )
            bars = "".join("■" if slot else "·" for slot in card.bars())
            self.stdout.write(f"{path}  판형 {card.layout_id} {bars}")
