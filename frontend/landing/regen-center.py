#!/usr/bin/env python3
"""
중앙 구도 자산 재생성 — 쿼터가 풀릴 때까지 버티는 재시도 러너.

이미지 API가 429로 막히면 그냥 실패시키지 않고 지수 백오프로 기다렸다 다시 친다.
성공한 항목은 .center-done에 적어두므로 몇 번을 다시 돌려도 이미 만든 건 건너뛴다.
(오늘 이미지 생성을 네 번 돌렸더니 프로젝트 쿼터가 소진됐다. 사람이 붙어 있을 필요가
 없도록 이 스크립트가 대신 기다린다.)

  python3 regen-center.py            # 이미지 → 영상 순으로 전부
  python3 regen-center.py --videos   # 영상만
"""
import io
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image

HERE = Path(__file__).resolve().parent
REH = HERE / "rehearsal"
MOTIFS = HERE / "assets" / "motifs"
LEDGER = REH / ".center-done"

load_dotenv("/Users/seanpark/Desktop/personal_projects/Gemini-Image/.env")
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

IMAGE_MODEL = "gemini-3-pro-image"
VIDEO_MODEL = "models/veo-3.1-generate-preview"
BACKOFF_START = 60
BACKOFF_MAX = 900


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def is_quota(err: Exception) -> bool:
    s = str(err)
    return "429" in s or "RESOURCE_EXHAUSTED" in s


class Ledger:
    """이미 만든 것을 두 번 만들지 않기 위한 기록."""

    def __init__(self, path: Path):
        self.path = path
        self.done = set(path.read_text().split()) if path.exists() else set()

    def has(self, key: str) -> bool:
        return key in self.done

    def add(self, key: str) -> None:
        self.done.add(key)
        with self.path.open("a") as f:
            f.write(key + "\n")


def as_part(path: Path) -> types.Image | None:
    if not path.exists():
        return None
    buf = io.BytesIO()
    Image.open(path).convert("RGB").save(buf, "PNG")
    return types.Image(image_bytes=buf.getvalue(), mime_type="image/png")


def make_image(pid: str, slug: str, prompt: str, ref: str) -> bool:
    contents: list = [prompt]
    if ref and ref != "none":
        fp = MOTIFS / (ref if ref.endswith(".webp") else f"{ref}.webp")
        if fp.exists():
            contents.append(Image.open(fp).convert("RGBA"))
    resp = client.models.generate_content(
        model=IMAGE_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
            image_config=types.ImageConfig(aspect_ratio="16:9", image_size="2K"),
        ),
    )
    for part in resp.candidates[0].content.parts:
        if part.inline_data:
            out = REH / "frames" / f"{pid}__{slug}.png"
            Image.open(io.BytesIO(part.inline_data.data)).save(out)
            return True
    return False


def make_video(pid: str, spec: dict) -> bool:
    first = as_part(REH / "frames" / f"{pid}__{spec['first_frame']}.png")
    if first is None:
        log(f"  건너뜀 {pid}/{spec['slug']} — 첫프레임 없음")
        return False

    cfg: dict = dict(number_of_videos=1, aspect_ratio="16:9", resolution="1080p")
    last = spec.get("last_frame", "none")
    if last and last != "none":
        part = as_part(REH / "frames" / f"{pid}__{last}.png")
        if part is not None:
            cfg["last_frame"] = part

    started = time.time()
    op = client.models.generate_videos(
        model=VIDEO_MODEL, prompt=spec["prompt"], image=first,
        config=types.GenerateVideosConfig(**cfg),
    )
    while not op.done:
        time.sleep(10)
        op = client.operations.get(op)
        if time.time() - started > 900:
            raise TimeoutError("veo 응답 지연")

    videos = getattr(op.response, "generated_videos", None) or []
    if not videos:
        return False
    client.files.download(file=videos[0].video)
    out = REH / f"clip__{pid}__{spec['slug']}.mp4"
    videos[0].video.save(str(out))
    log(f"  ok {pid}/{spec['slug']} {out.stat().st_size // 1024}KB "
        f"({int(time.time() - started)}s)")
    return True


def run(task, key: str, ledger: Ledger, label: str) -> None:
    """쿼터가 풀릴 때까지 버티며 하나를 완수한다."""
    if ledger.has(key):
        return
    backoff = BACKOFF_START
    while True:
        try:
            if task():
                ledger.add(key)
            else:
                log(f"  빈응답 {label}")
            return
        except Exception as e:  # noqa: BLE001 — 쿼터만 재시도, 나머지는 기록하고 통과
            if not is_quota(e):
                log(f"  실패 {label} — {str(e)[:80]}")
                return
            log(f"  쿼터 대기 {backoff}s ({label})")
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)


def main() -> None:
    packs = json.loads((REH / "PROMPTS-center.json").read_text(encoding="utf-8"))
    ledger = Ledger(LEDGER)
    videos_only = "--videos" in sys.argv

    if not videos_only:
        jobs = [(pid, im) for pid, pk in packs.items() for im in pk["images"]]
        left = sum(1 for pid, im in jobs if not ledger.has(f"img:{pid}/{im['slug']}"))
        log(f"이미지 {len(jobs)}장 중 {left}장 남음")
        for pid, im in jobs:
            key = f"img:{pid}/{im['slug']}"
            run(lambda p=pid, i=im: make_image(p, i["slug"], i["prompt"],
                                               i.get("reference_asset", "none")),
                key, ledger, f"{pid}/{im['slug']}")
            if ledger.has(key):
                log(f"  ok {pid}/{im['slug']}")
                time.sleep(20)      # 쿼터를 다시 때리지 않도록 간격을 둔다
        log("이미지 단계 종료")

    vjobs = [(pid, v) for pid, pk in packs.items()
             for v in pk["videos"] if "fallback" not in v["slug"]]
    log(f"Veo {len(vjobs)}클립 시작")
    for pid, spec in vjobs:
        run(lambda p=pid, s=spec: make_video(p, s),
            f"vid:{pid}/{spec['slug']}", ledger, f"{pid}/{spec['slug']}")
    log("ALLDONE")


if __name__ == "__main__":
    main()
