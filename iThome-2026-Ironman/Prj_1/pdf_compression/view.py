"""GUI 畫面（View）。只負責顯示與使用者輸入，不含任何壓縮邏輯。"""

from __future__ import annotations

import ctypes
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Callable, Optional

import ttkbootstrap as ttk
from ttkbootstrap.constants import BOTH, HORIZONTAL, LEFT, RIGHT, X, YES

# flatly：沿用既有主題，但版面全面改用其 info（藍色）作為強調色，取代原本純表單感的預設樣式。
THEME = "flatly"
ACCENT = "info"
FONT_FAMILY = "Microsoft JhengHei UI"
ICON_FILE = "pdf_compression.ico"
# Windows 依 AppUserModelID 把視窗歸到工作列圖示；不設會沿用 Python 直譯器的圖示。
APP_USER_MODEL_ID = "AlexYu.PdfCompression"


def resource_path(relative: str) -> str:
    """取得資源檔的實際路徑。PyInstaller onefile 會把 datas 解壓到 sys._MEIPASS。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


class PdfCompressorView:
    def __init__(self) -> None:
        self._set_app_user_model_id()
        self.root = ttk.Window(themename=THEME, title="PDF 壓縮工具")
        self._apply_icon()
        self._apply_geometry()
        # 卡片版面比原本的表單排版更需要垂直空間；允許縮放並設下限，避免在較矮的螢幕上被裁切。
        self.root.resizable(True, True)
        self.root.minsize(720, 640)

        self.input_path_var = tk.StringVar()
        self.output_dir_var = tk.StringVar()
        self.output_name_var = tk.StringVar()
        self.target_size_var = tk.StringVar()
        self.auto_tune_var = tk.BooleanVar(value=True)
        self.scale_var = tk.DoubleVar(value=0.75)
        self.quality_var = tk.IntVar(value=78)
        self.min_dim_var = tk.IntVar(value=200)
        self.status_var = tk.StringVar(value="請選擇輸入檔案。")
        self.progress_var = tk.DoubleVar(value=0.0)

        self._on_browse_input: Optional[Callable[[], None]] = None
        self._on_browse_output_dir: Optional[Callable[[], None]] = None
        self._on_start: Optional[Callable[[], None]] = None
        self._on_close: Optional[Callable[[], None]] = None

        self._build_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self._handle_close)

    # ------------------------------------------------------------------ #
    # 應用程式圖示（標題列 + 工作列）
    # ------------------------------------------------------------------ #
    @staticmethod
    def _set_app_user_model_id() -> None:
        # 必須在建立 root 視窗前呼叫才會生效；非 Windows 平台沒有這支 API。
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except (AttributeError, OSError):
            pass

    def _apply_icon(self) -> None:
        try:
            self.root.iconbitmap(resource_path(ICON_FILE))
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ #
    # 視窗尺寸：左右 3%~50%、上下 3%~87% 螢幕大小
    # ------------------------------------------------------------------ #
    def _apply_geometry(self) -> None:
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = int(sw * 0.03)
        y = int(sh * 0.03)
        width = int(sw * 0.50) - x
        height = int(sh * 0.87) - y
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    # ------------------------------------------------------------------ #
    # 版面配置
    # ------------------------------------------------------------------ #
    def _build_widgets(self) -> None:
        style = ttk.Style()
        style.configure(".", font=(FONT_FAMILY, 10))
        style.configure("TLabelframe.Label", font=(FONT_FAMILY, 11, "bold"))
        style.configure(f"{ACCENT}.TButton", font=(FONT_FAMILY, 12, "bold"))

        outer = ttk.Frame(self.root, padding=(20, 16, 20, 14))
        outer.pack(fill=BOTH, expand=YES)

        # -------------------------------------------------------------- #
        # 標題區
        # -------------------------------------------------------------- #
        header = ttk.Frame(outer)
        header.pack(fill=X, pady=(0, 12))
        ttk.Label(header, text="PDF 壓縮工具", font=(FONT_FAMILY, 18, "bold")).pack(anchor="w")
        ttk.Label(
            header, text="批次壓縮 PDF 內嵌圖片，快速縮小檔案體積", bootstyle="secondary", font=(FONT_FAMILY, 10),
        ).pack(anchor="w", pady=(2, 0))

        # -------------------------------------------------------------- #
        # 輸入與輸出
        # -------------------------------------------------------------- #
        io_frame = ttk.Labelframe(outer, text="輸入與輸出", bootstyle=ACCENT, padding=(14, 10))
        io_frame.pack(fill=X, pady=(0, 10))
        io_frame.columnconfigure(1, weight=1)

        ttk.Button(
            io_frame, text="輸入檔案", bootstyle=f"{ACCENT}-outline", width=12, command=self._handle_browse_input,
        ).grid(row=0, column=0, sticky="w")
        ttk.Entry(io_frame, textvariable=self.input_path_var, state="readonly").grid(
            row=0, column=1, sticky="ew", padx=(10, 0), ipady=2
        )

        ttk.Button(
            io_frame, text="輸出資料夾", bootstyle=f"{ACCENT}-outline", width=12, command=self._handle_browse_output_dir,
        ).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(io_frame, textvariable=self.output_dir_var, state="readonly").grid(
            row=1, column=1, sticky="ew", padx=(10, 0), pady=(8, 0), ipady=2
        )

        ttk.Label(io_frame, text="輸出檔名", width=12).grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(io_frame, textvariable=self.output_name_var).grid(
            row=2, column=1, sticky="ew", padx=(10, 0), pady=(8, 0), ipady=2
        )

        # -------------------------------------------------------------- #
        # 壓縮設定
        # -------------------------------------------------------------- #
        settings_frame = ttk.Labelframe(outer, text="壓縮設定", bootstyle=ACCENT, padding=(14, 10))
        settings_frame.pack(fill=X, pady=(0, 10))

        target_row = ttk.Frame(settings_frame)
        target_row.pack(fill=X)
        target_col = ttk.Frame(target_row)
        target_col.pack(side=LEFT)
        ttk.Label(target_col, text="目標檔案大小 (MB，留空=不限制)", bootstyle="secondary").pack(anchor="w")
        ttk.Entry(target_col, textvariable=self.target_size_var, width=10).pack(anchor="w", pady=(4, 0), ipady=2)

        toggle_col = ttk.Frame(target_row)
        toggle_col.pack(side=LEFT, padx=(28, 0), fill=X, expand=YES)
        ttk.Checkbutton(
            toggle_col, text="超過目標時自動加強壓縮", variable=self.auto_tune_var,
            bootstyle=f"{ACCENT}-round-toggle",
        ).pack(anchor="w")
        ttk.Label(
            toggle_col, text="若壓縮後仍超過目標大小，將逐步加大壓縮強度，直到符合限制或達到上限。",
            bootstyle="secondary", font=(FONT_FAMILY, 9), wraplength=340, justify="left",
        ).pack(anchor="w", pady=(2, 0))

        ttk.Separator(settings_frame).pack(fill=X, pady=10)

        scale_row = ttk.Frame(settings_frame)
        scale_row.pack(fill=X, pady=(0, 2))
        ttk.Label(scale_row, text="圖片縮放比例", font=(FONT_FAMILY, 10, "bold")).pack(side=LEFT)
        self.scale_value_label = ttk.Label(
            scale_row, text="0.75", width=5, anchor="center", bootstyle=f"{ACCENT}-inverse", font=(FONT_FAMILY, 9, "bold"),
        )
        self.scale_value_label.pack(side=RIGHT, ipady=2)
        ttk.Scale(
            settings_frame, from_=0.3, to=1.0, orient=HORIZONTAL, variable=self.scale_var, bootstyle=ACCENT,
            command=lambda v: self.scale_value_label.configure(text=f"{float(v):.2f}"),
        ).pack(fill=X, pady=(0, 8))

        quality_row = ttk.Frame(settings_frame)
        quality_row.pack(fill=X, pady=(0, 2))
        ttk.Label(quality_row, text="JPEG 品質", font=(FONT_FAMILY, 10, "bold")).pack(side=LEFT)
        self.quality_value_label = ttk.Label(
            quality_row, text="78", width=5, anchor="center", bootstyle=f"{ACCENT}-inverse", font=(FONT_FAMILY, 9, "bold"),
        )
        self.quality_value_label.pack(side=RIGHT, ipady=2)
        ttk.Scale(
            settings_frame, from_=35, to=95, orient=HORIZONTAL, variable=self.quality_var, bootstyle=ACCENT,
            command=lambda v: self.quality_value_label.configure(text=f"{int(float(v))}"),
        ).pack(fill=X, pady=(0, 8))

        min_dim_row = ttk.Frame(settings_frame)
        min_dim_row.pack(fill=X)
        min_dim_text = ttk.Frame(min_dim_row)
        min_dim_text.pack(side=LEFT, fill=X, expand=YES)
        ttk.Label(min_dim_text, text="最小圖片邊長 (px)", font=(FONT_FAMILY, 10, "bold")).pack(anchor="w")
        ttk.Label(
            min_dim_text, text="小於此邊長的圖片視為圖示或標誌，不進行壓縮",
            bootstyle="secondary", font=(FONT_FAMILY, 9),
        ).pack(anchor="w", pady=(2, 0))
        ttk.Spinbox(min_dim_row, from_=0, to=2000, textvariable=self.min_dim_var, width=8).pack(side=RIGHT)

        # -------------------------------------------------------------- #
        # 開始轉換
        # -------------------------------------------------------------- #
        self.start_button = ttk.Button(
            outer, text="開始轉換", bootstyle=ACCENT, command=self._handle_start,
        )
        self.start_button.pack(fill=X, ipady=6, pady=(0, 10))

        # -------------------------------------------------------------- #
        # 進度與狀態
        # -------------------------------------------------------------- #
        progress_frame = ttk.Frame(outer)
        progress_frame.pack(fill=X, pady=(0, 10))
        self.progressbar = ttk.Progressbar(
            progress_frame, variable=self.progress_var, maximum=100, bootstyle=f"{ACCENT}-striped",
        )
        self.progressbar.pack(fill=X)
        status_row = ttk.Frame(progress_frame)
        status_row.pack(fill=X, pady=(6, 0))
        ttk.Label(status_row, textvariable=self.status_var, bootstyle="secondary").pack(side=LEFT)
        self.percent_label = ttk.Label(status_row, text="", bootstyle=ACCENT, font=(FONT_FAMILY, 9, "bold"))
        self.percent_label.pack(side=RIGHT)

        # -------------------------------------------------------------- #
        # 轉換紀錄
        # -------------------------------------------------------------- #
        log_frame = ttk.Labelframe(outer, text="轉換紀錄", bootstyle=ACCENT, padding=(14, 10))
        log_frame.pack(fill=BOTH, expand=YES)
        self.log_text = tk.Text(
            log_frame, height=6, state="disabled", wrap="word", font=("Consolas", 10),
            background="#FAFBFC", foreground="#3D4257", relief="flat",
            highlightthickness=1, highlightbackground="#E3E5EC", highlightcolor="#E3E5EC",
            padx=10, pady=8,
        )
        self.log_text.pack(fill=BOTH, expand=YES)

    # ------------------------------------------------------------------ #
    # 事件綁定（由 Presenter 呼叫）
    # ------------------------------------------------------------------ #
    def bind_browse_input(self, callback: Callable[[], None]) -> None:
        self._on_browse_input = callback

    def bind_browse_output_dir(self, callback: Callable[[], None]) -> None:
        self._on_browse_output_dir = callback

    def bind_start(self, callback: Callable[[], None]) -> None:
        self._on_start = callback

    def bind_close(self, callback: Callable[[], None]) -> None:
        self._on_close = callback

    def _handle_browse_input(self) -> None:
        if self._on_browse_input:
            self._on_browse_input()

    def _handle_browse_output_dir(self) -> None:
        if self._on_browse_output_dir:
            self._on_browse_output_dir()

    def _handle_start(self) -> None:
        if self._on_start:
            self._on_start()

    def _handle_close(self) -> None:
        if self._on_close:
            self._on_close()
        else:
            self.root.destroy()

    # ------------------------------------------------------------------ #
    # 對話框（原生 OS 對話框）
    # ------------------------------------------------------------------ #
    def ask_open_pdf(self) -> Optional[str]:
        path = filedialog.askopenfilename(title="選擇輸入 PDF 檔案", filetypes=[("PDF 檔案", "*.pdf")])
        return path or None

    def ask_directory(self, initial: Optional[str] = None) -> Optional[str]:
        path = filedialog.askdirectory(title="選擇輸出資料夾", initialdir=initial or None)
        return path or None

    def confirm(self, title: str, message: str) -> bool:
        return messagebox.askyesno(title, message, parent=self.root)

    def show_info(self, title: str, message: str) -> None:
        messagebox.showinfo(title, message, parent=self.root)

    def show_warning(self, title: str, message: str) -> None:
        messagebox.showwarning(title, message, parent=self.root)

    def show_error(self, title: str, message: str) -> None:
        messagebox.showerror(title, message, parent=self.root)

    # ------------------------------------------------------------------ #
    # 取值 / 設值
    # ------------------------------------------------------------------ #
    def get_input_path(self) -> str:
        return self.input_path_var.get().strip()

    def set_input_path(self, path: str) -> None:
        self.input_path_var.set(path)

    def get_output_dir(self) -> str:
        return self.output_dir_var.get().strip()

    def set_output_dir(self, path: str) -> None:
        self.output_dir_var.set(path)

    def get_output_filename(self) -> str:
        return self.output_name_var.get().strip()

    def set_output_filename(self, name: str) -> None:
        self.output_name_var.set(name)

    def get_target_size_mb_text(self) -> str:
        return self.target_size_var.get().strip()

    def get_auto_tune(self) -> bool:
        return bool(self.auto_tune_var.get())

    def get_scale(self) -> float:
        return round(float(self.scale_var.get()), 2)

    def get_quality(self) -> int:
        return int(self.quality_var.get())

    def get_min_dim(self) -> int:
        return int(self.min_dim_var.get())

    # ------------------------------------------------------------------ #
    # 執行狀態顯示
    # ------------------------------------------------------------------ #
    def set_progress(self, current: int, total: int) -> None:
        percent = (current / total * 100) if total else 0
        self.progress_var.set(percent)
        self.percent_label.configure(text=f"{percent:.0f}%")

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.start_button.configure(state=state)
        if running:
            self.progress_var.set(0)
            self.percent_label.configure(text="0%")

    # ------------------------------------------------------------------ #
    # after() 排程包裝（供 Presenter 輪詢背景執行緒佇列）
    # ------------------------------------------------------------------ #
    def schedule(self, delay_ms: int, callback: Callable[[], None]) -> str:
        return self.root.after(delay_ms, callback)

    def cancel_scheduled(self, after_id: Optional[str]) -> None:
        if after_id:
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass

    def destroy(self) -> None:
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
