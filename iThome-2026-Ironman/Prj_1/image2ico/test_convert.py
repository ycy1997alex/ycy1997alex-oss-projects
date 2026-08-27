"""
IconConverterModel 的轉換驗收測試。

驗收標準有兩項：

1. 不論來源圖的尺寸、長寬比、色彩模式為何，輸出的 .ico 都必須包含
   16/32/48/64/128/256 六種「正方形」尺寸。
2. 隨程式附帶的 App 圖示（image2ico_icon.ico）本身也必須是多尺寸 .ico，
   否則檔案總管、視窗標題列、工作列至少有一處會模糊或退回預設圖示。

執行方式：
    python test_convert.py
"""
import tempfile
from pathlib import Path

from PIL import Image

from image2ico import ICON_NAME, IconConverterModel, resource_path

EXPECTED = {(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}

# App 圖示的最低要求，取自 ui-project 的打包規則；少任何一個尺寸都算不合格
REQUIRED_ICON_SIZES = {(16, 16), (32, 32), (48, 48), (256, 256)}


def _convert(model, tmp_dir, name, source: Image.Image, save_kwargs=None):
    src_path = tmp_dir / f"{name}{'.png' if source.mode == 'RGBA' else '.png'}"
    source.save(src_path, **(save_kwargs or {}))
    out_path = tmp_dir / f"{name}.ico"
    return model.convert_to_ico(str(src_path), str(out_path)), out_path


def _assert_ok(result, out_path, label):
    success, msg, _notes = result
    assert success, f"[{label}] 轉換失敗：{msg}"
    with Image.open(out_path) as ico:
        sizes = set(ico.ico.sizes())
    assert sizes == EXPECTED, f"[{label}] 尺寸不符，實際為 {sorted(sizes)}"
    print(f"  PASS  {label}")


def check_shipped_icon():
    """檢查隨程式附帶的 App 圖示，而不是轉換出來的檔案。"""
    icon_path = Path(resource_path(ICON_NAME))
    assert icon_path.is_file(), f"找不到 App 圖示 {icon_path}"

    with Image.open(icon_path) as ico:
        sizes = set(ico.ico.sizes())
        missing = sorted(REQUIRED_ICON_SIZES - sizes)
        assert not missing, f"App 圖示缺少尺寸 {missing}，實際只有 {sorted(sizes)}"
        # 只看宣告的尺寸不夠：非正方形來源做出來的 .ico 會宣告 256 卻存成 256x128
        for size in sorted(sizes):
            frame = ico.ico.getimage(size)
            assert frame.size == size, f"App 圖示 {size} 的 frame 實際是 {frame.size}"
            assert frame.width == frame.height, f"App 圖示 {size} 的 frame 不是正方形"

    print(f"  PASS  App 圖示 {icon_path.name} 含尺寸 {sorted(sizes)}")


def run():
    model = IconConverterModel()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # 1. 來源比 256 小：舊版會靜默丟掉 128/256
        small = Image.new("RGB", (100, 100), (200, 30, 30))
        result, out = _convert(model, tmp_dir, "small", small)
        _assert_ok(result, out, "小尺寸來源 100x100 RGB")
        assert result[2], "小尺寸來源應回報放大提醒"

        # 2. 非正方形：舊版會產生 256x128 這種非正方形 frame
        wide = Image.new("RGBA", (800, 400), (30, 90, 200, 255))
        result, out = _convert(model, tmp_dir, "wide", wide)
        _assert_ok(result, out, "非正方形來源 800x400 RGBA")
        assert result[2], "非正方形來源應回報補邊提醒"
        # 補出來的邊必須是透明的
        with Image.open(out) as ico:
            frame = ico.convert("RGBA")
        assert frame.getpixel((5, 5))[3] == 0, "補邊處應為透明"

        # 3. 調色盤 + 透明度（GIF / 8-bit PNG 常見）
        pal = Image.new("P", (300, 300))
        pal.info["transparency"] = 0
        result, out = _convert(model, tmp_dir, "palette", pal)
        _assert_ok(result, out, "調色盤來源 300x300 P")

        # 4. 大張正方形 RGB：正常路徑，不應有任何提醒
        big = Image.new("RGB", (1024, 1024), (10, 120, 60))
        result, out = _convert(model, tmp_dir, "big", big)
        _assert_ok(result, out, "正常來源 1024x1024 RGB")
        assert not result[2], f"正常來源不應有提醒，卻回報 {result[2]}"

        # 5. 不是圖片的檔案應乾淨地失敗，而不是拋例外
        bogus = tmp_dir / "bogus.png"
        bogus.write_bytes(b"not an image at all")
        success, msg, _ = model.convert_to_ico(str(bogus), str(tmp_dir / "bogus.ico"))
        assert not success, "非圖片檔應轉換失敗"
        print(f"  PASS  非圖片檔被擋下（{msg}）")

    # 6. 隨程式附帶的 App 圖示本身
    check_shipped_icon()

    print("\n全部通過。")


if __name__ == "__main__":
    run()
