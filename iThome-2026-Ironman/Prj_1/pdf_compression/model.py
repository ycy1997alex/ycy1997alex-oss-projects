"""PDF 壓縮核心邏輯（Model）。不依賴任何 UI 套件，可獨立測試或於 CLI 使用。"""

from __future__ import annotations

import io
import os
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

import fitz
from PIL import Image


class CompressionCancelled(Exception):
    """使用者於轉換過程中取消操作。"""

# 型別註記：進度回呼 (目前張數, 總張數, 說明文字)；記錄回呼 (單行文字)
ProgressCallback = Callable[[int, int, str], None]
LogCallback = Callable[[str], None]

MIN_QUALITY = 35
MIN_SCALE = 0.3
QUALITY_STEP = 7
SCALE_STEP = 0.08
MAX_TRIALS = 8


@dataclass
class CompressionSettings:
    scale: float = 0.75           # 圖片縮放比例 (0.1~1.0)
    quality: int = 78             # JPEG 品質 (1~95)
    min_dim_px: int = 200         # 小於此邊長的圖片視為圖示/Logo，不壓縮
    target_size_mb: Optional[float] = None  # 目標檔案大小 (MB)，None 表示不自動搜尋
    auto_tune: bool = False       # 是否在超過目標大小時自動逐步加大壓縮強度


@dataclass
class CompressionAttempt:
    scale: float
    quality: int
    size_bytes: int


@dataclass
class CompressionResult:
    success: bool
    output_path: str
    original_size: int
    final_size: int
    replaced: int
    skipped: int
    attempts: list[CompressionAttempt] = field(default_factory=list)
    reached_target: Optional[bool] = None
    message: str = ""


