# CLAUDE.md — RegressionAnalyzer

給 Claude Code 在這個子專案裡工作時的指引。上層 [../CLAUDE.md](../CLAUDE.md) 描述的是鐵人賽文章專案；**這個資料夾是真正的軟體專案**，有程式要跑、要測、要打包。

架構、模組職責、指令與相依套件的完整說明在 [README.md](README.md)，不要在這裡重複。

## 環境（已驗證 2026-08-28）

`conda` **不在 PATH 上**。一律用絕對路徑呼叫，不要 `conda activate`：

```
C:\Users\AlexYu\.conda\envs\stats\python.exe
```

該環境已具備全部相依套件（pandas 3.0.4、scikit-learn 1.9.0、statsmodels 0.14.6、matplotlib 3.11.0、seaborn 0.13.2、ttkbootstrap 1.20.4、python-docx 1.2.0、XlsxWriter 3.2.9、pyinstaller 6.21.0）。

## 常用指令

| 目的 | 指令 |
|---|---|
| 開介面 | `python.exe main.py` |
| 跑完整流程（無介面） | `python.exe main.py --selftest Data_Template_Stats.xlsx out\` |
| 建 onedir | `python.exe -m PyInstaller RegressionAnalyzer-onedir.spec --noconfirm --distpath dist\onedir --workpath build\onedir` |
| 建 onefile | `python.exe -m PyInstaller RegressionAnalyzer-onefile.spec --noconfirm --distpath dist\onefile --workpath build\onefile` |
| 格式檢查回歸測試 | `python.exe tools\check_format_rules.py` |
| 重產圖示 | `python.exe tools\make_icon.py` |

沒有 pytest 測試套件。驗收靠三件事：`tools\check_format_rules.py`（11 個格式案例全過）、`--selftest`（exit code 0 且三份報表都在）、以及實際開介面操作一次。

## 這個專案已經做過的決定

| 決定 | 結論 | 理由 |
|---|---|---|
| 打包方式 | **onefile 與 onedir 兩份都維護** | 使用者要求兩種都做並實測比較。實測（2026-08-28）：onedir 221 MB／2,484 檔／啟動 3.5 秒；onefile 97 MB／單檔／啟動 7.6 秒。onefile 反而比較小，因為 PyInstaller 會壓縮單檔封存 —— 別再憑印象說 onefile 比較肥 |
| sklearn 是否保留 | **保留** | 只用於 Bolasso 的 Lasso／LassoCV。拿掉省 40 MB（約佔核心相依 320 MB 的 12%），但 200 次 bootstrap 從 0.07 秒變 2.6 秒，且挑 α 要自己手刻 k-fold CV |
| UI_README.html | **不做** | 使用者明確表示先不要 |
| 使用者指引.html | **不做** | 同上。若日後要交付給非開發者，依 `ui-project` 規範補上 |
| ttkbootstrap 主題 | `cosmo` | 設計稿直接取用它的色票，確保畫得出來的東西 ttk 真的做得到 |
| 類別型結果變項 | **不支援，於格式檢查時報錯** | 本工具只做迴歸；類別型結果屬於分類任務 |

## 容易踩到的地方

- **`.spec` 必須在 `Analysis(...)` 之前把 `<sys.prefix>\Library\bin` 加進 `PATH`。** conda 的原生 DLL 放在那裡，不加的話建置照樣 exit 0，但 .exe 啟動時死在 `ImportError: DLL load failed while importing _ctypes`。`Analysis(pathex=[...])` 沒有用，那管的是 Python 模組搜尋。**驗收看的是建置紀錄裡 `Library not found` 為 0，不是 exit code。**
- **`ttkbootstrap.Window()` 要傳 `iconphoto=None`**，否則它會用自己的 logo 蓋掉 `iconbitmap`，標題列與工作列都變成 ttkbootstrap 的圖示。
- **matplotlib 標籤不要用 U+2212 MINUS SIGN**，`Microsoft JhengHei` 沒有這個字，會印成豆腐框。用 ASCII 連字號。
- **`view/main_view.py` 的 `_build()` 裡 pack 的順序是空間分配順序，不是畫面上下順序。** 分析紀錄與執行列先用 `side="bottom"` pack，最後才 pack 分析欄位區。順序寫反的話，視窗一矮下來被壓扁的就是紀錄區和按鈕列。
- **視窗尺寸是量測後校正的**（`_apply_geometry`）。`geometry()` 設的是內容區，Windows 會再加標題列與一圈隱形邊框；直接套百分比會偏掉約 39px。
- **`console=False` 的 exe 沒有 stdout**，`--selftest` 的結果要看 `<輸出目錄>\_selftest.log` 與 exit code。
- 工作執行緒**不得碰任何 widget**，一律走 `queue.Queue` ＋ `after()`。
