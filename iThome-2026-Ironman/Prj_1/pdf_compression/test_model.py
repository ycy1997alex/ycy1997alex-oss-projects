"""PdfCompressorModel 的單元測試（stdlib unittest，不需額外套件）。

執行：
    & $py -m unittest test_model -v
"""

from __future__ import annotations

import io
import os
import random
import tempfile
import threading
import unittest

import fitz
from PIL import Image

from model import (
    MAX_TRIALS,
    MIN_QUALITY,
    MIN_SCALE,
    CompressionSettings,
    PdfCompressorModel,
)


def make_noise_jpeg(width: int, height: int) -> bytes:
    """產生一張雜訊圖並存成高品質 JPEG。雜訊無法被再壓縮，可確保檔案夠大。"""
    rng = random.Random(1234)
    im = Image.new("RGB", (width, height))
    im.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(width * height)])
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def make_pdf(path: str, image_sizes: list[tuple[int, int]]) -> None:
    """依 image_sizes 建立一份 PDF，每張圖各佔一頁。"""
    doc = fitz.open()
    for width, height in image_sizes:
        page = doc.new_page(width=width, height=height)
        page.insert_image(fitz.Rect(0, 0, width, height), stream=make_noise_jpeg(width, height))
    doc.save(path)
    doc.close()


class BuildTrialsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.model = PdfCompressorModel()

    def test_no_target_size_gives_single_trial(self) -> None:
        settings = CompressionSettings(scale=0.75, quality=78)
        self.assertEqual(self.model._build_trials(settings), [(0.75, 78)])

    def test_target_without_auto_tune_gives_single_trial(self) -> None:
        settings = CompressionSettings(scale=0.6, quality=60, target_size_mb=1.0, auto_tune=False)
        self.assertEqual(self.model._build_trials(settings), [(0.6, 60)])

    def test_auto_tune_trials_are_monotonically_stronger(self) -> None:
        settings = CompressionSettings(scale=0.9, quality=90, target_size_mb=1.0, auto_tune=True)
        trials = self.model._build_trials(settings)

        self.assertEqual(trials[0], (0.9, 90))
        self.assertLessEqual(len(trials), MAX_TRIALS)
        for (prev_scale, prev_quality), (scale, quality) in zip(trials, trials[1:]):
            self.assertLessEqual(scale, prev_scale)
            self.assertLessEqual(quality, prev_quality)

    def test_auto_tune_never_goes_below_floor(self) -> None:
        settings = CompressionSettings(scale=0.35, quality=40, target_size_mb=1.0, auto_tune=True)
        trials = self.model._build_trials(settings)

        for scale, quality in trials:
            self.assertGreaterEqual(scale, MIN_SCALE)
            self.assertGreaterEqual(quality, MIN_QUALITY)
        self.assertEqual(trials[-1], (MIN_SCALE, MIN_QUALITY))
        # 觸底後就該停，不應把剩下的 MAX_TRIALS 次都填成同一組參數
        self.assertEqual(len(trials), len(set(trials)))


class CompressTest(unittest.TestCase):
    def setUp(self) -> None:
        self.model = PdfCompressorModel()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def input_pdf(self, image_sizes: list[tuple[int, int]]) -> str:
        path = os.path.join(self.tmpdir, "input.pdf")
        make_pdf(path, image_sizes)
        return path

    @property
    def output_pdf(self) -> str:
        return os.path.join(self.tmpdir, "output.pdf")

    def test_missing_input_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self.model.compress(
                os.path.join(self.tmpdir, "nope.pdf"), self.output_pdf, CompressionSettings()
            )

    def test_compression_shrinks_file_and_keeps_it_readable(self) -> None:
        input_path = self.input_pdf([(800, 600)])
        settings = CompressionSettings(scale=0.5, quality=40)

        result = self.model.compress(input_path, self.output_pdf, settings)

        self.assertTrue(result.success)
        self.assertEqual(result.replaced, 1)
        self.assertEqual(result.skipped, 0)
        self.assertLess(result.final_size, result.original_size)
        self.assertEqual(result.final_size, os.path.getsize(self.output_pdf))
        self.assertTrue(result.reached_target)

        doc = fitz.open(self.output_pdf)
        self.addCleanup(doc.close)
        self.assertEqual(doc.page_count, 1)

    def test_input_file_is_left_untouched(self) -> None:
        input_path = self.input_pdf([(800, 600)])
        before = os.path.getsize(input_path)

        self.model.compress(input_path, self.output_pdf, CompressionSettings(scale=0.5, quality=40))

        self.assertEqual(os.path.getsize(input_path), before)

    def test_images_smaller_than_min_dim_are_skipped(self) -> None:
        input_path = self.input_pdf([(120, 90)])

        result = self.model.compress(
            input_path, self.output_pdf, CompressionSettings(scale=0.5, quality=40, min_dim_px=200)
        )

        self.assertEqual(result.replaced, 0)
        self.assertEqual(result.skipped, 1)

    def test_progress_and_log_callbacks_are_invoked(self) -> None:
        input_path = self.input_pdf([(800, 600), (700, 500)])
        progress: list[tuple[int, int, str]] = []
        logs: list[str] = []

        self.model.compress(
            input_path,
            self.output_pdf,
            CompressionSettings(scale=0.5, quality=40),
            progress_cb=lambda cur, total, msg: progress.append((cur, total, msg)),
            log_cb=logs.append,
        )

        self.assertEqual([cur for cur, _total, _msg in progress], [1, 2])
        self.assertTrue(all(total == 2 for _cur, total, _msg in progress))
        self.assertTrue(logs)

    def test_reachable_target_reports_success(self) -> None:
        input_path = self.input_pdf([(800, 600)])
        settings = CompressionSettings(scale=0.5, quality=40, target_size_mb=100.0, auto_tune=True)

        result = self.model.compress(input_path, self.output_pdf, settings)

        self.assertTrue(result.success)
        self.assertTrue(result.reached_target)
        self.assertEqual(len(result.attempts), 1)

    def test_unreachable_target_exhausts_trials_and_keeps_last_output(self) -> None:
        input_path = self.input_pdf([(800, 600)])
        settings = CompressionSettings(scale=0.9, quality=90, target_size_mb=0.001, auto_tune=True)

        result = self.model.compress(input_path, self.output_pdf, settings)

        self.assertTrue(result.success)
        self.assertFalse(result.reached_target)
        self.assertGreater(len(result.attempts), 1)
        self.assertEqual(result.final_size, result.attempts[-1].size_bytes)
        self.assertTrue(os.path.isfile(self.output_pdf))

    def test_unreachable_target_without_auto_tune_tries_once(self) -> None:
        input_path = self.input_pdf([(800, 600)])
        settings = CompressionSettings(scale=0.9, quality=90, target_size_mb=0.001, auto_tune=False)

        result = self.model.compress(input_path, self.output_pdf, settings)

        self.assertFalse(result.reached_target)
        self.assertEqual(len(result.attempts), 1)

    def test_cancel_event_stops_before_writing_output(self) -> None:
        input_path = self.input_pdf([(800, 600)])
        cancel_event = threading.Event()
        cancel_event.set()

        result = self.model.compress(
            input_path, self.output_pdf, CompressionSettings(), cancel_event=cancel_event
        )

        self.assertFalse(result.success)
        self.assertEqual(result.final_size, 0)
        self.assertIn("取消", result.message)
        self.assertFalse(os.path.exists(self.output_pdf))


if __name__ == "__main__":
    unittest.main()
