# CLAUDE.md — webp2image

## 專案決策

- **架構**：MVP 三層全部寫在單一 `webp2image.py`（使用者指定）。背景執行緒不碰 widget，一律經 `MainView.post()` → `queue.Queue` → `after` 輪詢。
- **版本**：`APP_VERSION = "1"`，與 image2ico 一致（2026-08-24 從 `"1.0.0"` 改過來）。`test_convert.py` 會檢查這個值。
- **環境：conda env `app`**（Python 3.12.13，ttkbootstrap 2.2.0），與 image2ico、pdf_compression 三個專案共用。env 路徑依電腦而異：
  - **MSI-Alex**：`C:\Users\Alex\anaconda3\envs\app\python.exe`
  - **HQ-AlexYu**：`C:\Users\AlexYu\.conda\envs\app\python.exe`（2026-08-26 建立，取代原本借用的 `app_plot`；conda 執行檔在 `C:\Users\AA0014\AppData\Local\anaconda3\Scripts\conda.exe`，是舊使用者目錄留下的安裝，但 `envs_dirs` 已指向 `C:\Users\AlexYu\.conda\envs`）
  - 一律用絕對路徑呼叫對應電腦的 python.exe，不要 `conda activate`。舊的 `webp2image` / `app_plot` env 已不再使用。
- **打包**：onefile，spec 是 `Webp2Image.spec`，產物 `dist/Webp2Image.exe`。在 `app` 環境實測 20.4 MB（MSI-Alex，2026-08-24）、20.1 MB（HQ-AlexYu，2026-08-26），啟動正常，沒有換成 onedir 的理由。
- **.spec 必須把 `<env>\Library\bin` 加進 `PATH`**：conda 的原生 DLL（`ffi-8.dll` 等）在那裡，不在 PyInstaller 的搜尋路徑上。漏掉會打包成功但 exe 一啟動就 `ImportError: DLL load failed while importing _ctypes` 閃退。
- **.spec 必須 `collect_data_files("ttkbootstrap")`**：PyInstaller 與 hooks-contrib 都沒有 ttkbootstrap 的 hook，漏掉 themes/assets 會讓打包後的程式在建立視窗時啟動失敗。
- **文件範圍**：目前只有 `README.md`（使用者選定）。`UI_README.html`（開發者架構文件）與 `使用者指引.html`（終端使用者手冊）**尚未建立**，要交付給非開發者時再補。
- **App 圖示**：`webp2image_icon.ico`（16/24/32/48/64/128/256 七種尺寸，來源是同目錄的 1024×1024 `webp2image_icon.jpg`）。`.spec` 的 `icon=` 與 `datas` 都指向它，程式端由 `ICON_FILENAME` + `resource_path()` 讀取。

## 踩過的坑（別再踩）

- **ttkbootstrap 2.2.0 的主題**：`STANDARD_THEMES` 是 `cosmo` / `flatly` / `darkly` 這組舊命名，`bootstrap-light` 也接受。本專案用 `bootstrap-light`，image2ico 用 `cosmo`，兩者在 2.2.0 都能開起來。（本檔先前寫「2.2.0 沒有 cosmo」，2026-08-24 實測為誤，已更正。）
- **`ttkbootstrap.scrolled` 模組不存在**：`ScrolledText` 要直接從頂層 `ttkbootstrap` 取用。
- **Windows 檔名不分大小寫**：把 `webp2image.spec` 改名成 `Webp2Image.spec` 時，`cat > Webp2Image.spec` 寫的其實是同一個檔案，接著 `rm webp2image.spec` 會把新檔一起刪掉。要換大小寫得先改成暫時檔名再改回來。

## 驗證方式

1. **測試單元**：用當前這台電腦對應的 python.exe（見上方環境設定）執行 `test_convert.py`，應輸出 11 個 PASS。涵蓋四種輸出格式、透明壓白底 vs 保留 alpha、動畫取首幀、來源展開（遞迴／大小寫／去重）、略過與覆寫、單檔毀損不中斷整批、`should_continue` 提前中止、隨附 App 圖示的尺寸、版本號。
2. **View + Presenter**：跑完整批轉換確認產出數量與統計對話框；再測「轉換途中關閉視窗」——必須無 tkinter callback 例外、無殘留非主執行緒、關閉在數秒內完成。
3. **打包後的圖示**：不要用截圖驗收（會拍到使用者桌面上的個人內容）。改用 ctypes 列舉 exe 的 `RT_ICON` 資源確認尺寸齊全，再用 `PyInstaller.archive.readers.CArchiveReader` 確認 `webp2image_icon.ico` 有進到 onefile 封包裡。
4. **打包後的執行**：啟動 `dist/Webp2Image.exe`（onefile 會另開子行程，父行程沒有視窗，要用 `Get-Process Webp2Image` 找有 `MainWindowTitle` 的那個），確認視窗標題是 `WebP 轉圖片 v1`；另用 console 探針 exe 驗證凍結環境下 Pillow 的 `_webp` 能實際解碼。

## 已知邊界

- 動畫 webp 只取第一幀。
- JPEG / BMP 不支援 alpha，透明區域壓平成白底；PNG / TIFF 保留。
- 「開始轉換」後只能中止（關視窗），沒有暫停/續傳。
