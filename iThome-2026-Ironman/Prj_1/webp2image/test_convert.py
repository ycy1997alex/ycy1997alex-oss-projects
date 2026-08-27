"""ConverterModel 與隨附 App 圖示的驗收測試。

驗收標準有三項：

1. 四種輸出格式都轉得出來；JPEG / BMP 把透明壓成白底，PNG / TIFF 保留 alpha；
   動畫 webp 只取第一幀。
2. 批次行為正確：遞迴展開、略過已存在、覆寫、單檔失敗不中斷整批、
   should_continue 可提前中止。
3. 隨程式附帶的 App 圖示（webp2image_icon.ico）必須是多尺寸 .ico，
   否則檔案總管、視窗標題列、工作列至少有一處會模糊或退回預設圖示。

執行方式：
    python test_convert.py
"""
import tempfile
from pathlib import Path

from PIL import Image

from webp2image import APP_VERSION, ICON_FILENAME, ConverterModel, resource_path

# App 圖示的最低要求，取自 ui-project 的打包規則；少任何一個尺寸都算不合格
REQUIRED_ICON_SIZES = {(16, 16), (32, 32), (48, 48), (256, 256)}

# 半透明紅：alpha=128 壓白底後會變成淡紅，用來分辨有沒有被壓平
TRANSLUCENT_RED = (255, 0, 0, 128)


def _make_webp(path: Path, color=TRANSLUCENT_RED, size=(40, 30)):
    Image.new("RGBA", size, color).save(path, "WEBP", lossless=True)
    return path


def _make_animated_webp(path: Path):
    """兩幀動畫：第一幀純紅、第二幀純藍，用來確認只取到第一幀。"""
    first = Image.new("RGB", (20, 20), (255, 0, 0))
    second = Image.new("RGB", (20, 20), (0, 0, 255))
    first.save(path, "WEBP", save_all=True, append_images=[second], duration=100, lossless=True)
    return path


def check_formats(tmp_dir: Path):
    model = ConverterModel()
    source = _make_webp(tmp_dir / "src.webp")

    for fmt, suffix in ConverterModel.FORMATS.items():
        out_dir = tmp_dir / f"out_{fmt}"
        result = model.convert_one(source, out_dir, fmt, overwrite=False)
        assert result.status == "ok", f"[{fmt}] 轉換失敗：{result.message}"
        target = out_dir / ("src" + suffix)
        assert target.is_file(), f"[{fmt}] 找不到輸出檔 {target}"

        with Image.open(target) as out:
            assert out.size == (40, 30), f"[{fmt}] 尺寸被改變成 {out.size}"
            has_alpha = "A" in out.getbands()
            if fmt in ConverterModel._FLATTEN_FORMATS:
                assert not has_alpha, f"[{fmt}] 不支援 alpha，卻保留了透明通道"
                # 半透明紅壓白底後三個通道都應該偏亮，而不是純紅
                pixel = out.convert("RGB").getpixel((0, 0))
                assert pixel[1] > 100 and pixel[2] > 100, f"[{fmt}] 透明沒有壓成白底：{pixel}"
            else:
                assert has_alpha, f"[{fmt}] 應保留 alpha，實際 bands 為 {out.getbands()}"
        print(f"  PASS  輸出格式 {fmt}")


def check_animation(tmp_dir: Path):
    model = ConverterModel()
    source = _make_animated_webp(tmp_dir / "anim.webp")
    result = model.convert_one(source, tmp_dir / "out_anim", "PNG", overwrite=False)
    assert result.status == "ok", f"動畫轉換失敗：{result.message}"
    with Image.open(result.target) as out:
        pixel = out.convert("RGB").getpixel((10, 10))
    assert pixel[0] > 200 and pixel[2] < 60, f"取到的不是第一幀（紅），而是 {pixel}"
    print("  PASS  動畫 webp 只取第一幀")


