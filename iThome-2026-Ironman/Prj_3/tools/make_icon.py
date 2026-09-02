r"""產生 app.ico。

要換圖示就改這裡再重跑一次：
    C:\Users\Alex\anaconda3\envs\nb_ble\python.exe tools\make_icon.py

在 1024px 畫布上畫、再降採樣，形狀刻意做粗，縮到 16px 時才不會糊成一團。
圖案是「一支手環在廣播、被聽見」：左邊一個直立的圓角矩形當錶面，右邊兩道
弧線往外散。置中的同心扇形試過，縮小後跟 Wi-Fi 圖示分不出來，所以改成
偏左的錶面加單側弧線。刻意不畫藍牙官方那個 rune 商標。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

CANVAS = 1024
ICO_SIZES = [16, 32, 48, 64, 128, 256]

BLUE = (69, 130, 236, 255)      # litera primary #4582ec
GREEN = (2, 184, 117, 255)      # litera success #02b875
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

    # 錶面：偏左的直立圓角矩形，整張圖的視覺重心。
    draw.rounded_rectangle([150, 310, 370, 714], radius=70, fill=WHITE)

    # 兩道從錶面右緣往外散的弧；外面那道換成成功色，代表「被聽見了」。
    # 弧與錶面之間、兩道弧之間都要留 100px 以上的空隙，縮到 16px 才不會黏成一塊。
    cx, cy = 300, CANVAS // 2
    for radius, width, color in [(340, 80, WHITE), (530, 70, GREEN)]:
        draw.arc(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            start=-48, end=48, fill=color, width=width,
        )

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
