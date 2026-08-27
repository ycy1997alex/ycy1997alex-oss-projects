"""PdfCompressorPresenter 的單元測試（stdlib unittest，不需額外套件）。

以 FakeView / FakeModel 取代真實 UI 與壓縮流程，因此不會開視窗、也不會處理 PDF。

執行：
    & $py -m unittest test_presenter -v
"""

from __future__ import annotations

import os
import tempfile
import threading
import unittest

from model import CompressionResult, CompressionSettings
from presenter import PdfCompressorPresenter
from view import PdfCompressorView


class FakeView:
    """實作 Presenter 用到的那部分 PdfCompressorView 介面。"""

    def __init__(self) -> None:
        self.input_path = ""
        self.output_dir = ""
        self.output_filename = ""
        self.target_size_mb_text = ""
        self.auto_tune = False
        self.scale = 0.75
        self.quality = 78
        self.min_dim = 200

        # 對話框的預設回應，測試可逐項覆寫
        self.open_pdf_result: str | None = None
        self.directory_result: str | None = None
        self.confirm_result = True

        # 記錄 Presenter 對 View 做過什麼
        self.status = ""
        self.log: list[str] = []
        self.progress: list[tuple[int, int]] = []
        self.running_calls: list[bool] = []
        self.errors: list[tuple[str, str]] = []
        self.warnings: list[tuple[str, str]] = []
        self.infos: list[tuple[str, str]] = []
        self.scheduled: list[tuple[int, object]] = []
        self.cancelled_ids: list[object] = []
        self.destroyed = False
        self.ask_directory_initial: str | None = None

        self.on_browse_input = None
        self.on_browse_output_dir = None
        self.on_start = None
        self.on_close = None

    # -- 事件綁定 --------------------------------------------------------- #
    def bind_browse_input(self, callback) -> None:
        self.on_browse_input = callback

    def bind_browse_output_dir(self, callback) -> None:
        self.on_browse_output_dir = callback

    def bind_start(self, callback) -> None:
        self.on_start = callback

    def bind_close(self, callback) -> None:
        self.on_close = callback

    # -- 對話框 ----------------------------------------------------------- #
    def ask_open_pdf(self):
        return self.open_pdf_result

    def ask_directory(self, initial=None):
        self.ask_directory_initial = initial
        return self.directory_result

    def confirm(self, title: str, message: str) -> bool:
        return self.confirm_result

    def show_info(self, title: str, message: str) -> None:
        self.infos.append((title, message))

    def show_warning(self, title: str, message: str) -> None:
        self.warnings.append((title, message))

    def show_error(self, title: str, message: str) -> None:
        self.errors.append((title, message))

    # -- 欄位讀寫 --------------------------------------------------------- #
    def get_input_path(self) -> str:
        return self.input_path

    def set_input_path(self, path: str) -> None:
        self.input_path = path

    def get_output_dir(self) -> str:
        return self.output_dir

    def set_output_dir(self, path: str) -> None:
        self.output_dir = path

    def get_output_filename(self) -> str:
        return self.output_filename

    def set_output_filename(self, name: str) -> None:
        self.output_filename = name

    def get_target_size_mb_text(self) -> str:
        return self.target_size_mb_text

    def get_auto_tune(self) -> bool:
        return self.auto_tune

    def get_scale(self) -> float:
        return self.scale

    def get_quality(self) -> int:
        return self.quality

    def get_min_dim(self) -> int:
        return self.min_dim

    # -- 狀態顯示 --------------------------------------------------------- #
    def set_progress(self, current: int, total: int) -> None:
        self.progress.append((current, total))

    def set_status(self, text: str) -> None:
        self.status = text

    def append_log(self, text: str) -> None:
        self.log.append(text)

    def clear_log(self) -> None:
        self.log.clear()

    def set_running(self, running: bool) -> None:
        self.running_calls.append(running)

    # -- 排程與關閉 ------------------------------------------------------- #
    def schedule(self, delay_ms: int, callback) -> str:
        """只記錄不執行；測試自行呼叫 presenter._poll_queue() 推進流程。"""
        self.scheduled.append((delay_ms, callback))
        return f"after#{len(self.scheduled)}"

    def cancel_scheduled(self, after_id) -> None:
        self.cancelled_ids.append(after_id)

    def destroy(self) -> None:
        self.destroyed = True


class FakeModel:
    """回傳預設結果的假 Model；也可設成拋例外。"""

    def __init__(self, result: CompressionResult | None = None, exc: Exception | None = None) -> None:
        self.result = result
        self.exc = exc
        self.calls: list[tuple[str, str, CompressionSettings]] = []
        self.block = threading.Event()
        self.block.set()

    def compress(self, input_path, output_path, settings, progress_cb=None, log_cb=None, cancel_event=None):
        self.calls.append((input_path, output_path, settings))
        self.block.wait()
        if self.exc is not None:
            raise self.exc
        if progress_cb:
            progress_cb(1, 2, "處理圖片 1/2")
        if log_cb:
            log_cb("嘗試壓縮 ...")
        return self.result


