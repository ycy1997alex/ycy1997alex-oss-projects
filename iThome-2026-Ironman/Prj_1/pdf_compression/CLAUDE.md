# CLAUDE.md — pdf_compression

## 環境

conda env `app`（Python 3.12.13），與 image2ico、webp2image 三個專案共用。此環境未加入 PATH，直接用絕對路徑呼叫直譯器，不要 `conda activate`。env 路徑依電腦而異：

- **HQ-AlexYu**：`C:\Users\AlexYu\.conda\envs\app\python.exe`（2026-08-26 建立，取代原本的 `app_plot`；conda 執行檔在 `C:\Users\AA0014\AppData\Local\anaconda3\Scripts\conda.exe`，是舊使用者目錄留下的安裝，但 `envs_dirs` 已指向 `C:\Users\AlexYu\.conda\envs`）
- **MSI-Alex**：`C:\Users\Alex\anaconda3\envs\app\python.exe`

```powershell
$py = "C:\Users\AlexYu\.conda\envs\app\python.exe"   # HQ-AlexYu
```

## 常用指令

```powershell
& $py -m pip install -r requirements.txt          # 安裝相依套件
& $py main.py                                     # 開發執行
& $py -m PyInstaller --noconfirm --clean pdf_compression.spec   # 打包（onefile）
& $py -m unittest discover -p "test_*.py"          # 跑全部測試
```

輸出：`dist\PDF壓縮工具.exe`（`app` 環境實測 38.8 MB，2026-08-26；舊 `app_plot` 環境是約 52 MB）。

## 打包決策

- **onefile**（`ui-project` skill §5 預設）。啟動數秒，尚無切換 onedir 的理由。
- **不用 UPX**（2026-08-26 從 `upx=True` 改掉）：與 image2ico / webp2image 一致，壓縮後的執行檔容易被防毒誤判。
- `excludes=['pandas','matplotlib','scipy']`：舊的 `app_plot` 是繪圖環境、裝有這些套件，而 `pymupdf.table` 有一處未使用的 `to_pandas()` 引用會把整條相依鏈拉進來。現在的 `app` 環境本來就沒裝這些，保留 excludes 當作保險。

## 打包踩過的坑（改 .spec 前先看這段）

1. conda 的原生 DLL 在 `<env>\Library\bin`，不在 PyInstaller 搜尋路徑上 → 打包成功但執行閃退（`ImportError: DLL load failed while importing pyexpat`）。`.spec` 已在 Analysis 前把該目錄加進 `PATH`。
2. ttkbootstrap 2.x 的 `assets/`（含 `bootstrap.ttf`）是執行時才讀的檔案 → 需 `collect_data_files('ttkbootstrap')`，否則建立 Window 時 `FileNotFoundError`。

除錯技巧：`console=False` 看不到 traceback。把 `.spec` 複製一份改成 `console=True` 再打包執行，就能在終端機看到完整錯誤。

## 測試

- `test_model.py`：Model 層。用 PyMuPDF + Pillow 在暫存目錄現場產生含雜訊圖的 PDF，測壓縮結果、min_dim 略過、目標大小的達成與未達成、取消事件、`_build_trials` 的遞減與觸底。
- `test_presenter.py`：Presenter 層。以 FakeView / FakeModel 取代 UI 與壓縮流程，不開視窗；測輸入驗證、輸出路徑組法、背景執行緒完成後的訊息與對話框、關閉時的取消流程。`schedule()` 只記錄不執行，測試自行呼叫 `_poll_queue()` 推進。
- 用 stdlib `unittest`，不需另外安裝 pytest。

## 驗證方式

- 圖示三處：`.exe` 檔案圖示（讀 PE 的 RT_GROUP_ICON 確認解析度）、標題列、工作列（`WM_GETICON` 取 HICON 並畫出來比對）。
- 功能：以 PyMuPDF 產生含大圖的 PDF，跑一次 `PdfCompressorModel.compress()`，確認產出變小且可正常開啟。