def check_collect_sources(tmp_dir: Path):
    root = tmp_dir / "tree"
    (root / "sub").mkdir(parents=True)
    _make_webp(root / "a.webp")
    _make_webp(root / "sub" / "b.webp")
    # 副檔名大小寫不應影響判斷；非 webp 檔要被忽略
    _make_webp(root / "c.WEBP")
    (root / "note.txt").write_text("not an image", encoding="utf-8")

    shallow = ConverterModel.collect_sources([root], recursive=False)
    assert {p.name for p in shallow} == {"a.webp", "c.WEBP"}, f"非遞迴結果錯誤：{shallow}"

    deep = ConverterModel.collect_sources([root], recursive=True)
    assert {p.name for p in deep} == {"a.webp", "b.webp", "c.WEBP"}, f"遞迴結果錯誤：{deep}"

    # 同一個檔案同時以檔案與資料夾形式傳入，只能算一次
    deduped = ConverterModel.collect_sources([root, root / "a.webp"], recursive=True)
    assert len(deduped) == 3, f"重複來源沒有去重：{deduped}"
    print("  PASS  來源展開（遞迴／大小寫／去重）")


def check_skip_and_overwrite(tmp_dir: Path):
    model = ConverterModel()
    work = tmp_dir / "skip"
    work.mkdir()
    source = _make_webp(work / "s.webp")

    first = model.convert_one(source, work, "PNG", overwrite=False)
    assert first.status == "ok", f"第一次轉換就失敗：{first.message}"

    again = model.convert_one(source, work, "PNG", overwrite=False)
    assert again.status == "skipped", f"目標已存在時應略過，實際為 {again.status}"

    forced = model.convert_one(source, work, "PNG", overwrite=True)
    assert forced.status == "ok", f"覆寫模式應成功，實際為 {forced.status}"
    print("  PASS  已存在時略過／勾選覆寫時蓋掉")


def check_batch_resilience(tmp_dir: Path):
    model = ConverterModel()
    work = tmp_dir / "batch"
    work.mkdir()
    good_a = _make_webp(work / "good_a.webp")
    broken = work / "broken.webp"
    broken.write_bytes(b"this is not a webp file")
    good_b = _make_webp(work / "good_b.webp")

    results = model.convert_many([good_a, broken, good_b], work / "out", "PNG", overwrite=False)
    statuses = [r.status for r in results]
    assert statuses == ["ok", "failed", "ok"], f"毀損檔應只讓自己失敗，實際 {statuses}"
    print("  PASS  單檔毀損不中斷整批")


def check_should_continue(tmp_dir: Path):
    model = ConverterModel()
    work = tmp_dir / "stop"
    work.mkdir()
    sources = [_make_webp(work / f"n{i}.webp") for i in range(5)]

    seen = []

    def on_result(result, done, total):
        seen.append(done)

    # 做完第二個之後就要求停止
    results = model.convert_many(
        sources, work / "out", "PNG", overwrite=False,
        on_result=on_result,
        should_continue=lambda: len(seen) < 2,
    )
    assert len(results) == 2, f"應在第 2 個之後停手，實際完成 {len(results)} 個"
    print("  PASS  should_continue 可提前中止批次")


def check_shipped_icon():
    """檢查隨程式附帶的 App 圖示，而不是轉換出來的檔案。"""
    icon_path = Path(resource_path(ICON_FILENAME))
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


def check_version():
    assert APP_VERSION == "1", f"版本號應與 image2ico 一致為 \"1\"，實際為 {APP_VERSION!r}"
    print(f"  PASS  版本號 v{APP_VERSION}")


def run():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        check_formats(tmp_dir)
        check_animation(tmp_dir)
        check_collect_sources(tmp_dir)
        check_skip_and_overwrite(tmp_dir)
        check_batch_resilience(tmp_dir)
        check_should_continue(tmp_dir)

    check_shipped_icon()
    check_version()

    print("\n全部通過。")


if __name__ == "__main__":
    run()