def make_result(**overrides) -> CompressionResult:
    defaults = dict(
        success=True,
        output_path="out.pdf",
        original_size=10 * 1024 * 1024,
        final_size=4 * 1024 * 1024,
        replaced=3,
        skipped=1,
        reached_target=True,
        message="壓縮完成。",
    )
    defaults.update(overrides)
    return CompressionResult(**defaults)


class PresenterTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

        self.input_path = os.path.join(self.tmpdir, "sample.pdf")
        with open(self.input_path, "wb") as fh:
            fh.write(b"%PDF-1.7\n")

        self.view = FakeView()
        self.model = FakeModel(result=make_result())
        self.presenter = PdfCompressorPresenter(self.view, self.model)
        self.addCleanup(self.presenter.shutdown)

    def fill_valid_inputs(self) -> None:
        self.view.input_path = self.input_path
        self.view.output_dir = os.path.join(self.tmpdir, "out")
        self.view.output_filename = "sample_LowResolution.pdf"

    def run_to_completion(self) -> None:
        """啟動轉換、等背景執行緒結束，再手動推進一次佇列輪詢。"""
        self.presenter.on_start()
        self.presenter._worker.join(timeout=5)
        self.presenter._poll_queue()


class BindingTest(PresenterTestBase):
    def test_presenter_binds_all_view_events(self) -> None:
        self.assertEqual(self.view.on_browse_input, self.presenter.on_browse_input)
        self.assertEqual(self.view.on_browse_output_dir, self.presenter.on_browse_output_dir)
        self.assertEqual(self.view.on_start, self.presenter.on_start)
        self.assertEqual(self.view.on_close, self.presenter.on_close)

    def test_fake_view_matches_real_view_api(self) -> None:
        """FakeView 的每個公開方法都必須在真實 View 上存在，避免介面悄悄漂移。"""
        for name in dir(FakeView):
            if name.startswith("_") or not callable(getattr(FakeView, name)):
                continue
            self.assertTrue(hasattr(PdfCompressorView, name), f"PdfCompressorView 缺少 {name}()")


class BrowseInputTest(PresenterTestBase):
    def test_selecting_input_fills_output_fields(self) -> None:
        self.view.open_pdf_result = os.path.join(self.tmpdir, "報告.pdf")

        self.presenter.on_browse_input()

        self.assertEqual(self.view.input_path, self.view.open_pdf_result)
        self.assertEqual(self.view.output_dir, self.tmpdir)
        self.assertEqual(self.view.output_filename, "報告_LowResolution.pdf")

    def test_cancelling_dialog_changes_nothing(self) -> None:
        self.view.open_pdf_result = None

        self.presenter.on_browse_input()

        self.assertEqual(self.view.input_path, "")
        self.assertEqual(self.view.output_filename, "")

    def test_browse_output_dir_starts_at_current_dir(self) -> None:
        self.view.output_dir = self.tmpdir
        self.view.directory_result = None

        self.presenter.on_browse_output_dir()

        self.assertEqual(self.view.ask_directory_initial, self.tmpdir)
        self.assertEqual(self.view.output_dir, self.tmpdir)


class ValidationTest(PresenterTestBase):
    def test_valid_inputs_pass(self) -> None:
        self.fill_valid_inputs()
        self.assertIsNone(self.presenter._validate())

    def test_missing_input_path(self) -> None:
        self.assertIn("輸入檔案", self.presenter._validate())

    def test_input_file_gone(self) -> None:
        self.fill_valid_inputs()
        os.remove(self.input_path)
        self.assertIn("不存在", self.presenter._validate())

    def test_missing_output_dir(self) -> None:
        self.fill_valid_inputs()
        self.view.output_dir = ""
        self.assertIn("輸出檔案路徑", self.presenter._validate())

    def test_missing_output_filename(self) -> None:
        self.fill_valid_inputs()
        self.view.output_filename = ""
        self.assertIn("檔案名稱", self.presenter._validate())

    def test_output_must_differ_from_input(self) -> None:
        self.fill_valid_inputs()
        self.view.output_dir = self.tmpdir
        self.view.output_filename = "sample.pdf"
        self.assertIn("不可與輸入檔案相同", self.presenter._validate())

    def test_output_same_as_input_without_extension_is_rejected(self) -> None:
        self.fill_valid_inputs()
        self.view.output_dir = self.tmpdir
        self.view.output_filename = "sample"
        self.assertIn("不可與輸入檔案相同", self.presenter._validate())

    def test_non_numeric_target_size(self) -> None:
        self.fill_valid_inputs()
        self.view.target_size_mb_text = "5 MB"
        self.assertIn("數字", self.presenter._validate())

    def test_non_positive_target_size(self) -> None:
        self.fill_valid_inputs()
        self.view.target_size_mb_text = "0"
        self.assertIn("大於 0", self.presenter._validate())

    def test_invalid_input_shows_error_and_starts_no_worker(self) -> None:
        self.presenter.on_start()

        self.assertEqual(len(self.view.errors), 1)
        self.assertIsNone(self.presenter._worker)
        self.assertEqual(self.model.calls, [])


