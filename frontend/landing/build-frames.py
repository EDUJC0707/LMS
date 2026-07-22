#!/usr/bin/env python3
"""
Veo 클립 → 스크롤 스크러빙용 프레임 시퀀스.

rehearsal/clip__<안id>__<슬러그>.mp4 를 전부 찾아
frames/<안id>/f_000.webp ... 로 굽고, index.html이 읽을 VARIANTS 조각을 출력한다.

한 안에 클립이 둘이면(예: ruled-layout) 슬러그 알파벳 순으로 이어붙인다.
클립 경계에서 프레임이 튀지 않도록 뒤 클립의 첫 프레임은 버린다
(앞 클립의 마지막 프레임과 같은 상태를 노린 것이므로 중복이다).

품질 기준은 실측으로 정한 값이다:
  1600px / q82 → 장당 약 30KB, 96장 2.85MB.
  파일 용량이 아니라 디코드 RGBA(장당 약 3MB)가 상한이라
  scrub.js가 슬라이딩 윈도로 들고 있는다. 총 장수를 늘려도 메모리는 창 크기에 묶인다.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
REH = ROOT / "rehearsal"
OUT = ROOT / "frames"

TARGET = 96      # 안당 프레임 수
WIDTH = 1600
QUALITY = 82


def clips_by_variant() -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = {}
    for p in sorted(REH.glob("clip__*.mp4")):
        m = re.match(r"clip__(.+?)__(.+)\.mp4$", p.name)
        if not m:
            continue
        found.setdefault(m.group(1), []).append(p)
    return found


def explode(clip: Path, into: Path) -> list[Path]:
    into.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(clip),
         "-vf", "fps=24", str(into / "%04d.png")],
        check=True,
    )
    return sorted(into.glob("*.png"))


def build(vid: str, clips: list[Path]) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pool: list[Path] = []
        for i, clip in enumerate(clips):
            frames = explode(clip, tmp / f"c{i}")
            # 두 번째 클립부터는 첫 프레임을 버린다 — 앞 클립 끝과 중복이다.
            pool.extend(frames[1:] if i else frames)

        if not pool:
            raise SystemExit(f"{vid}: 프레임 0개")

        dst = OUT / vid
        shutil.rmtree(dst, ignore_errors=True)
        dst.mkdir(parents=True)

        n = len(pool)
        k = min(TARGET, n)
        idx = [round(i * (n - 1) / (k - 1)) for i in range(k)] if k > 1 else [0]

        total = 0
        for j, i in enumerate(idx):
            im = Image.open(pool[i]).convert("RGB")
            im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
            f = dst / f"f_{j:03d}.webp"
            im.save(f, "WEBP", quality=QUALITY, method=0)
            total += f.stat().st_size

        return {
            "id": vid,
            "count": k,
            "clips": len(clips),
            "source_frames": n,
            "mb": round(total / 1048576, 2),
            "kb_per_frame": total // k // 1024,
        }


def main() -> None:
    groups = clips_by_variant()
    if not groups:
        sys.exit("rehearsal/clip__*.mp4 없음 — Veo 생성이 끝났는지 확인할 것")

    OUT.mkdir(exist_ok=True)
    report = [build(vid, clips) for vid, clips in sorted(groups.items())]

    for r in report:
        print(f"{r['id']:16s} 클립{r['clips']}개 · 원본{r['source_frames']}f "
              f"→ {r['count']}f  {r['mb']}MB  장당 {r['kb_per_frame']}KB")

    (ROOT / "frames" / "manifest.json").write_text(
        json.dumps({r["id"]: {"count": r["count"], "pad": 3} for r in report},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nmanifest.json 기록 완료 ({len(report)}개 안)")


if __name__ == "__main__":
    main()
