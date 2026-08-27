import os
import sys
import ctypes
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter import filedialog, messagebox
from PIL import Image, ImageOps, UnidentifiedImageError
from pathlib import Path

# 全域設定：定義 ICON 檔案名稱與 APP ID
APP_VERSION = "1"
ICON_NAME = "image2ico_icon.ico"
APP_ID = "prof_program.image2ico.converter.v1"  # 自定義的唯一識別碼

# 檔名中不允許出現的字元（Windows 檔案系統限制）
INVALID_NAME_CHARS = '<>:"/\\|?*'


def resource_path(relative_path):
    """
    取得資源的絕對路徑。
    用於處理 PyInstaller 打包後的路徑問題（onefile 會解壓到 sys._MEIPASS）。
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller 建立的暫存資料夾路徑
        base_path = sys._MEIPASS
    else:
        # 一般開發環境的路徑：以本檔案所在目錄為準，不受工作目錄影響
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


# ==========================================
# 1. Model: 負責資料處理與商業邏輯
# ==========================================
class IconConverterModel:
    """
    Model 層：專注於圖片處理邏輯，不接觸任何 UI 元件。
    """

    # 由小到大排列；Windows app icon 至少需要 16/32/48/256
    ICON_SIZES = ((16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256))
    TARGET_SIZE = 256

    def convert_to_ico(self, input_path: str, output_path: str):
        """
        將任意圖片轉為多尺寸 .ico。

        回傳 (success, message, notes)；notes 是給使用者看的處理說明
        （例如補了透明邊、或做了放大）。
        """
        try:
            with Image.open(input_path) as src:
                src.load()
                base, notes = self._normalize(src)
        except UnidentifiedImageError:
            return False, "無法辨識這個檔案的圖片格式。", []
        except (OSError, ValueError) as e:
            return False, f"讀取圖片失敗：{e}", []

        try:
            # 明確產生每一個尺寸的畫面，再一次寫入。
            # 不能只丟原圖給 Pillow：它會自動略過大於原圖的尺寸，
            # 也會把非正方形的來源寫成非正方形的 frame。
            frames = [base.resize(size, Image.Resampling.LANCZOS) for size in self.ICON_SIZES]
            frames[-1].save(
                output_path,
                format='ICO',
                sizes=list(self.ICON_SIZES),
                append_images=frames[:-1],
            )
        except (OSError, ValueError) as e:
            return False, f"寫入 .ico 失敗：{e}", []

        produced = self._read_back_sizes(output_path)
        expected = {size for size in self.ICON_SIZES}
        if produced != expected:
            missing = sorted(expected - produced)
            return False, f"輸出檔缺少尺寸：{missing}", notes

        size_text = "、".join(str(w) for w, _ in self.ICON_SIZES)
        message = f"成功轉換並儲存至：\n{output_path}\n\n內含尺寸：{size_text} px"
        return True, message, notes

    def _normalize(self, src: Image.Image):
        """把來源整理成一張至少 256px 的正方形 RGBA 圖，並回報做了哪些調整。"""
        notes = []

        # 相機/手機照片的 EXIF 方向標記，不處理會讓圖示轉 90 度
        img = ImageOps.exif_transpose(src) or src
        # 統一轉 RGBA：涵蓋 JPEG(RGB)、GIF/PNG 調色盤(P)、灰階(L)、CMYK
        img = img.convert("RGBA")

        width, height = img.size
        if width != height:
            side = max(width, height)
            canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            canvas.paste(img, ((side - width) // 2, (side - height) // 2))
            img = canvas
            notes.append(f"來源為 {width}×{height} 非正方形，已置中補上透明邊。")

        if img.width < self.TARGET_SIZE:
            notes.append(
                f"來源只有 {img.width}px，已放大到 {self.TARGET_SIZE}px；"
                "大尺寸圖示會比較模糊，建議改用更大的原圖。"
            )

        return img, notes

    @staticmethod
    def _read_back_sizes(path: str):
        """重新讀出剛寫好的 .ico，確認尺寸真的都在裡面。"""
        try:
            with Image.open(path) as check:
                return set(check.ico.sizes())
        except Exception:
            return set()


# ==========================================
# 2. View: 負責介面顯示 (包含圖示設定)
# ==========================================
class IconConverterView(ttk.Window):
    """
    View 層：繼承自 ttk.Window，負責 UI 建構，不含任何商業邏輯。
    """

    def __init__(self):
        super().__init__(themename="cosmo")
        self.title(f"圖片轉 ICON 工具 v{APP_VERSION}")
        self._apply_window_geometry()
        self.resizable(False, False)

        # 設定視窗圖示（方法名不可叫 _setup_icon，會與 ttkbootstrap.Window 的內部方法撞名）
        self._apply_window_icon()

        # 綁定變數
        self.input_path_var = ttk.StringVar()
        self.output_dir_var = ttk.StringVar()
        self.output_name_var = ttk.StringVar()

        self._setup_ui()

    def _apply_window_geometry(self):
        """視窗尺寸：左右 3%~50%、上下 3%~87% 螢幕大小
        （方法名不可叫 _apply_geometry，會與 ttkbootstrap.Window 的內部方法撞名）"""
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = int(sw * 0.03)
        y = int(sh * 0.03)
        width = int(sw * 0.50) - x
        height = int(sh * 0.87) - y
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _apply_window_icon(self):
        """設定應用程式左上角的圖示"""
        icon_path = resource_path(ICON_NAME)
        # 加入防呆機制，避免開發時因為找不到檔案而閃退
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception as e:
                print(f"Warning: 無法設定圖示 ({e})")
        else:
            print(f"Warning: 找不到圖示檔案 {icon_path}")

    def _setup_ui(self):
        main_frame = ttk.Frame(self, padding=20)
        main_frame.pack(fill=BOTH, expand=YES)

        # 標題
        lbl_title = ttk.Label(main_frame, text="Image to ICO Converter", font=("Helvetica", 18, "bold"))
        lbl_title.pack(pady=(0, 20))

        # 1. 輸入區塊
        input_group = ttk.Labelframe(main_frame, text="1. 選擇來源圖片", padding=15, bootstyle=PRIMARY)
        input_group.pack(fill=X, pady=5)

        input_row = ttk.Frame(input_group)
        input_row.pack(fill=X, pady=5)

        self.entry_input = ttk.Entry(input_row, textvariable=self.input_path_var)
        self.entry_input.pack(side=LEFT, fill=X, expand=YES, padx=(0, 10))

        self.btn_browse = ttk.Button(input_row, text="瀏覽圖片", bootstyle=OUTLINE)
        self.btn_browse.pack(side=RIGHT)

        # 2. 輸出設定區塊
        output_group = ttk.Labelframe(main_frame, text="2. 輸出設定", padding=15, bootstyle=INFO)
        output_group.pack(fill=X, pady=10)

        # 輸出路徑
        ttk.Label(output_group, text="輸出資料夾：").pack(anchor=W)
        dir_row = ttk.Frame(output_group)
        dir_row.pack(fill=X, pady=5)

        self.entry_output_dir = ttk.Entry(dir_row, textvariable=self.output_dir_var)
        self.entry_output_dir.pack(side=LEFT, fill=X, expand=YES, padx=(0, 10))

        self.btn_select_dir = ttk.Button(dir_row, text="選擇資料夾", bootstyle=OUTLINE)
        self.btn_select_dir.pack(side=RIGHT)

        # 輸出檔名
        ttk.Label(output_group, text="輸出檔名 (.ico)：").pack(anchor=W, pady=(10, 0))
        self.entry_output_name = ttk.Entry(output_group, textvariable=self.output_name_var)
        self.entry_output_name.pack(fill=X, pady=5)

        # 3. 確認輸出按鈕區塊
        action_frame = ttk.Frame(main_frame)
        action_frame.pack(fill=X, pady=25)

        self.btn_confirm = ttk.Button(
            action_frame,
            text="確認輸出並轉換 (Convert)",
            bootstyle="SUCCESS",
            width=25
        )
        self.btn_confirm.pack(side=RIGHT)

        # 狀態列
        self.lbl_status = ttk.Label(
            main_frame,
            text="等待操作...",
            bootstyle=SECONDARY,
            wraplength=540,
            justify=LEFT,
        )
        self.lbl_status.pack(fill=X, anchor=W)

    # --- View 介面操作方法 ---
    def set_input_path(self, path): self.input_path_var.set(path)
    def set_output_dir(self, path): self.output_dir_var.set(path)
    def set_output_name(self, name): self.output_name_var.set(name)
    def get_input_path(self): return self.input_path_var.get().strip()
    def get_output_dir(self): return self.output_dir_var.get().strip()
    def get_output_name(self): return self.output_name_var.get().strip()

    def show_message(self, title, message, is_error=False):
        if is_error:
            messagebox.showerror(title, message)
        else:
            messagebox.showinfo(title, message)

    def ask_yes_no(self, title, message):
        return messagebox.askyesno(title, message)

    def set_busy(self, busy: bool):
        """轉換進行中時停用按鈕，避免重複點擊。"""
        state = DISABLED if busy else NORMAL
        self.btn_confirm.config(state=state)
        self.btn_browse.config(state=state)
        self.btn_select_dir.config(state=state)

    def update_status(self, text, style=INFO):
        self.lbl_status.config(text=text, bootstyle=style)


# ==========================================
# 3. Presenter: 邏輯控制
# ==========================================
class IconConverterPresenter:
    def __init__(self, view: IconConverterView, model: IconConverterModel):
        self.view = view
        self.model = model

        # 綁定事件
        self.view.btn_browse.config(command=self.select_input_file)
        self.view.btn_select_dir.config(command=self.select_output_directory)
        self.view.btn_confirm.config(command=self.perform_conversion)

        # 安全關閉
        self.view.protocol('WM_DELETE_WINDOW', self.on_closing)

    def select_input_file(self):
        file_path = filedialog.askopenfilename(
            title="選擇圖片",
            filetypes=[
                ("Image Files", "*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.webp;*.tif;*.tiff;*.ico"),
                ("All Files", "*.*"),
            ]
        )
        if file_path:
            self.view.set_input_path(file_path)
            path_obj = Path(file_path)
            # 自動填入預設值
            self.view.set_output_dir(str(path_obj.parent))
            self.view.set_output_name(f"{path_obj.stem}.ico")
            self.view.update_status(f"已選擇：{path_obj.name}", INFO)

    def select_output_directory(self):
        dir_path = filedialog.askdirectory(title="選擇輸出資料夾")
        if dir_path:
            self.view.set_output_dir(dir_path)

    def perform_conversion(self):
        """執行轉換的邏輯"""
        full_output_path = self._validate_and_build_path()
        if full_output_path is None:
            return

        self.view.set_busy(True)
        self.view.update_status("正在處理圖片...", WARNING)
        self.view.update_idletasks()
        try:
            success, msg, notes = self.model.convert_to_ico(
                self.view.get_input_path(), full_output_path
            )
        finally:
            self.view.set_busy(False)

        if success:
            note_text = "\n".join(notes)
            self.view.update_status(
                note_text or "轉換成功！", WARNING if notes else SUCCESS
            )
            self.view.show_message("完成", f"{msg}\n\n{note_text}".strip())
        else:
            self.view.update_status(msg, DANGER)
            self.view.show_message("失敗", msg, True)

    def _validate_and_build_path(self):
        """驗證所有輸入；通過則回傳完整輸出路徑，否則回傳 None 並提示使用者。"""
        input_path = self.view.get_input_path()
        output_dir = self.view.get_output_dir()
        output_name = self.view.get_output_name()

        if not input_path or not os.path.isfile(input_path):
            self.view.show_message("錯誤", "找不到輸入圖片", True)
            return None
        if not output_dir:
            self.view.show_message("錯誤", "輸出路徑不得為空", True)
            return None
        if not os.path.isdir(output_dir):
            self.view.show_message("錯誤", f"輸出資料夾不存在：\n{output_dir}", True)
            return None
        if not output_name:
            self.view.show_message("錯誤", "輸出檔名不得為空", True)
            return None

        bad = [c for c in INVALID_NAME_CHARS if c in output_name]
        if bad:
            self.view.show_message("錯誤", f"檔名不可包含這些字元：{' '.join(bad)}", True)
            return None

        if not output_name.lower().endswith('.ico'):
            output_name += ".ico"

        full_output_path = os.path.join(output_dir, output_name)

        if os.path.abspath(full_output_path) == os.path.abspath(input_path):
            self.view.show_message("錯誤", "輸出檔不可與來源圖片相同", True)
            return None

        if os.path.exists(full_output_path):
            overwrite = self.view.ask_yes_no(
                "檔案已存在",
                f"以下檔案已存在，要覆蓋嗎？\n\n{full_output_path}"
            )
            if not overwrite:
                self.view.update_status("已取消，未覆蓋既有檔案。", SECONDARY)
                return None

        return full_output_path

    def on_closing(self):
        # 本程式沒有背景執行緒與 after() 排程，無狀態需要保存，直接關閉即可
        self.view.destroy()


# ==========================================
# 4. Main: 程式進入點 (包含工作列 ID 設定)
# ==========================================
def main():
    # 設定 AppUserModelID，讓工作列圖示正確顯示（必須在建立主視窗之前）
    if sys.platform == 'win32':
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception as e:
            print(f"Warning: Could not set AppUserModelID: {e}")

    model = IconConverterModel()
    view = IconConverterView()
    IconConverterPresenter(view, model)
    try:
        view.mainloop()
    finally:
        # 即使 mainloop 因未捕捉的例外中斷，也確保視窗資源被釋放
        try:
            view.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
