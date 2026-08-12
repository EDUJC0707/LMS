"""OG 카드를 굽는다 — assets/og.png.

카톡·트위터·페이스북이 1.91:1 로 자르므로 **1200x630 을 고정**한다. 히어로 비율
(1200x800)로 주면 위아래 21% 가 잘려 인물 정수리와 발밑이 날아간다.

배치는 데스크탑 히어로에서 출발해 카드 크기에 맞게 조인 값이다(2026-08-11 대표 확정):
히어로의 강사 80svh·오른쪽5%·글자 --pad 를 기준으로, 둘을 **서로 5%씩 안쪽으로**
당기고 **각각 5% 키웠다**. 카드는 카톡 목록에서 손톱만 하게 뜨므로 히어로를 그대로
옮기면 인물이 작고 가운데가 빈다 — 실측 빈칸 485px → 333px.

**스크린샷을 오려 쓰지 않는다.** 전에 그렇게 만들었더니 nav 와 한쪽에만 있는 먼지가
딸려 들어왔다. 서체로 직접 그리고 먼지도 화면 전체에 고르게 뿌린다.

새 프사가 오면 teacher.webp 를 갈아 끼우고 이 스크립트를 다시 돌리면 된다.

    python3 assets/og-build.py        # frontend/landing 에서
"""
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont
import random, pathlib, tempfile

W, H = 1200, 630
HERE = pathlib.Path(__file__).parent

# PIL 은 woff2 를 못 읽는다 — 임시로 ttf 로 바꾼다
_t = TTFont(HERE / "fonts/SUIT-subset.woff2"); _t.flavor = None
_ttf = pathlib.Path(tempfile.gettempdir()) / "suit-og.ttf"; _t.save(_ttf)

c = Image.new("RGB", (W, H), (0, 0, 0))          # --bg
d = ImageDraw.Draw(c, "RGBA")

# 먼지 — field.js 와 같은 규격(1~4px · 알파 .10~.40 · --glow #9EAEE1), 면적당 밀도도 동일
random.seed(7)
for _ in range(int(4000 * (W * H) / (1200 * 800))):
    x, y = random.random() * W, random.random() * H
    r = random.uniform(1.0, 4.0) / 2
    d.ellipse([x - r, y - r, x + r, y + r],
              fill=(158, 174, 225, int(255 * random.uniform(.10, .40))))

STEP = round(W * 0.05)                            # 서로 다가가는 양

T = Image.open(HERE / "teacher/nobg/teacher.webp").convert("RGBA")
th = round(H * 0.80 * 1.05)                       # 히어로 80svh 에서 +5%
t = T.resize((round(T.width * th / T.height), th), Image.LANCZOS)
c.paste(t, (W - (round(W * 0.05) + STEP) - t.width, H - th), t)

fs = 63.6 * 1.05                                  # 히어로 63.6px 에서 +5%
f = ImageFont.truetype(str(_ttf), round(fs))
f.set_variation_by_axes([900])                    # SUIT 기본은 100 이다 — 900 을 박아야 한다
gap, ls = round(fs * 0.20), -0.045 * fs           # h1 의 gap .20em · letter-spacing -.045em
tx = 54 + STEP                                    # 히어로 --pad(1200 에서 54px) 에서 안쪽으로
ty = (H - (round(fs) * 2 + gap)) // 2

def line(s, y, col):
    x = tx
    for ch in s:                                  # letter-spacing 은 직접 먹인다
        d.text((x, y), ch, font=f, fill=col)
        x += d.textlength(ch, font=f) + ls

line("통합과학도",   ty,                    (96, 109, 164))    # --t1
line("철두철미하게", ty + round(fs) + gap,  (238, 241, 250))   # --t2

c.save(HERE / "og.png", "PNG", optimize=True)
print(f"assets/og.png  {W}x{H}")
