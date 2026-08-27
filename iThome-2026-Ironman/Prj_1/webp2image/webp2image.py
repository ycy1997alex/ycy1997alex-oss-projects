"""webp2image — 將 .webp 批次轉換為常見圖片格式（預設 PNG）。

採用 MVP（Model-View-Presenter）架構，三層都放在這個檔案裡，彼此以明確邊界隔開：

  Model     ConverterModel      純轉檔邏輯，完全不 import tkinter
  View      MainView            ttkbootstrap 視窗，被動顯示，不含任何商業邏輯
  Presenter ConverterPresenter  接收 View 事件、呼叫 Model、把結果推回 View

View 與 Model 之間沒有任何直接依賴，所有互動都經過 Presenter。
背景執行緒不直接碰 widget，一律把工作丟進 queue，由 UI 執行緒輪詢後執行。
"""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable, Iterable, Sequence

import ttkbootstrap as tb
from PIL import Image

APP_NAME = "WebP 轉圖片"
APP_VERSION = "1"

# Windows 工作列會以 AppUserModelID 分群，不設定的話會顯示 Python 直譯器的圖示
APP_USER_MODEL_ID = "webp2image.desktop.1"

THEME_NAME = "bootstrap-light"
ICON_FILENAME = "webp2image_icon.ico"

# 視窗尺寸：詳細記錄收起／展開時的高度比例（寬度固定），實際像素在執行時依螢幕解析度換算
# 展開高度 = 螢幕可用高度上限；收起／最小高度依原設計比例（540/720、460/540）換算
WINDOW_HEIGHT_COLLAPSED_RATIO = 540 / 720
WINDOW_MIN_HEIGHT_RATIO = 460 / 540

# UI 執行緒輪詢 queue 的間隔（毫秒）
UI_POLL_MS = 50
# 關閉視窗時等待背景執行緒收手的上限（秒）
WORKER_JOIN_TIMEOUT = 2.0

# JPEG 是破壞性壓縮，95 是「肉眼幾乎無損」與檔案大小的常見折衷點
JPEG_QUALITY = 95


def resource_path(relative: str) -> Path:
    """回傳資源檔的實際路徑。

    PyInstaller onefile 執行時會把打包資源解壓到暫存目錄（sys._MEIPASS），
    直接用相對路徑會找不到檔案，所以必須經過這層轉換。
    """
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / relative


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ConversionResult:
    """單一檔案的轉換結果。status 只會是 ok / skipped / failed。"""

    source: Path
    status: str
    target: Path | None = None
    message: str = ""


