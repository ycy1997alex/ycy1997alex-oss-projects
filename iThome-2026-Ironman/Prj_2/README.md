# RegressionAnalyzer

一個 Windows 桌面工具：讀入符合樣板格式的 Excel，對每個結果變項跑 200 次 Bolasso 篩選變項、配適 OLS 迴歸，然後把統計視覺化、模型報表與一份 Word 分析報告一次輸出到指定資料夾。介面用 tkinter／ttkbootstrap，架構是 MVP，分析全部跑在背景執行緒上，執行中可以隨時停止而不必關掉程式。

輸入格式的完整定義在 [Data_Template_Stats_Format_Definition.md](Data_Template_Stats_Format_Definition.md)，[Data_Template_Stats.xlsx](Data_Template_Stats.xlsx) 是可直接使用的樣板。

## Architecture

MVP（Model–View–Presenter）。View 是被動的：它只畫畫面、把事件轉給 Presenter，自己不判斷任何事、不碰檔案。Model 完全不認識 tkinter，可以獨立在沒有介面的情況下跑（`main.py --selftest` 走的就是這條路）。

分析跑在一條 daemon 工作執行緒上。工作執行緒**不碰任何 widget** —— tkinter 不是執行緒安全的 —— 所有要顯示的訊息都丟進 `queue.Queue`，由主執行緒每 100ms 用 `after()` 撈出來更新畫面。中止靠一個 `threading.Event`，流程在每個階段邊界與 Bolasso 每 10 次抽樣時檢查它。

```
                    ┌──────────────────────────────────────┐
   使用者操作  ───▶ │  View  (view/main_view.py)           │
                    │  ttkbootstrap widgets，被動           │
                    └───────┬──────────────────────▲───────┘
                       事件 │                      │ after() 每 100ms
                            ▼                      │
                    ┌──────────────────────────────┴───────┐
                    │  Presenter (presenter/…)             │
                    │  驗證輸入、開執行緒、輪詢 queue        │
                    └───────┬──────────────────────▲───────┘
             AnalysisRequest│                      │ queue.Queue
                            ▼                      │ (log / stage / done
              ┌─────────────────────────┐          │  / cancelled / error)
              │  工作執行緒 (daemon)      │──────────┘
              │  pipeline.run_analysis  │
              └───────────┬─────────────┘
                          │  RunContext（取消 Event ＋ 兩個 callback）
                          ▼
   excel_reader ─▶ features ─▶ bolasso ─▶ modeling ─▶ visualization
                                                   └▶ report_excel / report_word
```

模組職責：

| 模組 | 負責 |
|---|---|
| `model/schema.py` | `ColumnSpec` / `Dataset` / `AnalysisRequest` 等資料結構 |
| `model/excel_reader.py` | 讀 Excel 並一次收集所有格式問題（不是遇到第一個就中斷） |
| `model/features.py` | 設計矩陣：連續型原樣、類別型 One-Hot；listwise deletion |
| `model/bolasso.py` | 200 次 bootstrap Lasso，α 由全樣本 LassoCV 選定後固定 |
| `model/modeling.py` | statsmodels OLS、六項指標、5-fold 交叉驗證、VIF 與殘差診斷 |
| `model/visualization.py` | 所有圖表（強制 Agg backend，背景執行緒才畫得出來） |
| `model/report_excel.py` | `Model_Report.xlsx` 與 `Predictions.xlsx` |
| `model/report_word.py` | `Analysis_Report.docx` |
| `model/pipeline.py` | 串起整條流程，負責在每個階段邊界檢查中止訊號 |
| `model/context.py` | `RunContext`：取消 Event 與進度 callback |

## Directory structure

```
Prj_2_StatisticalAnalysis/
├── main.py                             進入點；--selftest 可無介面跑完整流程
├── app.ico                             多解析度圖示（16/32/48/64/128/256）
├── requirements.txt
├── RegressionAnalyzer-onedir.spec      PyInstaller 設定：啟動快，整個資料夾交付
├── RegressionAnalyzer-onefile.spec     PyInstaller 設定：單一 exe，啟動較慢
├── Data_Template_Stats.xlsx            輸入樣板
├── Data_Template_Stats_Format_Definition.md
├── regression_app/
│   ├── version.py                      APP_NAME / APP_VERSION / APP_ID
│   ├── paths.py                        resource_path（相容 PyInstaller onefile）
│   ├── model/                          資料、統計、報表（不依賴 UI）
│   ├── view/main_view.py               主視窗
│   └── presenter/main_presenter.py     事件處理、執行緒、關閉流程
├── tools/
│   ├── make_icon.py                    重新產生 app.ico
│   └── check_format_rules.py           格式檢查的回歸測試（11 個案例）
└── design/                             UI 設計稿原始檔（.dc.html ＋ canvas.json）
```

## Setup & run

開發環境是 conda env `stats`。這台機器上 `conda` 不在 PATH 上，一律用絕對路徑呼叫該環境的 `python.exe`，不要 `conda activate`。

