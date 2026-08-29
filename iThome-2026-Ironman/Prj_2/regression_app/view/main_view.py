"""主視窗。

被動 View（passive view）：所有事件都轉給 Presenter 指定的 callback，
自己不做判斷、不碰檔案、不知道分析怎麼跑。
"""

from __future__ import annotations

import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import ttkbootstrap as ttkb
from ttkbootstrap.scrolled import ScrolledText

from regression_app.model.schema import ColumnSpec
from regression_app.paths import resource_path
from regression_app.version import APP_NAME, APP_VERSION

THEME = "cosmo"
UI_FONT = ("Microsoft JhengHei UI", 10)
LOG_FONT = ("Consolas", 10)

CHECKED = "☑"
UNCHECKED = "☐"

# 視窗佔螢幕的比例：水平 10%～90%、垂直 3%～87%。
_LEFT, _RIGHT = 0.10, 0.90
_TOP, _BOTTOM = 0.03, 0.87


class MainView:
    """主視窗的所有 widget 與對外介面。"""

    def __init__(self) -> None:
        # iconphoto=None 一定要傳：ttkbootstrap 預設會用自己的 logo 蓋掉 iconbitmap。
        self.root = ttkb.Window(themename=THEME, iconphoto=None)
        self.root.title(f"{APP_NAME}　v{APP_VERSION}")
        self._apply_geometry()
        self._apply_icon()
        self._apply_fonts()

        # Presenter 會覆寫這些；預設為 no-op，View 自己單獨跑也不會爆。
        self.on_browse_input: Callable[[str], None] = lambda path: None
        self.on_browse_output: Callable[[str], None] = lambda path: None
        self.on_start: Callable[[], None] = lambda: None
        self.on_stop: Callable[[], None] = lambda: None
        self.on_close_request: Callable[[], None] = lambda: None
        self.on_selection_changed: Callable[[], None] = lambda: None

        self._check_state: dict[str, bool] = {}
        self._progress_running = False

        self._build()
        self.root.protocol("WM_DELETE_WINDOW", lambda: self.on_close_request())

    # ------------------------------------------------------------------
    # 視窗基礎
    # ------------------------------------------------------------------

    def _apply_geometry(self) -> None:
        """讓「看得見的視窗」佔螢幕水平 10%～90%、垂直 3%～87%。

        直接把比例丟給 geometry() 會偏掉兩次：geometry() 設的是內容區，
        Windows 會再加上標題列（約 31px）；而視窗四周還有一圈約 8px 的隱形
        縮放邊框，也不算在肉眼看到的範圍裡。
        所以先擺一次、量出實際可見範圍，再用差額校正一次。
        """
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        target_x = int(screen_w * _LEFT)
        target_y = int(screen_h * _TOP)
        target_w = int(screen_w * (_RIGHT - _LEFT))
        target_h = int(screen_h * (_BOTTOM - _TOP))

        self.root.geometry(f"{target_w}x{target_h}+{target_x}+{target_y}")
        self.root.update_idletasks()

        visible = self._visible_rect()
        if visible is not None:
            vx, vy, vw, vh = visible
            self.root.geometry(
                f"{self.root.winfo_width() + (target_w - vw)}"
                f"x{self.root.winfo_height() + (target_h - vh)}"
                f"+{target_x + (target_x - vx)}+{target_y + (target_y - vy)}"
            )
        else:
            # 量不到可見範圍（非 Windows，或 DWM 不給）就只扣標題列，至少不會過高。
            title_bar = self.root.winfo_rooty() - self.root.winfo_y()
            if title_bar > 0:
                self.root.geometry(f"{target_w}x{target_h - title_bar}+{target_x}+{target_y}")

        # 再小下去分析紀錄就會被上面三個區塊擠到看不見。
        self.root.minsize(1000, 780)

    def _visible_rect(self) -> tuple[int, int, int, int] | None:
        """向 DWM 問這個視窗肉眼看得到的範圍，回傳 (x, y, w, h)。"""
        if sys.platform != "win32":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            DWMWA_EXTENDED_FRAME_BOUNDS = 9
            hwnd = int(self.root.wm_frame(), 16)
            rect = wintypes.RECT()
            status = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                wintypes.HWND(hwnd), ctypes.c_uint(DWMWA_EXTENDED_FRAME_BOUNDS),
                ctypes.byref(rect), ctypes.sizeof(rect),
            )
            if status != 0:
                return None
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        except Exception:
            return None

    def _apply_icon(self) -> None:
        icon = resource_path("app.ico")
        if icon.is_file():
            try:
                self.root.iconbitmap(str(icon))
            except tk.TclError:
                pass  # 圖示壞掉不該讓程式開不起來

    def _apply_fonts(self) -> None:
        style = self.root.style
        style.configure(".", font=UI_FONT)
        style.configure("Treeview", font=UI_FONT, rowheight=26)
        style.configure("Treeview.Heading", font=(UI_FONT[0], UI_FONT[1], "bold"))
        style.configure("Run.TButton", font=(UI_FONT[0], 12, "bold"))

    # ------------------------------------------------------------------
    # 版面
    # ------------------------------------------------------------------

    def _build(self) -> None:
        outer = ttkb.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        # pack 的順序就是分配空間的順序，不是畫面上下的順序。
        # 分析紀錄與執行列先從底部 pack，確保它們拿得到高度；
        # 最後才 pack 的「分析欄位」設 expand=True，由它吸收剩下的空間。
        # 反過來寫的話，視窗一矮下來被壓扁的就會是紀錄區和按鈕列。
        self._build_log(outer)      # 貼底
        self._build_run(outer)      # 貼在紀錄區上方
        self._build_source(outer)
        self._build_output(outer)
        self._build_columns(outer)  # 吸收剩餘空間

    def _build_source(self, parent) -> None:
        frame = ttkb.Labelframe(parent, text=" 1. 資料來源 ", padding=10)
        frame.pack(fill="x", pady=(0, 8))
        frame.columnconfigure(1, weight=1)

        ttkb.Label(frame, text="輸入 Excel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.var_input = tk.StringVar(value="")
        self.entry_input = ttkb.Entry(frame, textvariable=self.var_input, state="readonly")
        self.entry_input.grid(row=0, column=1, sticky="ew")
        self.btn_browse_input = ttkb.Button(
            frame, text="瀏覽…", bootstyle="primary", width=10, command=self._browse_input
        )
        self.btn_browse_input.grid(row=0, column=2, padx=(8, 0))

        self.banner = ttkb.Label(
            frame,
            text="請選擇符合樣板格式的 Excel（需含 Definition 與 Data 兩張工作表）",
            bootstyle="secondary",
            anchor="w",
            justify="left",
            padding=(10, 8),
        )
        self.banner.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(10, 0))

    def _build_output(self, parent) -> None:
        frame = ttkb.Labelframe(parent, text=" 2. 輸出設定 ", padding=10)
        frame.pack(fill="x", pady=(0, 8))
        frame.columnconfigure(1, weight=1)

        ttkb.Label(frame, text="輸出目錄").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.var_output_dir = tk.StringVar(value="")
        self.entry_output_dir = ttkb.Entry(frame, textvariable=self.var_output_dir)
        self.entry_output_dir.grid(row=0, column=1, sticky="ew")
        self.btn_browse_output = ttkb.Button(
            frame, text="瀏覽…", bootstyle="secondary", width=10, command=self._browse_output
        )
        self.btn_browse_output.grid(row=0, column=2, padx=(8, 0))

        ttkb.Label(frame, text="資料夾名稱").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        self.var_folder = tk.StringVar(value="")
        self.entry_folder = ttkb.Entry(frame, textvariable=self.var_folder)
        self.entry_folder.grid(row=1, column=1, sticky="ew", pady=(8, 0))
        self.btn_reset_folder = ttkb.Button(
            frame, text="還原預設", bootstyle="secondary-outline", width=10, command=self.reset_folder_name
        )
        self.btn_reset_folder.grid(row=1, column=2, padx=(8, 0), pady=(8, 0))

        self.label_full_path = ttkb.Label(frame, text="實際輸出至　—", bootstyle="secondary")
        self.label_full_path.grid(row=2, column=1, columnspan=2, sticky="w", pady=(6, 0))

        self.var_output_dir.trace_add("write", lambda *_: self._refresh_full_path())
        self.var_folder.trace_add("write", lambda *_: self._refresh_full_path())

    def _build_columns(self, parent) -> None:
        # 固定高度，剩餘空間留給分析紀錄 —— 表格有捲軸，紀錄沒有多的行可看。
        frame = ttkb.Labelframe(parent, text=" 3. 分析欄位 ", padding=10)
        frame.pack(fill="x", pady=(0, 8))
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1, uniform="cols")
        frame.columnconfigure(1, weight=1, uniform="cols")

        self.tree_input, self.count_input = self._build_column_panel(frame, 0, "輸入變項　Input", "input")
        self.tree_result, self.count_result = self._build_column_panel(frame, 1, "結果變項　Result", "result")

    def _build_column_panel(self, parent, column: int, title: str, kind: str):
        holder = ttkb.Frame(parent)
        holder.grid(row=0, column=column, sticky="nsew", padx=(0, 8) if column == 0 else (8, 0))
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(1, weight=1)   # 表格列吃掉多出來的高度

        # 標題、全選鈕、已選數量擠成同一列，比各佔一列省下 30 幾 px。
        header = ttkb.Frame(holder)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttkb.Label(header, text=title, font=(UI_FONT[0], UI_FONT[1], "bold")).pack(side="left")
        ttkb.Button(header, text="全選", bootstyle="primary-outline", width=7,
                    command=lambda: self._set_all(kind, True)).pack(side="left", padx=(14, 0))
        ttkb.Button(header, text="全不選", bootstyle="secondary-outline", width=7,
                    command=lambda: self._set_all(kind, False)).pack(side="left", padx=(6, 0))
        count = ttkb.Label(header, text="已選 0 ／ 0", bootstyle="secondary")
        count.pack(side="right")

        tree = ttkb.Treeview(holder, columns=("check", "name", "type", "note"), show="headings", height=5)
        tree.heading("check", text="")
        tree.heading("name", text="欄位")
        tree.heading("type", text="類型")
        tree.heading("note", text="備註")
        tree.column("check", width=42, anchor="center", stretch=False)
        tree.column("name", width=150, anchor="w", stretch=False)
        tree.column("type", width=70, anchor="center", stretch=False)
        tree.column("note", width=200, anchor="w")
        tree.grid(row=1, column=0, sticky="nsew", pady=(6, 0))

        scroll = ttkb.Scrollbar(holder, orient="vertical", command=tree.yview)
        scroll.grid(row=1, column=1, sticky="ns", pady=(6, 0))
        tree.configure(yscrollcommand=scroll.set)

        tree.bind("<Button-1>", self._on_tree_click)
        tree.bind("<space>", self._on_tree_space)

        setattr(self, f"_panel_buttons_{kind}", header)
        return tree, count

    def _build_run(self, parent) -> None:
        frame = ttkb.Frame(parent)
        frame.pack(side="bottom", fill="x", pady=(8, 8))

        self.btn_start = ttkb.Button(
            frame, text="▶　開始分析", bootstyle="primary", style="Run.TButton",
            width=16, command=lambda: self.on_start(), state="disabled",
        )
        self.btn_start.pack(side="left", ipady=6)

        self.btn_stop = ttkb.Button(
            frame, text="■　停止計算", bootstyle="danger", width=14,
            command=lambda: self.on_stop(), state="disabled",
        )
        self.btn_stop.pack(side="left", padx=(10, 0), ipady=6)

        # 紀錄區的兩顆按鈕擺在這一列，省下紀錄框上方一整列的高度。
        self.btn_clear_log = ttkb.Button(frame, text="清除紀錄", bootstyle="secondary-outline", width=10,
                                         command=self.clear_log)
        self.btn_clear_log.pack(side="right", padx=(6, 0))
        self.btn_save_log = ttkb.Button(frame, text="另存為 .log", bootstyle="secondary-outline", width=12,
                                        command=self._save_log)
        self.btn_save_log.pack(side="right", padx=(10, 0))

        self.label_stage = ttkb.Label(frame, text="請先選擇檔案", bootstyle="secondary", width=22, anchor="e")
        self.label_stage.pack(side="right", padx=(10, 0))

        self.progress = ttkb.Progressbar(frame, mode="indeterminate", bootstyle="primary-striped")
        self.progress.pack(side="left", fill="x", expand=True, padx=(14, 0))

    def _build_log(self, parent) -> None:
        frame = ttkb.Labelframe(parent, text=" 分析紀錄 ", padding=10)
        frame.pack(side="bottom", fill="both", expand=True)

        self.log = ScrolledText(frame, autohide=True, font=LOG_FONT, height=7, wrap="word")
        self.log.pack(fill="both", expand=True)
        self.log.text.configure(state="disabled")

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------

    def _browse_input(self) -> None:
        path = filedialog.askopenfilename(
            title="選擇輸入 Excel",
            filetypes=[("Excel 活頁簿", "*.xlsx *.xlsm"), ("所有檔案", "*.*")],
            parent=self.root,
        )
        if path:
            self.on_browse_input(path)

    def _browse_output(self) -> None:
        path = filedialog.askdirectory(title="選擇輸出目錄", parent=self.root)
        if path:
            self.on_browse_output(path)

    def _on_tree_click(self, event) -> str | None:
        """只有點在勾選欄才切換，避免點欄位名稱時誤觸。"""
        tree = event.widget
        if tree.identify_region(event.x, event.y) != "cell":
            return None
        if tree.identify_column(event.x) != "#1":
            return None
        item = tree.identify_row(event.y)
        if item:
            self._toggle(tree, item)
        return "break"

    def _on_tree_space(self, event) -> str:
        tree = event.widget
        for item in tree.selection():
            self._toggle(tree, item)
        return "break"

    def _toggle(self, tree, item: str) -> None:
        if str(self.btn_start["state"]) == "disabled" and self._progress_running:
            return  # 執行中不接受修改
        self._check_state[item] = not self._check_state.get(item, True)
        tree.set(item, "check", CHECKED if self._check_state[item] else UNCHECKED)
        self._refresh_counts()
        self.on_selection_changed()

    def _set_all(self, kind: str, value: bool) -> None:
        tree = self.tree_input if kind == "input" else self.tree_result
        for item in tree.get_children():
            self._check_state[item] = value
            tree.set(item, "check", CHECKED if value else UNCHECKED)
        self._refresh_counts()
        self.on_selection_changed()

    def _save_log(self) -> None:
        path = filedialog.asksaveasfilename(
            title="另存分析紀錄", defaultextension=".log",
            initialfile=f"analysis_{datetime.now():%Y-%m-%d_%H%M%S}.log",
            filetypes=[("記錄檔", "*.log"), ("文字檔", "*.txt")], parent=self.root,
        )
        if not path:
            return
        Path(path).write_text(self.log.text.get("1.0", "end-1c"), encoding="utf-8")
        self.append_log(f"分析紀錄已另存至 {path}")

    # ------------------------------------------------------------------
    # Presenter 呼叫的介面
    # ------------------------------------------------------------------

    def set_input_path(self, path: str) -> None:
        self.var_input.set(path)

    def set_banner(self, level: str, text: str) -> None:
        """level: ok / error / info。"""
        style = {"ok": "success", "error": "danger", "info": "secondary"}.get(level, "secondary")
        self.banner.configure(text=text, bootstyle=f"{style}-inverse" if level != "info" else "secondary")

    def set_output_dir(self, path: str) -> None:
        self.var_output_dir.set(path)

    def get_output_dir(self) -> str:
        return self.var_output_dir.get().strip()

    def set_folder_name(self, name: str) -> None:
        self.var_folder.set(name)

    def get_folder_name(self) -> str:
        return self.var_folder.get().strip()

    def reset_folder_name(self) -> None:
        """由 Presenter 覆寫成真正的重設邏輯；預設不做事。"""

    def _refresh_full_path(self) -> None:
        directory, name = self.get_output_dir(), self.get_folder_name()
        self.label_full_path.configure(
            text=f"實際輸出至　{Path(directory) / name}" if directory and name else "實際輸出至　—"
        )

    def populate_columns(self, inputs: list[ColumnSpec], results: list[ColumnSpec]) -> None:
        self._check_state.clear()
        for tree, specs in ((self.tree_input, inputs), (self.tree_result, results)):
            tree.delete(*tree.get_children())
            for spec in specs:
                item = tree.insert(
                    "", "end",
                    values=(CHECKED, spec.name, _type_label(spec.data_type), spec.note or "—"),
                )
                self._check_state[item] = True
        self._refresh_counts()

    def clear_columns(self) -> None:
        self._check_state.clear()
        for tree in (self.tree_input, self.tree_result):
            tree.delete(*tree.get_children())
        self._refresh_counts()

    def selected_columns(self, kind: str) -> list[str]:
        tree = self.tree_input if kind == "input" else self.tree_result
        return [tree.set(i, "name") for i in tree.get_children() if self._check_state.get(i, False)]

    def _refresh_counts(self) -> None:
        for tree, label in ((self.tree_input, self.count_input), (self.tree_result, self.count_result)):
            items = tree.get_children()
            chosen = sum(1 for i in items if self._check_state.get(i, False))
            label.configure(text=f"已選 {chosen} ／ {len(items)}")

    def set_controls_enabled(self, enabled: bool) -> None:
        """執行中把所有輸入與按鈕鎖住，只留「停止計算」。"""
        state = "normal" if enabled else "disabled"
        for widget in (
            self.btn_browse_input, self.btn_browse_output, self.btn_reset_folder,
            self.entry_output_dir, self.entry_folder, self.btn_clear_log, self.btn_save_log,
        ):
            widget.configure(state=state)
        for kind in ("input", "result"):
            for child in getattr(self, f"_panel_buttons_{kind}").winfo_children():
                if isinstance(child, ttkb.Button):
                    child.configure(state=state)

    def set_running(self, running: bool, can_start: bool = False) -> None:
        self._progress_running = running
        self.set_controls_enabled(not running)
        self.btn_start.configure(
            state="disabled" if running or not can_start else "normal",
            text="分析中…" if running else "▶　開始分析",
        )
        self.btn_stop.configure(state="normal" if running else "disabled")
        if running:
            self.progress.start(12)
        else:
            self.progress.stop()

    def set_start_enabled(self, enabled: bool) -> None:
        if not self._progress_running:
            self.btn_start.configure(state="normal" if enabled else "disabled")

    def set_stop_enabled(self, enabled: bool) -> None:
        self.btn_stop.configure(state="normal" if enabled else "disabled")

    def set_stage(self, text: str) -> None:
        self.label_stage.configure(text=text)

    def append_log(self, message: str) -> None:
        self.log.text.configure(state="normal")
        self.log.text.insert("end", f"{datetime.now():%H:%M:%S}  {message}\n")
        self.log.text.see("end")
        self.log.text.configure(state="disabled")

    def clear_log(self) -> None:
        self.log.text.configure(state="normal")
        self.log.text.delete("1.0", "end")
        self.log.text.configure(state="disabled")

    def ask_yes_no(self, title: str, message: str) -> bool:
        return messagebox.askyesno(title, message, parent=self.root, icon="warning")

    def show_error(self, title: str, message: str) -> None:
        messagebox.showerror(title, message, parent=self.root)

    def show_info(self, title: str, message: str) -> None:
        messagebox.showinfo(title, message, parent=self.root)


def _type_label(data_type: str) -> str:
    return {"Continuous": "連續", "Categorical": "類別", "None": "—"}.get(data_type, data_type)