class ConverterModel:
    """轉檔核心。不知道 UI 的存在，可獨立測試。"""

    # 顯示名稱 -> 副檔名
    FORMATS: dict[str, str] = {
        "PNG": ".png",
        "JPEG": ".jpg",
        "BMP": ".bmp",
        "TIFF": ".tif",
    }
    DEFAULT_FORMAT = "PNG"

    # 這些格式不支援 alpha 通道，存檔前必須先把透明區域壓平成白底
    _FLATTEN_FORMATS = frozenset({"JPEG", "BMP"})

    @staticmethod
    def collect_sources(paths: Iterable[str | Path], recursive: bool) -> list[Path]:
        """把使用者選的檔案／資料夾展開成實際的 .webp 清單（去重並排序）。"""
        found: set[Path] = set()
        for raw in paths:
            path = Path(raw)
            if path.is_dir():
                candidates = path.rglob("*") if recursive else path.glob("*")
                found.update(
                    f for f in candidates
                    if f.is_file() and f.suffix.lower() == ".webp"
                )
            elif path.is_file() and path.suffix.lower() == ".webp":
                found.add(path)
        return sorted(found)

    def convert_one(
        self,
        source: Path,
        output_dir: Path | None,
        fmt: str,
        overwrite: bool,
    ) -> ConversionResult:
        """轉換單一檔案。output_dir 為 None 時輸出到原始檔所在資料夾。"""
        target_dir = output_dir if output_dir is not None else source.parent
        target = target_dir / (source.stem + self.FORMATS[fmt])

        if target.exists() and not overwrite:
            return ConversionResult(source, "skipped", target, "目標檔已存在")

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            with Image.open(source) as image:
                # 動畫 webp 由 Pillow 預設定位在第 0 幀，等同取首幀
                self._prepare(image, fmt).save(target, fmt, **self._save_options(fmt))
        except Exception as exc:  # Pillow 會丟出多種例外，一律轉成結果回報
            return ConversionResult(source, "failed", None, f"{type(exc).__name__}: {exc}")

        return ConversionResult(source, "ok", target)

    def convert_many(
        self,
        sources: Sequence[Path],
        output_dir: Path | None,
        fmt: str,
        overwrite: bool,
        on_result: Callable[[ConversionResult, int, int], None] | None = None,
        should_continue: Callable[[], bool] | None = None,
    ) -> list[ConversionResult]:
        """批次轉換。

        每完成一個檔案就呼叫 on_result(result, 已完成數, 總數)；
        should_continue() 回傳 False 時，在下一個檔案開始前中止（不會腰斬寫到一半的檔案）。
        """
        total = len(sources)
        results: list[ConversionResult] = []
        for index, source in enumerate(sources, start=1):
            if should_continue is not None and not should_continue():
                break
            result = self.convert_one(source, output_dir, fmt, overwrite)
            results.append(result)
            if on_result is not None:
                on_result(result, index, total)
        return results

    def _prepare(self, image: Image.Image, fmt: str) -> Image.Image:
        if fmt in self._FLATTEN_FORMATS:
            rgba = image.convert("RGBA")
            flattened = Image.new("RGB", rgba.size, (255, 255, 255))
            flattened.paste(rgba, mask=rgba.getchannel("A"))
            return flattened
        # 調色盤模式直接存 PNG 可能掉失透明資訊，統一轉成 RGBA
        if image.mode == "P":
            return image.convert("RGBA")
        return image

    @staticmethod
    def _save_options(fmt: str) -> dict[str, object]:
        if fmt == "JPEG":
            return {"quality": JPEG_QUALITY, "subsampling": 0}
        return {}


# --------------------------------------------------------------------------- #
# View
# --------------------------------------------------------------------------- #

@dataclass
class ViewState:
    """View 當下的輸入內容，交給 Presenter 判讀。"""

    sources: list[Path] = field(default_factory=list)
    output_dir: str = ""
    fmt: str = ConverterModel.DEFAULT_FORMAT
    overwrite: bool = False
    recursive: bool = False