```powershell
# 安裝相依套件
C:\Users\AlexYu\.conda\envs\stats\python.exe -m pip install -r requirements.txt

# 開啟圖形介面
C:\Users\AlexYu\.conda\envs\stats\python.exe main.py

# 不開介面跑完整條分析（打包驗收用；結果寫進 <輸出目錄>\_selftest.log，成敗看 exit code）
C:\Users\AlexYu\.conda\envs\stats\python.exe main.py --selftest Data_Template_Stats.xlsx out\

# 格式檢查的回歸測試（改過 excel_reader.py 就跑這支）
C:\Users\AlexYu\.conda\envs\stats\python.exe tools\check_format_rules.py

# 重新產生圖示
C:\Users\AlexYu\.conda\envs\stats\python.exe tools\make_icon.py
```

打包：

```powershell
# onedir：啟動快，交付時整個資料夾一起給
C:\Users\AlexYu\.conda\envs\stats\python.exe -m PyInstaller RegressionAnalyzer-onedir.spec `
    --noconfirm --distpath dist\onedir --workpath build\onedir

# onefile：單一 exe，每次啟動都要先解壓到暫存資料夾
C:\Users\AlexYu\.conda\envs\stats\python.exe -m PyInstaller RegressionAnalyzer-onefile.spec `
    --noconfirm --distpath dist\onefile --workpath build\onefile
```

兩種方式的實測差異（2026-08-28，本機 1920×1080）：

| | 體積 | 檔案數 | 啟動到視窗出現 | 跑完一次分析 |
|---|---:|---:|---:|---:|
| onedir | 221 MB | 2,484 | 3.5 秒 | 66 秒 |
| onefile | 97 MB | 1 | 7.6 秒 | 81 秒 |

onefile 比較小是因為 PyInstaller 會壓縮單檔封存；代價是每次啟動都要把內容解壓到暫存資料夾，所以啟動與整體執行都慢一截。要好交付選 onefile，要開得快選 onedir。

**打包的驗收標準是「建置紀錄裡沒有任何 `Library not found`」，不是 exit 0** —— 兩者都會回 0。兩份 .spec 都在 `Analysis(...)` 之前把 `<sys.prefix>\Library\bin` 加進 `PATH`；少了那一行，建置照樣成功，但 .exe 會在啟動時死於 `ImportError: DLL load failed while importing _ctypes`。用 `Analysis(pathex=[...])` 代替沒有用：`pathex` 管的是 Python 模組搜尋，DLL 相依走的是 `PATH`。

打包完成後跑一次 selftest 確認（視窗開得起來不代表相依套件都在）：

```powershell
dist\onedir\RegressionAnalyzer\RegressionAnalyzer.exe --selftest <完整路徑>\Data_Template_Stats.xlsx <輸出目錄>
echo $LASTEXITCODE   # 0 才算過
```

## Dependencies

| 套件 | 為什麼是它 |
|---|---|
| `statsmodels` | 最終模型用它，因為報告需要 p 值、標準誤與信賴區間 —— sklearn 的線性模型不提供這些 |
| `scikit-learn` | 只用在 Bolasso 的 `Lasso` 與 `LassoCV`。改用 statsmodels 的 `fit_regularized` 可省約 40 MB，但 200 次 bootstrap 會從 0.07 秒變成 2.6 秒，而且挑 α 得自己手刻 k-fold CV |
| `pandas` / `numpy` / `scipy` | 資料處理與統計計算的底層 |
| `matplotlib` / `seaborn` | 所有圖表；seaborn 提供 violin、heatmap 與 pair plot |
| `openpyxl` | 讀 xlsx |
| `XlsxWriter` | 寫 xlsx，能設定標題列樣式、欄寬與凍結窗格 |
| `python-docx` | 產生 Word 分析報告 |
| `ttkbootstrap` | 讓 tkinter 有現代外觀；本專案用 `cosmo` 主題 |
| `pillow` | 產生多解析度 .ico |

## Configuration

沒有設定檔，也沒有任何金鑰或連外服務 —— 所有輸入來自使用者選的 Excel，所有輸出都寫在使用者指定的資料夾裡。

可調參數寫在程式碼中，需要改就改這幾處：

| 參數 | 位置 | 預設 |
|---|---|---|
| bootstrap 次數 | `model/schema.py` `AnalysisRequest.n_bootstrap` | 200 |
| 變項選入門檻 | `model/schema.py` `AnalysisRequest.selection_threshold` | 0.9 |
| 亂數種子 | `model/schema.py` `AnalysisRequest.random_state` | 0 |
| 交叉驗證折數 | `model/modeling.py` `CV_FOLDS` | 5 |
| 直方圖 bin 數 | `model/visualization.py` `HIST_BINS` | 50 |
| 圖檔解析度 | `model/visualization.py` `DPI` | 300 |
| 視窗佔螢幕比例 | `view/main_view.py` `_LEFT` / `_RIGHT` / `_TOP` / `_BOTTOM` | 0.10 / 0.90 / 0.03 / 0.87 |
| 主題 | `view/main_view.py` `THEME` | `cosmo` |