class PdfCompressorModel:
    def compress(
        self,
        input_path: str,
        output_path: str,
        settings: CompressionSettings,
        progress_cb: Optional[ProgressCallback] = None,
        log_cb: Optional[LogCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> CompressionResult:
        if not os.path.isfile(input_path):
            raise FileNotFoundError(f"輸入檔案不存在: {input_path}")

        original_size = os.path.getsize(input_path)
        trials = self._build_trials(settings)
        attempts: list[CompressionAttempt] = []
        last_replaced = last_skipped = 0

        for scale, quality in trials:
            if log_cb:
                log_cb(f"嘗試壓縮：縮放={scale:.2f}、品質={quality} ...")

            try:
                size_bytes, replaced, skipped = self._compress_once(
                    input_path, output_path, scale, quality, settings.min_dim_px, progress_cb, cancel_event
                )
            except CompressionCancelled:
                return CompressionResult(
                    success=False,
                    output_path=output_path,
                    original_size=original_size,
                    final_size=0,
                    replaced=last_replaced,
                    skipped=last_skipped,
                    attempts=attempts,
                    reached_target=None,
                    message="使用者已取消轉換。",
                )
            attempts.append(CompressionAttempt(scale, quality, size_bytes))
            last_replaced, last_skipped = replaced, skipped

            if log_cb:
                log_cb(f"  -> 產出大小：{size_bytes / 1024 / 1024:.2f} MB")

            target_bytes = (settings.target_size_mb * 1024 * 1024) if settings.target_size_mb else None
            if target_bytes is None or size_bytes <= target_bytes:
                reached = True if target_bytes is None else size_bytes <= target_bytes
                return CompressionResult(
                    success=True,
                    output_path=output_path,
                    original_size=original_size,
                    final_size=size_bytes,
                    replaced=last_replaced,
                    skipped=last_skipped,
                    attempts=attempts,
                    reached_target=reached,
                    message="壓縮完成。" if target_bytes is None else "壓縮完成，已達目標大小。",
                )

            if not settings.auto_tune:
                break

        # 目標大小設定了但未達成（或未啟用自動搜尋）：保留最後一次（最小）的產出
        final_size = attempts[-1].size_bytes if attempts else original_size
        return CompressionResult(
            success=True,
            output_path=output_path,
            original_size=original_size,
            final_size=final_size,
            replaced=last_replaced,
            skipped=last_skipped,
            attempts=attempts,
            reached_target=False,
            message="壓縮完成，但未能達到目標大小（已用最強壓縮設定）。",
        )

    def _build_trials(self, settings: CompressionSettings) -> list[tuple[float, int]]:
        if not settings.target_size_mb or not settings.auto_tune:
            return [(settings.scale, settings.quality)]

        trials: list[tuple[float, int]] = []
        scale, quality = settings.scale, settings.quality
        for _ in range(MAX_TRIALS):
            pair = (round(scale, 2), int(quality))
            if not trials or trials[-1] != pair:
                trials.append(pair)
            if scale <= MIN_SCALE and quality <= MIN_QUALITY:
                break
            scale = max(MIN_SCALE, scale - SCALE_STEP)
            quality = max(MIN_QUALITY, quality - QUALITY_STEP)
        return trials

    def _compress_once(
        self,
        input_path: str,
        output_path: str,
        scale: float,
        quality: int,
        min_dim_px: int,
        progress_cb: Optional[ProgressCallback],
        cancel_event: Optional[threading.Event] = None,
    ) -> tuple[int, int, int]:
        doc = fitz.open(input_path)

        total = len({img[0] for page in doc for img in page.get_images(full=True)})
        seen: set[int] = set()
        replaced = skipped = 0
        done = 0

        for page in doc:
            for img in page.get_images(full=True):
                if cancel_event is not None and cancel_event.is_set():
                    doc.close()
                    raise CompressionCancelled()

                xref = img[0]
                if xref in seen:
                    continue
                seen.add(xref)
                done += 1
                if progress_cb:
                    progress_cb(done, total, f"處理圖片 {done}/{total}")

                info = doc.extract_image(xref)
                orig_bytes = info["image"]
                w, h = info["width"], info["height"]
                orig_total_bytes = len(orig_bytes)
                smask_xref = info.get("smask") or 0

                if w < min_dim_px or h < min_dim_px:
                    skipped += 1
                    continue

                try:
                    im = Image.open(io.BytesIO(orig_bytes))
                    if im.mode == "P":
                        im = im.convert("RGBA") if "transparency" in im.info else im.convert("RGB")

                    if smask_xref:
                        smask_info = doc.extract_image(smask_xref)
                        orig_total_bytes += len(smask_info["image"])
                        alpha = Image.open(io.BytesIO(smask_info["image"])).convert("L")
                        if alpha.size != im.size:
                            alpha = alpha.resize(im.size, Image.LANCZOS)
                        if im.mode != "RGB":
                            im = im.convert("RGB")
                        bg = Image.new("RGB", im.size, (255, 255, 255))
                        bg.paste(im, mask=alpha)
                        im = bg
                    elif im.mode in ("RGBA", "LA"):
                        bg = Image.new("RGB", im.size, (255, 255, 255))
                        bg.paste(im, mask=im.split()[-1])
                        im = bg
                    elif im.mode not in ("RGB", "L"):
                        im = im.convert("RGB")

                    new_w = max(1, int(w * scale))
                    new_h = max(1, int(h * scale))
                    im = im.resize((new_w, new_h), Image.LANCZOS)

                    buf = io.BytesIO()
                    im.save(buf, format="JPEG", quality=quality, optimize=True)
                    new_bytes = buf.getvalue()
                except Exception:
                    skipped += 1
                    continue

                if len(new_bytes) >= orig_total_bytes:
                    skipped += 1
                    continue

                page.replace_image(xref, stream=new_bytes)
                replaced += 1

        tmp_path = output_path + ".tmp"
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        # garbage=1 已足以移除 replace_image 留下的舊圖片物件（配合 clean=True 拿到與 garbage=4
        # 幾乎相同的壓縮效果），garbage>=3 會觸發全文件詳盡掃描，在這份文件上會慢上百倍（142s vs 1.7s）。
        doc.save(tmp_path, garbage=1, deflate=True, clean=True)
        doc.close()
        os.replace(tmp_path, output_path)

        return os.path.getsize(output_path), replaced, skipped
