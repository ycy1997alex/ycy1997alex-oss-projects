# CLAUDE.md — image2ico

## 專案決策

- **文件範圍：只做 README.md。** 使用者在 2026-08-09 明確表示不需要 UI_README.html、使用者指引.html、README.en.md。之後不要再問，除非使用者主動要求。
- **環境：conda env `app`**（Python 3.12.13），與 webp2image、pdf_compression 三個專案共用。一律用絕對路徑呼叫，不要 `conda activate`。舊的 `image2ico` / `app_plot` env 已不再使用。env 路徑依電腦而異：
  - **MSI-Alex**：`C:\Users\Alex\anaconda3\envs\app\python.exe`
  - **HQ-AlexYu**：`C:\Users\AlexYu\.conda\envs\app\python.exe`（2026-08-26 建立；conda 執行檔在 `C:\Users\AA0014\AppData\Local\anaconda3\Scripts\conda.exe`，是舊使用者目錄留下的安裝，但 `envs_dirs` 已指向 `C:\Users\AlexYu\.conda\envs`）
- **打包用 onefile。** 啟動約 2–3 秒，沒有改 onedir 的理由。體積在 `app` 環境實測 20.5 MB（MSI-Alex，2026-08-24）、20.1 MB（HQ-AlexYu，2026-08-26）；`app_plot` 那次是 28.1 MB，差在那個環境把 numpy 等無關套件也收進了 bundle。`app` 只裝三個專案的相依套件，這個數字就是乾淨值。
- **隨附的 `image2ico_icon.ico` 含 16/32/48/64/128/256 六種尺寸**（來源是同目錄的 1024×1024 PNG），`test_convert.py` 的 `check_shipped_icon()` 每次都會驗。本程式的產物就是 `.ico`，自己的圖示不合格說不過去。
- **轉換策略：補透明邊 + 放大。** 非正方形來源置中補透明邊；小於 256px 的來源放大到 256px。兩者都會在 UI 回報 notes。使用者在 2026-08-09 從三個選項中選定此策略。

## 踩過的坑（別再踩）

- **`_setup_icon` 這個方法名不能用。** ttkbootstrap 2.2.0 的 `Window.__init__` 會呼叫`self._setup_icon(iconphoto, default_data=...)`，在 View 上定義同名方法會被父類別以錯誤參數呼叫，程式在 `super().__init__()` 就 TypeError 掛掉。目前叫 `_apply_window_icon`。
- **`.spec` 必須把 `<env>\Library\bin` 加進 `PATH`。** conda 的原生 DLL（`ffi-8.dll` 等）放在那裡，不在 PyInstaller 的搜尋路徑上。少了這段，打包會成功但 exe 一啟動就 `ImportError: DLL load failed while importing _ctypes` 閃退。2026-08-26 在 HQ-AlexYu 的 `app` env 踩到，pdf_compression 早就修過同一個坑。
- **`.spec` 必須 `collect_data_files('ttkbootstrap')`。** ttkbootstrap 2.x 需要`assets/icons/bootstrap.ttf`，PyInstaller 不會自動收集。少了它，開發環境正常但打包後的 exe一啟動就 FileNotFoundError 閃退。
- **Pillow 的 ICO save 會靜默出錯。** 直接 `img.save(..., sizes=[...])` 時，大於原圖的尺寸被丟棄、非正方形來源產生非正方形 frame，兩者都不報錯。必須自己 normalize + 逐尺寸 resize + `append_images`，寫完再讀回驗證。詳見 README「為什麼不直接把原圖丟給 Pillow」。
- **不要用 SendKeys / 截圖驅動 GUI 做驗收。** 會截到使用者桌面上的個人內容。要驗證 frozen 行為就打包一支 console harness 直接呼叫 Model；要驗打包後的圖示，就用 ctypes 列舉 exe 的 `RT_ICON` 資源，再用 `PyInstaller.archive.readers.CArchiveReader` 確認 `.ico` 有進到 onefile 封包裡。
