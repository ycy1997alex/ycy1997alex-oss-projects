"""連接 View 與 Model（Presenter）。負責事件處理、輸入驗證與背景執行緒排程。"""

from __future__ import annotations

import os
import queue
import threading
from typing import Optional

from model import CompressionResult, CompressionSettings, PdfCompressorModel
from view import PdfCompressorView

POLL_INTERVAL_MS = 100
JOIN_TIMEOUT_SEC = 3.0


class PdfCompressorPresenter:
    def __init__(self, view: PdfCompressorView, model: PdfCompressorModel) -> None:
        self.view = view
        self.model = model

        self._queue: "queue.Queue[tuple]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()
        self._poll_after_id: Optional[str] = None
        self._running = False
        self._shutdown_done = False

        view.bind_browse_input(self.on_browse_input)
        view.bind_browse_output_dir(self.on_browse_output_dir)
        view.bind_start(self.on_start)
        view.bind_close(self.on_close)

    # ------------------------------------------------------------------ #
    # 檔案選擇
    # ------------------------------------------------------------------ #
    def on_browse_input(self) -> None:
        path = self.view.ask_open_pdf()
        if not path:
            return
        self.view.set_input_path(path)

        directory, filename = os.path.split(path)
        stem, _ext = os.path.splitext(filename)
        self.view.set_output_dir(directory)
        self.view.set_output_filename(f"{stem}_LowResolution.pdf")
        self.view.set_status("已選擇輸入檔案，請確認輸出設定後按下「開始轉換」。")

    def on_browse_output_dir(self) -> None:
        current = self.view.get_output_dir() or os.path.dirname(self.view.get_input_path() or "") or None
        path = self.view.ask_directory(initial=current)
        if path:
            self.view.set_output_dir(path)

    # ------------------------------------------------------------------ #
    # 開始轉換
    # ------------------------------------------------------------------ #
    def on_start(self) -> None:
        if self._running:
            return

        error = self._validate()
        if error:
            self.view.show_error("輸入有誤", error)
            return

        input_path = self.view.get_input_path()
        output_dir = self.view.get_output_dir()
        output_name = self.view.get_output_filename()
        if not output_name.lower().endswith(".pdf"):
            output_name += ".pdf"
        output_path = os.path.join(output_dir, output_name)

        os.makedirs(output_dir, exist_ok=True)

        target_text = self.view.get_target_size_mb_text()
        target_size_mb = float(target_text) if target_text else None

        settings = CompressionSettings(
            scale=self.view.get_scale(),
            quality=self.view.get_quality(),
            min_dim_px=self.view.get_min_dim(),
            target_size_mb=target_size_mb,
            auto_tune=self.view.get_auto_tune() if target_size_mb else False,
        )

        self.view.clear_log()
        self.view.set_status("轉換中...")
        self.view.set_running(True)
        self._running = True
        self._cancel_event = threading.Event()

        self._worker = threading.Thread(
            target=self._run_compression,
            args=(input_path, output_path, settings),
            daemon=True,
        )
        self._worker.start()
        self._poll_after_id = self.view.schedule(POLL_INTERVAL_MS, self._poll_queue)

    def _validate(self) -> Optional[str]:
        input_path = self.view.get_input_path()
        if not input_path:
            return "請先選擇輸入檔案。"
        if not os.path.isfile(input_path):
            return "輸入檔案不存在，請重新選擇。"

        output_dir = self.view.get_output_dir()
        if not output_dir:
            return "請選擇輸出檔案路徑。"

        output_name = self.view.get_output_filename()
        if not output_name:
            return "請輸入輸出檔案名稱。"

        name_with_ext = output_name if output_name.lower().endswith(".pdf") else output_name + ".pdf"
        if os.path.abspath(os.path.join(output_dir, name_with_ext)) == os.path.abspath(input_path):
            return "輸出檔案不可與輸入檔案相同，請更改輸出路徑或檔名，避免覆蓋原始檔案。"

        target_text = self.view.get_target_size_mb_text()
        if target_text:
            try:
                value = float(target_text)
            except ValueError:
                return "目標檔案大小必須是數字（單位 MB）。"
            if value <= 0:
                return "目標檔案大小必須大於 0。"

        return None

    # ------------------------------------------------------------------ #
    # 背景執行緒
    # ------------------------------------------------------------------ #
    def _run_compression(self, input_path: str, output_path: str, settings: CompressionSettings) -> None:
        try:
            result = self.model.compress(
                input_path,
                output_path,
                settings,
                progress_cb=lambda cur, total, msg: self._queue.put(("progress", cur, total, msg)),
                log_cb=lambda text: self._queue.put(("log", text)),
                cancel_event=self._cancel_event,
            )
            self._queue.put(("done", result))
        except Exception as exc:  # noqa: BLE001 - 需將任何例外送回主執行緒顯示
            self._queue.put(("error", str(exc)))

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == "progress":
                    _, current, total, message = item
                    self.view.set_progress(current, total)
                    self.view.set_status(message)
                elif kind == "log":
                    self.view.append_log(item[1])
                elif kind == "error":
                    self._finish(success=False)
                    self.view.set_status("轉換失敗。")
                    self.view.show_error("轉換失敗", item[1])
                    return
                elif kind == "done":
                    self._on_done(item[1])
                    return
        except queue.Empty:
            pass

        if self._running:
            self._poll_after_id = self.view.schedule(POLL_INTERVAL_MS, self._poll_queue)

    def _on_done(self, result: CompressionResult) -> None:
        self._finish(success=result.success)

        if not result.success:
            self.view.set_status("已取消。")
            self.view.append_log(result.message)
            return

        reduction = 0.0
        if result.original_size:
            reduction = (1 - result.final_size / result.original_size) * 100

        summary = (
            f"原始大小：{result.original_size / 1024 / 1024:.2f} MB\n"
            f"壓縮後大小：{result.final_size / 1024 / 1024:.2f} MB（縮減 {reduction:.1f}%）\n"
            f"已壓縮圖片數：{result.replaced}，略過：{result.skipped}\n"
            f"輸出檔案：{result.output_path}"
        )
        self.view.append_log(result.message)
        self.view.append_log(summary)
        self.view.set_status(result.message)

        if result.reached_target is False:
            self.view.show_warning("未達目標大小", f"{result.message}\n\n{summary}")
        else:
            self.view.show_info("轉換完成", summary)

    def _finish(self, success: bool) -> None:
        self._running = False
        self.view.set_running(False)
        self.view.cancel_scheduled(self._poll_after_id)
        self._poll_after_id = None

    # ------------------------------------------------------------------ #
    # 安全關閉
    # ------------------------------------------------------------------ #
    def on_close(self) -> None:
        if self._running:
            if not self.view.confirm("轉換進行中", "轉換尚未完成，確定要中止並關閉視窗嗎？"):
                return
            self._cancel_event.set()

        self.shutdown()
        self.view.destroy()

    def shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True

        self.view.cancel_scheduled(self._poll_after_id)
        self._poll_after_id = None

        self._cancel_event.set()
        if self._worker is not None and self._worker.is_alive():
            self._worker.join(timeout=JOIN_TIMEOUT_SEC)
