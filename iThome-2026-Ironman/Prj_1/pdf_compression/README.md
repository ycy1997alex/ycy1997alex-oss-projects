# PDF 壓縮工具（pdf_compression）

## Overview

桌面 GUI 工具，用來壓縮 PDF 檔案大小。原理是把 PDF 內嵌的點陣圖片（PNG/JPEG）依設定的縮放比例與 JPEG 品質重新編碼，其餘文字與向量內容維持不變。支援輸入「目標檔案大小」，並在勾選「自動加強壓縮」時，於壓縮結果超出目標時自動逐步調降縮放比例與品質、重新嘗試，直到達成目標或用盡可調範圍。

## Architecture

採用 MVP（Model-View-Presenter）架構，三層互不越界：

- **Model**（`model.py`）：純壓縮邏輯，不依賴任何 UI 套件，可獨立於 CLI 或測試中呼叫。
- **View**（`view.py`）：只負責畫面呈現與使用者輸入（ttkbootstrap），不含任何壓縮邏輯，透過 `bind_*` 方法把事件交給外部處理。
- **Presenter**（`presenter.py`）：接收 View 的事件、驗證輸入、在背景執行緒呼叫 Model，並透過 `queue.Queue` + `root.after()` 把結果安全地送回主執行緒更新畫面。

```
main.py
  ├─ View（畫面、使用者輸入、對話框）
  ├─ Model（PDF 圖片重新編碼、目標大小自動搜尋）
  └─ Presenter（事件轉接、背景執行緒、佇列輪詢、安全關閉）
        │
        ├──> 呼叫 Model.compress() （背景執行緒）
        └──> 透過 queue 回報 progress / log / done 給 View（主執行緒 after() 輪詢）
```

## 目錄結構

```
pdf_compression/
├── main.py            # 進入點，組裝 Model / View / Presenter
├── model.py            # PDF 壓縮邏輯（PyMuPDF + Pillow）
├── view.py              # GUI 畫面（ttkbootstrap，主題：flatly）
├── presenter.py          # 事件處理、背景執行緒、佇列輪詢
├── requirements.txt      # 相依套件
├── pdf_compression.ico   # 應用程式圖示（多解析度）
├── pdf_compression.spec  # PyInstaller 打包設定（onefile）
└── README.md
```

## Setup & run

```powershell
# 安裝相依套件
pip install -r requirements.txt

# 啟動
python main.py
```

平台：Windows（PowerShell）。

### 打包成 .exe

```powershell
pip install pyinstaller
pyinstaller pdf_compression.spec
```

輸出在 `dist\PDF壓縮工具.exe`（onefile，單一執行檔，無需另外安裝 Python）。

`pymupdf` 內建一個沒用到、以 try/except 保護的 `Table.to_pandas()` 方法，若環境裝有 pandas，PyInstaller 靜態分析仍會把它與其重量級的相依鏈（matplotlib / scipy / lxml 等）一併打包進去，體積會從約 56MB 暴增到 100MB 以上。`pdf_compression.spec` 已在 `excludes` 排除 `pandas`／`matplotlib`／`scipy`，因為本工具完全不使用 PDF 表格擷取功能；若之後有其他模組需要用到這些套件，記得從 `excludes` 移除。

### 應用程式圖示

圖示檔為 `pdf_compression.ico`（多解析度：16/32/48/64/128/256 px），三個顯示位置都已接上：

| 位置 | 來源 |
| --- | --- |
| `.exe` 在檔案總管的圖示 | `.spec` 的 `icon='pdf_compression.ico'` |
| 視窗標題列 | `view.py` 的 `_apply_icon()` → `root.iconbitmap()` |
| 工作列 | 同上，並在建立 root 視窗前呼叫 `SetCurrentProcessExplicitAppUserModelID()`，否則 Windows 會沿用 Python 直譯器的圖示 |

onefile 打包時執行檔會把資源解壓到 `sys._MEIPASS`，所以 `.ico` 必須同時列在 `.spec` 的 `datas`，程式端則透過 `view.py` 的 `resource_path()` 取得實際路徑。

> 目前的 `.ico` 由一張 32×32 的原圖放大產生，256 px 這一階在大圖示檢視下會偏糊。若日後取得 ≥256 px 的原始圖檔，重新產生 `.ico` 即可，程式與 `.spec` 都不必改。

### 打包環境注意事項

conda 環境把 `libexpat.dll`、`tcl86t.dll`、`tk86t.dll` 等原生 DLL 放在 `<env>\Library\bin`，不在 PyInstaller 的預設搜尋路徑上。沒補上會「打包成功但一執行就閃退」（`ImportError: DLL load failed while importing pyexpat`），`.spec` 已在 Analysis 前把該目錄加進 `PATH`。

ttkbootstrap 2.x 的圖示字型等資產（`ttkbootstrap/assets/…`）是執行時才讀的檔案，靜態分析抓不到，`.spec` 以 `collect_data_files('ttkbootstrap')` 明確收集；缺少時會在建立視窗時丟 `FileNotFoundError: …bootstrap.ttf`。

## Dependencies

- **pymupdf (fitz)**：讀寫 PDF、取出/替換內嵌圖片物件（含 SMask 透明遮罩）。
- **pillow**：圖片縮放與 JPEG 重新編碼。
- **ttkbootstrap**：在 tkinter 上提供現代化 Bootstrap 風格元件（本專案採用 `flatly` 主題）。

## Configuration

無需設定檔或環境變數。所有壓縮參數皆於 GUI 畫面中即時設定：

| 設定項 | 說明 | 預設值 |
| --- | --- | --- |
| 目標檔案大小 (MB) | 留空表示不限制，只用下方縮放比例／品質做單次壓縮 | 空 |
| 自動加強壓縮 | 有設定目標大小時，超出目標會自動逐步調降縮放比例與品質重試（最多 8 次） | 開 |
| 圖片縮放比例 | 內嵌圖片的長寬縮放比例 | 0.75 |
| JPEG 品質 | 重新編碼的 JPEG 品質（1–95） | 78 |
| 最小圖片邊長 (px) | 小於此邊長的圖片（如 icon/logo）不壓縮 | 200 |

## 已知限制

- 只對點陣圖片重新編碼，若 PDF 體積來自大量文字/向量內容或內嵌字型，壓縮效果有限。
- 壓縮採不可逆的 JPEG 重新編碼，含透明背景的圖片會被合成到白底（適用於一般白底報告；若圖片疊在非白底頁面上，透明區域可能與頁面顏色不符）。
- 目標大小自動搜尋為固定步進（縮放 -0.08、品質 -7，下限 0.3 / 35），非精確二分搜尋，可能略高於或低於目標一些。