class StartCompressionTest(PresenterTestBase):
    def test_settings_and_output_path_are_passed_to_model(self) -> None:
        self.fill_valid_inputs()
        self.view.scale, self.view.quality, self.view.min_dim = 0.6, 55, 150
        self.view.target_size_mb_text = "2.5"
        self.view.auto_tune = True

        self.run_to_completion()

        input_path, output_path, settings = self.model.calls[0]
        self.assertEqual(input_path, self.input_path)
        self.assertEqual(output_path, os.path.join(self.view.output_dir, "sample_LowResolution.pdf"))
        self.assertEqual(
            (settings.scale, settings.quality, settings.min_dim_px, settings.target_size_mb, settings.auto_tune),
            (0.6, 55, 150, 2.5, True),
        )
        self.assertTrue(os.path.isdir(self.view.output_dir))

    def test_auto_tune_is_ignored_without_target_size(self) -> None:
        self.fill_valid_inputs()
        self.view.auto_tune = True
        self.view.target_size_mb_text = ""

        self.run_to_completion()

        _input, _output, settings = self.model.calls[0]
        self.assertIsNone(settings.target_size_mb)
        self.assertFalse(settings.auto_tune)

    def test_missing_pdf_extension_is_appended(self) -> None:
        self.fill_valid_inputs()
        self.view.output_filename = "sample_small"

        self.run_to_completion()

        self.assertTrue(self.model.calls[0][1].endswith("sample_small.pdf"))

    def test_second_start_while_running_is_ignored(self) -> None:
        self.fill_valid_inputs()
        self.model.block.clear()  # 讓背景執行緒卡在 compress() 裡
        self.presenter.on_start()
        try:
            self.presenter.on_start()
            self.assertEqual(len(self.model.calls), 1)
        finally:
            self.model.block.set()
            self.presenter._worker.join(timeout=5)

    def test_success_reports_progress_log_and_info_dialog(self) -> None:
        self.fill_valid_inputs()

        self.run_to_completion()

        self.assertEqual(self.view.progress, [(1, 2)])
        self.assertIn("嘗試壓縮 ...", self.view.log)
        self.assertEqual(len(self.view.infos), 1)
        self.assertIn("縮減 60.0%", self.view.infos[0][1])
        self.assertEqual(self.view.status, "壓縮完成。")
        self.assertEqual(self.view.running_calls, [True, False])
        self.assertFalse(self.presenter._running)

    def test_missed_target_shows_warning_instead_of_info(self) -> None:
        self.fill_valid_inputs()
        self.model.result = make_result(reached_target=False, message="壓縮完成，但未能達到目標大小。")

        self.run_to_completion()

        self.assertEqual(self.view.infos, [])
        self.assertEqual(len(self.view.warnings), 1)

    def test_cancelled_result_reports_cancellation(self) -> None:
        self.fill_valid_inputs()
        self.model.result = make_result(success=False, final_size=0, message="使用者已取消轉換。")

        self.run_to_completion()

        self.assertEqual(self.view.status, "已取消。")
        self.assertIn("使用者已取消轉換。", self.view.log)
        self.assertEqual(self.view.infos, [])

    def test_model_exception_surfaces_as_error_dialog(self) -> None:
        self.fill_valid_inputs()
        self.model.exc = RuntimeError("boom")

        self.run_to_completion()

        self.assertEqual(len(self.view.errors), 1)
        self.assertIn("boom", self.view.errors[0][1])
        self.assertEqual(self.view.status, "轉換失敗。")
        self.assertFalse(self.presenter._running)


class CloseTest(PresenterTestBase):
    def test_idle_close_destroys_window(self) -> None:
        self.presenter.on_close()

        self.assertTrue(self.view.destroyed)

    def test_declining_confirmation_keeps_window_open(self) -> None:
        self.fill_valid_inputs()
        self.model.block.clear()
        self.presenter.on_start()
        self.view.confirm_result = False
        try:
            self.presenter.on_close()

            self.assertFalse(self.view.destroyed)
            self.assertFalse(self.presenter._cancel_event.is_set())
        finally:
            self.model.block.set()
            self.presenter._worker.join(timeout=5)

    def test_confirming_close_cancels_worker(self) -> None:
        self.fill_valid_inputs()
        self.model.block.clear()
        self.presenter.on_start()
        self.view.confirm_result = True
        self.model.block.set()

        self.presenter.on_close()

        self.assertTrue(self.presenter._cancel_event.is_set())
        self.assertTrue(self.view.destroyed)
        self.assertFalse(self.presenter._worker.is_alive())

    def test_shutdown_is_idempotent(self) -> None:
        self.presenter.shutdown()
        cancelled_after_first = len(self.view.cancelled_ids)

        self.presenter.shutdown()

        self.assertEqual(len(self.view.cancelled_ids), cancelled_after_first)


if __name__ == "__main__":
    unittest.main()