class MainView(tb.Window):
    """被動視圖：只負責畫面與蒐集輸入，所有動作轉交 Presenter。"""

    # append_log() 依行首字樣決定顏色 tag；tuple 順序即比對順序
    _LOG_TAG_PREFIXES = (("ok", "[完成]"), ("fail", "[失敗]"), ("skip", "[略過]"))

    def __init__(self) -> None:
        super().__init__(themename=THEME_NAME)
        self.title(f"{APP_NAME} v{APP_VERSION}")
        self._apply_window_geometry()
        self.minsize(self._window_width, int(self._window_height_collapsed * WINDOW_MIN_HEIGHT_RATIO))

        self._presenter: "ConverterPresenter | None" = None
        self._sources: list[Path] = []
        self._log_expanded = False
        # 背景執行緒把「要在 UI 執行緒做的事」丟進來，由 _drain_queue 取出執行
        self._ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._poll_id: str | None = None

        self._apply_window_icon()
        self._build_widgets()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_id = self.after(UI_POLL_MS, self._drain_queue)

    def _apply_window_geometry(self) -> None:
        """視窗尺寸：左右 3%~50%、上下 3%~87% 螢幕大小（展開狀態即此上限，收起／最小高度依原設計比例換算）"""
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = int(sw * 0.03)
        y = int(sh * 0.03)
        self._window_width = int(sw * 0.50) - x
        self._window_height_expanded = int(sh * 0.87) - y
        self._window_height_collapsed = int(self._window_height_expanded * WINDOW_HEIGHT_COLLAPSED_RATIO)
        self._window_x = x
        self._window_y = y
        self.geometry(f"{self._window_width}x{self._window_height_collapsed}+{x}+{y}")

    # -- 給 Presenter 用的介面 ---------------------------------------------- #

    def set_presenter(self, presenter: "ConverterPresenter") -> None:
        self._presenter = presenter

    def post(self, callback: Callable[[], None]) -> None:
        """從背景執行緒排入一件要在 UI 執行緒執行的工作（thread-safe）。"""
        self._ui_queue.put(callback)

    def get_state(self) -> ViewState:
        return ViewState(
            sources=list(self._sources),
            output_dir=self._output_var.get().strip(),
            fmt=self._format_var.get(),
            overwrite=bool(self._overwrite_var.get()),
            recursive=bool(self._recursive_var.get()),
        )

    def set_sources(self, sources: Sequence[Path], summary: str) -> None:
        self._sources = list(sources)
        self._source_var.set(summary)

    def set_output_dir(self, path: str) -> None:
        self._output_var.set(path)

    def set_busy(self, busy: bool) -> None:
        self._convert_button.configure(
            state=tk.DISABLED if busy else tk.NORMAL,
            text="轉換中…" if busy else "開始轉換",
        )

    def set_progress(self, done: int, total: int) -> None:
        self._progress.configure(maximum=max(total, 1), value=done)
        self._status_var.set(f"{done} / {total}" if total else "尚未開始")

    def set_status(self, text: str) -> None:
        self._status_var.set(text)

    def clear_log(self) -> None:
        self._log.configure(state=tk.NORMAL)
        self._log.delete("1.0", tk.END)
        self._log.configure(state=tk.DISABLED)

    def append_log(self, line: str) -> None:
        tag = next((t for t, prefix in self._LOG_TAG_PREFIXES if line.startswith(prefix)), None)
        self._log.configure(state=tk.NORMAL)
        self._log.insert(tk.END, line + "\n", tag or ())
        self._log.see(tk.END)
        self._log.configure(state=tk.DISABLED)

    def ask_directory(self, title: str) -> str:
        return filedialog.askdirectory(title=title, parent=self) or ""

    def ask_files(self, title: str) -> tuple[str, ...]:
        return filedialog.askopenfilenames(
            title=title,
            parent=self,
            filetypes=[("WebP 圖片", "*.webp"), ("所有檔案", "*.*")],
        )

    def ask_yes_no(self, message: str) -> bool:
        return messagebox.askyesno(APP_NAME, message, parent=self)

    def show_error(self, message: str) -> None:
        messagebox.showerror(APP_NAME, message, parent=self)

    def show_info(self, message: str) -> None:
        messagebox.showinfo(APP_NAME, message, parent=self)

    # -- 版面 --------------------------------------------------------------- #

    def _apply_window_icon(self) -> None:
        # 圖示只影響外觀，設不起來就沿用預設，不讓它擋住程式啟動
        icon = resource_path(ICON_FILENAME)
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except Exception as exc:
                print(f"Warning: 無法設定圖示 ({exc})")
        else:
            print(f"Warning: 找不到圖示檔案 {icon}")

    def _build_widgets(self) -> None:
        self._source_var = tk.StringVar(value="尚未選擇")
        self._output_var = tk.StringVar()
        self._format_var = tk.StringVar(value=ConverterModel.DEFAULT_FORMAT)
        self._overwrite_var = tk.BooleanVar(value=False)
        self._recursive_var = tk.BooleanVar(value=False)
        self._status_var = tk.StringVar(value="尚未開始")
        self._log_toggle_var = tk.StringVar(value="▸ 顯示詳細記錄")

        colors = self.style.colors

        content = tb.Frame(self, padding=(32, 26, 32, 0))
        content.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # 標題
        header = tb.Frame(content)
        header.pack(fill=tk.X, pady=(0, 22))
        tb.Label(header, text=APP_NAME, font=("Microsoft JhengHei UI", 16, "bold")).pack(anchor=tk.W)
        tb.Label(header, text="把 .webp 批次轉成 PNG、JPEG、BMP 或 TIFF",
                 bootstyle="secondary", font=("Microsoft JhengHei UI", 9)).pack(anchor=tk.W, pady=(3, 0))

        # 來源
        source_section = self._build_section(content, "來源")
        source_row = tb.Frame(source_section)
        source_row.pack(fill=tk.X)
        tb.Entry(source_row, textvariable=self._source_var, state="readonly").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10)
        )
        tb.Button(source_row, text="選檔案", width=8, bootstyle="secondary-outline",
                  command=self._on_pick_files).pack(side=tk.LEFT)
        tb.Button(source_row, text="選資料夾", width=9, bootstyle="secondary-outline",
                  command=self._on_pick_source_dir).pack(side=tk.LEFT, padx=(8, 0))

        # 輸出
        output_section = self._build_section(content, "輸出")
        output_row = tb.Frame(output_section)
        output_row.pack(fill=tk.X)
        tb.Entry(output_row, textvariable=self._output_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10)
        )
        tb.Button(output_row, text="選資料夾", width=9, bootstyle="secondary-outline",
                  command=self._on_pick_output_dir).pack(side=tk.LEFT)
        tb.Label(output_section, text="留空則輸出到原始檔所在資料夾",
                 bootstyle="secondary", font=("Microsoft JhengHei UI", 9)).pack(anchor=tk.W, pady=(6, 0))

        # 選項
        options_section = self._build_section(content, "選項")
        options_row = tb.Frame(options_section)
        options_row.pack(fill=tk.X)
        tb.Label(options_row, text="格式").pack(side=tk.LEFT, padx=(0, 9))
        tb.Combobox(
            options_row,
            textvariable=self._format_var,
            values=list(ConverterModel.FORMATS),
            state="readonly",
            width=8,
        ).pack(side=tk.LEFT, padx=(0, 26))
        tb.Checkbutton(options_row, text="覆寫同名檔案", variable=self._overwrite_var,
                       bootstyle="round-toggle").pack(side=tk.LEFT, padx=(0, 26))
        tb.Checkbutton(options_row, text="含子資料夾", variable=self._recursive_var,
                       bootstyle="round-toggle").pack(side=tk.LEFT)

        # 底部動作列
        self._action_bar = tb.Frame(self, bootstyle="light", padding=(32, 18, 32, 16))
        self._action_bar.pack(side=tk.BOTTOM, fill=tk.X)

        button_row = tb.Frame(self._action_bar, bootstyle="light")
        button_row.pack(fill=tk.X)
        self._convert_button = tb.Button(button_row, text="開始轉換", bootstyle="primary",
                                         width=22, command=self._on_convert)
        self._convert_button.pack(anchor=tk.CENTER, ipady=4)

        progress_row = tb.Frame(self._action_bar, bootstyle="light")
        progress_row.pack(fill=tk.X, pady=(14, 0))
        self._progress = tb.Progressbar(progress_row, mode="determinate", maximum=1, value=0,
                                         bootstyle="primary")
        self._progress.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 14))
        self.style.configure(self._progress.cget("style"), thickness=6)
        tb.Label(progress_row, textvariable=self._status_var, bootstyle="light",
                 font=("Microsoft JhengHei UI", 9)).pack(side=tk.RIGHT)

        toggle_label = tb.Label(self._action_bar, textvariable=self._log_toggle_var,
                                 bootstyle="secondary", font=("Microsoft JhengHei UI", 9),
                                 cursor="hand2")
        toggle_label.pack(anchor=tk.W, pady=(10, 0))
        toggle_label.bind("<Button-1>", lambda _event: self._toggle_log())

        # 詳細記錄（預設收起，點上方文字才展開）
        self._log_frame = tb.Frame(self, padding=(32, 12, 32, 12))
        self._log = tb.ScrolledText(self._log_frame, height=10, wrap="none", state=tk.DISABLED,
                                     font=("Consolas", 9))
        self._log.pack(fill=tk.BOTH, expand=True)
        self._log.tag_configure("ok", foreground=colors.success)
        self._log.tag_configure("fail", foreground=colors.danger)
        self._log.tag_configure("skip", foreground=colors.secondary)

    def _build_section(self, parent: tk.Widget, title: str) -> tb.Frame:
        """畫一個帶標題與分隔線的區段容器，回傳給呼叫端放內容。"""
        section = tb.Frame(parent)
        section.pack(fill=tk.X, pady=(0, 22))

        header = tb.Frame(section)
        header.pack(fill=tk.X, pady=(0, 10))
        tb.Label(header, text=title, font=("Microsoft JhengHei UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 10))
        tb.Separator(header, bootstyle="secondary").pack(side=tk.LEFT, fill=tk.X, expand=True)

        return section

    def _toggle_log(self) -> None:
        self._log_expanded = not self._log_expanded
        if self._log_expanded:
            self._log_frame.pack(fill=tk.BOTH, expand=False, side=tk.BOTTOM, before=self._action_bar)
            self._log_toggle_var.set("▾ 隱藏詳細記錄")
            self.geometry(f"{self._window_width}x{self._window_height_expanded}+{self._window_x}+{self._window_y}")
        else:
            self._log_frame.pack_forget()
            self._log_toggle_var.set("▸ 顯示詳細記錄")
            self.geometry(f"{self._window_width}x{self._window_height_collapsed}+{self._window_x}+{self._window_y}")

    # -- 事件轉發（View 不做判斷，一律交給 Presenter） ----------------------- #

    def _on_pick_files(self) -> None:
        if self._presenter:
            self._presenter.on_pick_files()

    def _on_pick_source_dir(self) -> None:
        if self._presenter:
            self._presenter.on_pick_source_dir()

    def _on_pick_output_dir(self) -> None:
        if self._presenter:
            self._presenter.on_pick_output_dir()

    def _on_convert(self) -> None:
        if self._presenter:
            self._presenter.on_convert()

    # -- 生命週期 ----------------------------------------------------------- #

    def _drain_queue(self) -> None:
        while True:
            try:
                callback = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            callback()
        self._poll_id = self.after(UI_POLL_MS, self._drain_queue)

    def _on_close(self) -> None:
        # 1. 轉換進行中先問過使用者
        if self._presenter and not self._presenter.confirm_close():
            return
        # 2. 停掉輪詢，避免 destroy 之後還有 after callback 觸發
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        # 3. 通知背景執行緒收手並等待
        if self._presenter:
            self._presenter.shutdown()
        # 4. 關閉視窗
        self.destroy()


# --------------------------------------------------------------------------- #
# Presenter
# --------------------------------------------------------------------------- #

class ConverterPresenter:
    """協調者：唯一同時認識 Model 與 View 的角色。"""

    _STATUS_LABEL = {"ok": "完成", "skipped": "略過", "failed": "失敗"}

    def __init__(self, model: ConverterModel, view: MainView) -> None:
        self._model = model
        self._view = view
        self._busy = False
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        view.set_presenter(self)

    # -- View 事件 ---------------------------------------------------------- #

    def on_pick_files(self) -> None:
        selected = self._view.ask_files("選擇 .webp 檔案")
        if not selected:
            return
        paths = [Path(p) for p in selected]
        summary = str(paths[0]) if len(paths) == 1 else f"已選擇 {len(paths)} 個檔案"
        self._view.set_sources(paths, summary)

    def on_pick_source_dir(self) -> None:
        directory = self._view.ask_directory("選擇來源資料夾")
        if directory:
            self._view.set_sources([Path(directory)], directory)

    def on_pick_output_dir(self) -> None:
        directory = self._view.ask_directory("選擇輸出資料夾")
        if directory:
            self._view.set_output_dir(directory)

    def on_convert(self) -> None:
        if self._busy:
            return

        state = self._view.get_state()
        if not state.sources:
            self._view.show_error("請先選擇要轉換的 .webp 檔案或資料夾。")
            return

        sources = self._model.collect_sources(state.sources, state.recursive)
        if not sources:
            self._view.show_error("選取的位置中找不到任何 .webp 檔案。")
            return

        output_dir = Path(state.output_dir) if state.output_dir else None

        self._busy = True
        self._stop.clear()
        self._view.set_busy(True)
        self._view.clear_log()
        self._view.set_progress(0, len(sources))
        self._view.append_log(f"開始轉換 {len(sources)} 個檔案 → {state.fmt}")

        self._worker = threading.Thread(
            target=self._run_conversion,
            args=(sources, output_dir, state.fmt, state.overwrite),
            daemon=True,
        )
        self._worker.start()

    # -- 關閉流程 ----------------------------------------------------------- #

    def confirm_close(self) -> bool:
        if not self._busy:
            return True
        return self._view.ask_yes_no(
            "轉換尚未完成。關閉會停止處理剩下的檔案，已轉好的檔案會保留。確定關閉嗎？"
        )

    def shutdown(self) -> None:
        """設定停止旗標並等待背景執行緒收手；可重複呼叫。"""
        self._stop.set()
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=WORKER_JOIN_TIMEOUT)
        self._worker = None

    # -- 背景執行緒（不可直接碰 widget） ------------------------------------- #

    def _run_conversion(
        self,
        sources: Sequence[Path],
        output_dir: Path | None,
        fmt: str,
        overwrite: bool,
    ) -> None:
        try:
            results = self._model.convert_many(
                sources,
                output_dir,
                fmt,
                overwrite,
                on_result=self._report_progress,
                should_continue=lambda: not self._stop.is_set(),
            )
        except Exception as exc:  # 保險：避免背景執行緒無聲死掉、按鈕永遠卡住
            self._view.post(lambda: self._finish_with_error(exc))
            return
        cancelled = self._stop.is_set()
        self._view.post(lambda: self._finish(results, cancelled))

    def _report_progress(self, result: ConversionResult, done: int, total: int) -> None:
        label = self._STATUS_LABEL[result.status]
        detail = f"（{result.message}）" if result.message else ""
        line = f"[{label}] {result.source.name} {detail}".rstrip()
        self._view.post(lambda: self._view.append_log(line))
        self._view.post(lambda: self._view.set_progress(done, total))

    # -- 以下都在 UI 執行緒執行 --------------------------------------------- #

    def _finish(self, results: Sequence[ConversionResult], cancelled: bool) -> None:
        self._busy = False
        self._worker = None
        self._view.set_busy(False)

        counts = dict.fromkeys(self._STATUS_LABEL, 0)
        for result in results:
            counts[result.status] += 1
        summary = f"完成 {counts['ok']}、略過 {counts['skipped']}、失敗 {counts['failed']}"
        if cancelled:
            summary = "已中止：" + summary

        self._view.append_log("── " + summary)
        self._view.set_status(summary)
        self._view.show_info(summary)

    def _finish_with_error(self, exc: Exception) -> None:
        self._busy = False
        self._worker = None
        self._view.set_busy(False)
        message = f"轉換中止：{type(exc).__name__}: {exc}"
        self._view.append_log(message)
        self._view.set_status("轉換中止")
        self._view.show_error(message)


# --------------------------------------------------------------------------- #

def _set_app_user_model_id() -> None:
    """讓 Windows 工作列顯示本程式的圖示，而非 Python 直譯器的圖示。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass  # 設不起來只是圖示分群不理想，不該影響程式執行


def main() -> None:
    _set_app_user_model_id()  # 必須在建立主視窗之前呼叫
    view = MainView()
    presenter = ConverterPresenter(ConverterModel(), view)
    try:
        view.mainloop()
    finally:
        # 即使 mainloop 因未攔截的例外或 console 中斷而結束，也確保背景執行緒收到停止訊號
        presenter.shutdown()


if __name__ == "__main__":
    main()
