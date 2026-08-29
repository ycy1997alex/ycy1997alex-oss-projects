"""產生 app.ico。

要換圖示就改這裡再重跑一次：
    C:\\Users\\Alex\\anaconda3\\envs\\stats\\python.exe tools\\make_icon.py

在 1024px 畫布上畫、再降採樣，形狀刻意做粗，縮到 16px 時才不會糊成一團。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

CANVAS = 1024
ICO_SIZES = [16, 32, 48, 64, 128, 256]

BLUE = (39, 128, 227, 255)      # cosmo primary #2780e3
ORANGE = (255, 117, 24, 255)    # cosmo warning #ff7518
WHITE = (255, 255, 255, 255)

OUT = Path(__file__).resolve().parent.parent / "app.ico"


def draw_icon() -> Image.Image:
    image = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    margin = 40
    draw.rounded_rectangle(
        [margin, margin, CANVAS - margin, CANVAS - margin],
        radius=170, fill=BLUE,
    )

    # 座標軸：L 形，線要夠粗，縮小後才看得見。
    axis_w = 46
    left, bottom, top, right = 230, 800, 210, 810
    draw.line([(left, top), (left, bottom)], fill=WHITE, width=axis_w)
    draw.line([(left, bottom), (right, bottom)], fill=WHITE, width=axis_w)

    # 迴歸線：整張圖的主體，斜著上升。
    draw.line([(280, 720), (770, 300)], fill=ORANGE, width=68)

    # 散布點：貼著迴歸線兩側，數量少但夠大顆。
    radius = 52
    for cx, cy in [(330, 640), (450, 610), (520, 470), (640, 440), (720, 320)]:
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=WHITE)

    return image


def main() -> None:
    master = draw_icon()
    frames = [master.resize((s, s), Image.Resampling.LANCZOS) for s in ICO_SIZES]
    frames[-1].save(OUT, format="ICO", sizes=[(s, s) for s in ICO_SIZES], append_images=frames[:-1])

    with Image.open(OUT) as check:
        print(f"寫入 {OUT}")
        print("內含解析度：", sorted(check.ico.sizes()))


if __name__ == "__main__":
    main()
