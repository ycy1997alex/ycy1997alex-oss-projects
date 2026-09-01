# MiBand6BleExplorer

一支對小米手環 6 的 BLE **唯讀**探索工具：掃描週遭裝置、連線、列舉完整 GATT 結構、讀取所有可讀的 characteristic、訂閱所有可訂閱的 characteristic，並把已知欄位解碼成看得懂的字。命令列版與 ttkbootstrap 圖形介面版各一支，架構是 MVP，BLE 全部跑在背景的 asyncio 事件迴圈上。

**唯讀是硬性規定**：不寫入任何 characteristic，不嘗試華米（Huami／Zepp）認證，不修改手環上的任何設定。手環的私有服務（`0xFEE0`）多數需要 auth key，未認證時讀取會被拒絕，程式把拒絕原因如實印出來而不是吞掉。

驗收方式很簡單：全專案 grep 不到 `write_gatt_char`。

## Architecture

兩支主程式**各自完全自包含**：`mi_band_explorer_gui.py` 不 import `mi_band_explorer.py`，UUID 對照表與解碼器各帶一份。這是刻意的取捨——GUI 版要能單獨搬走或打包，不用管相對路徑——代價是兩份要手動同步。

圖形介面版是 MVP（Model–View–Presenter）：

| 層 | 類別 | 負責 |
|---|---|---|
| Model | `BandModel` | 所有 BLE 行為，全部是 coroutine，完全不碰 Tk |
| Model | `LogRecorder` | 純檔案 I/O：一次性快照存檔與即時逐行寫入 |
| View | `ExplorerView` | 純 ttkbootstrap widget，完全不懂 BLE |
| Presenter | `ExplorerPresenter` | 綁定兩者，並負責跨執行緒交棒 |
| — | `AsyncRunner` | 背景 daemon 執行緒上的 asyncio 事件迴圈 |

View **不持有 Presenter 的參考**：使用者操作一律經由 View 身上的 `on_*` 屬性外露，預設是空函式，由 Presenter 在建構時指派。View 因此可以單獨拿出來跑，只是按了沒反應。

真正的難點是兩個都想當主人的迴圈。bleak 走 asyncio，Tk 的 `mainloop()` 要佔住主執行緒，而 Tk 的 widget 只能從建立它的那條執行緒去碰。解法是：事件迴圈跑在背景 daemon 執行緒，Model 只呼叫 `emit(kind, payload)` 把結果塞進 `queue.Queue`，Presenter 在主執行緒用 `after(50)` 輪詢，撈出來才碰 widget。

```
                     ┌────────────────────────────────────────┐
    使用者操作  ───▶ │  ExplorerView                          │
                     │  ttkbootstrap widget，被動              │
                     └──────┬───────────────────────▲─────────┘
                    on_*()  │                       │  set_devices / set_gatt
                            ▼                       │  log_to_window / set_status
                     ┌──────────────────────────────┴─────────┐
                     │  ExplorerPresenter                     │
                     │  指派 on_*、鎖忙碌、輪詢 queue、關閉流程 │
                     └──────┬───────────────────────▲─────────┘
     submit(coroutine)      │                       │  after(50ms) 輪詢
                            ▼                       │
              ┌──────────────────────────┐   queue.Queue
              │  AsyncRunner（daemon）    │   (log / status / devices / gatt
              │  asyncio event loop      │    / connected / disconnected
              └──────┬───────────────────┘    / notifying / done)
                     │                                │
                     ▼                                │
              ┌──────────────────────────┐  emit()    │
              │  BandModel               │────────────┘
              │  scan / connect / …      │
              └──────┬───────────────────┘
                     ▼
                   bleak ──▶ WinRT ──▶ 小米手環 6

              LogRecorder ◀── Presenter._log()（視窗與檔案同一個出口）
```

規矩只有一條：**背景執行緒絕不碰任何 widget**。這條在斷線時最明顯——bleak 的斷線 callback 從它自己的執行緒呼叫，它只丟一則 `disconnected` 訊息，50 毫秒內主執行緒撈到，才把整組 UI 打回未連線狀態。

命令列版沒有分層，是一個 `Explorer` 類別加上一圈選單迴圈；`input()` 包成 `asyncio.to_thread` 才不會擋住事件迴圈，斷線 callback 也才有機會被呼叫。

## Directory structure

```
Prj_3_BluetoothConnection/
├── mi_band_explorer.py                  命令列版；互動選單，例外直接印在主控台
├── mi_band_explorer_gui.py              圖形介面版；MVP，自包含，打包的進入點
├── device_config.py                     測試腳本用來決定「要測哪一支手環」
├── device.local.example                 位址設定範本（複製成 device.local）
├── requirements.txt                     只有執行期的兩行相依
├── app.ico                              多解析度圖示（16/32/48/64/128/256）
├── MiBand6BleExplorer-onefile.spec      PyInstaller 設定；建置指令寫在檔頭
├── unit_test/
│   ├── test_scan.py                     掃描：手環有沒有在廣播
│   ├── test_connect.py                  連線與讀取；含唯一不需要手環的 test_decoders()
│   └── test_notify.py                   訂閱與監看
├── tools/
│   └── make_icon.py                     重新產生 app.ico
├── ui_design/                           三張 UI 設計稿 ＋ 被選上那張的原始檔
└── test_record_20260830/                2026-08-30 那一輪實測的原始輸出與腳本
```

文件另有三份：本檔（開發者摘要）、`UI_README.html`（架構與互動流程，可雙擊開啟）、`使用者指引.html`（給拿到 `.exe` 的非開發者，不提到任何原始碼）。

## Setup & run

開發環境是 conda env `nb_ble`。這台機器上 `conda` **不在 PATH 上**，一律用絕對路徑呼叫該環境的 `python.exe`，不要 `conda activate`。

```powershell
# 安裝相依套件
C:\Users\Alex\anaconda3\envs\nb_ble\python.exe -m pip install -r requirements.txt

# 開圖形介面
C:\Users\Alex\anaconda3\envs\nb_ble\python.exe mi_band_explorer_gui.py

# 開命令列版（探索階段用這支，主控台看得到例外）
C:\Users\Alex\anaconda3\envs\nb_ble\python.exe mi_band_explorer.py

# 三支測試
C:\Users\Alex\anaconda3\envs\nb_ble\python.exe unit_test\test_scan.py
C:\Users\Alex\anaconda3\envs\nb_ble\python.exe unit_test\test_connect.py
C:\Users\Alex\anaconda3\envs\nb_ble\python.exe unit_test\test_notify.py

# 重新產生圖示
C:\Users\Alex\anaconda3\envs\nb_ble\python.exe tools\make_icon.py
```

`test_connect.py` 裡的 `test_decoders()` 是唯一不需要手環在場的測試，四筆基準位元組取自 2026-08-14 的實機讀取。其餘測試都要手環戴在手上、手機的 Zepp Life 關掉——**手環同時只能被一個中央裝置連線**。

打包（只做 onefile）：

```powershell
C:\Users\Alex\anaconda3\envs\nb_ble\python.exe -m PyInstaller MiBand6BleExplorer-onefile.spec `
    --noconfirm --distpath dist\onefile --workpath build\onefile
```

實測（2026-08-31，PyInstaller 6.21.0）：單檔 21.5 MB，第一次啟動 7.4 秒，之後穩定在 4.5 秒上下。沒有另外維護 onedir——探索階段本來就直接跑 `.py`（那樣才看得到主控台），打包出來的版本是拿來交付的，而交付這件事單一檔案贏很多。

**打包的驗收標準是三條，不是 exit 0**（建置失敗與成功都回 0）：

1. 建置紀錄裡 `Library not found` 出現零次。
2. `.exe` 雙擊之後真的跳出視窗。
3. 視窗裡按一次 `Scan` 真的掃得到裝置——這條是本專案特有的，前兩條只證明 Python 那層裝好了，而 BLE 後端整包走 winrt，正好是最可能在打包時被漏掉的部分。

`.spec` 在 `Analysis(...)` 之前把 `<sys.prefix>\Library\bin` 加進 `PATH`；少了那一行，建置照樣成功，`.exe` 會在啟動時死於 `ImportError: DLL load failed while importing _ctypes`。用 `Analysis(pathex=[...])` 代替沒有用：`pathex` 管的是 Python 模組搜尋，DLL 相依走的是 `PATH`。

最後檢查檔案總管、視窗左上角、工作列三處的圖示——這三處是分開決定的。

## Dependencies

| 套件 | 為什麼是它 |
|---|---|
| `bleak==2.0.0` | 跨平台 BLE client，Windows 底下走 WinRT。2.x 的 API 與網路上大量的 0.2x 範例寫法不同，所以版本釘死 |
| `ttkbootstrap==1.19.0` | 讓 tkinter 有現代外觀；亮色用 `litera`、暗色用 `darkly`。只有圖形介面版需要它 |

`requirements.txt` 只有這兩行。BLE 的資料是幾個到二十個位元組，能做的運算就是位元位移跟查表，Python 內建的 `int.from_bytes` 就夠了，所以沒有 numpy、沒有 pandas。把 `ttkbootstrap` 那行拿掉的話，命令列版只靠 `bleak` 一個套件就能跑。

開發期另外需要、但**不進 `requirements.txt`** 的兩個：`pillow`（`tools/make_icon.py` 產圖示用）與 `pyinstaller`（打包用）。

## Configuration

沒有設定檔，沒有金鑰，也沒有任何連外服務——所有資料來自手環，所有輸出寫在使用者指定的資料夾裡。

唯一的本機設定是 `device.local`，用來告訴測試腳本要連哪一支手環：

```ini
# device.local（由 .gitignore 排除，不進版控）
address = XX:XX:XX:XX:XX:XX
```

手環的 MAC 位址屬於裝置識別資訊，不寫死在會進版控的程式碼裡。**這個檔案不存在也要能跑**：`device_config.find_device()` 拿不到位址時會退回用名稱（Mi Band / Xiaomi / Amazfit）掃描，而不是直接失敗。範本見 `device.local.example`。

可調參數寫在程式碼中，需要改就改這幾處（皆在 `mi_band_explorer_gui.py`）：

| 參數 | 位置 | 預設 |
|---|---|---|
| 視窗佔螢幕比例 | `GEOMETRY_LEFT` / `RIGHT` / `TOP` / `BOTTOM` | 0.03 / 0.97 / 0.03 / 0.87 |
| 亮色／暗色主題 | `THEME_LIGHT` / `THEME_DARK` | `litera` / `darkly` |
| 紀錄各語意標籤的顏色 | `LOG_COLORS` | 兩套色票，明暗各一 |
| 佇列輪詢間隔 | `POLL_INTERVAL_MS` | 50 (ms) |
| 紀錄檔預設資料夾 | `LOG_DIR_NAME`（在 `~/Documents` 底下） | `MiBand6_Explorer_Log` |
| 工作列圖示的識別字串 | `APP_ID` | `Aitronics.MiBand6BleExplorer.v1` |
| 掃描秒數／單一讀取的預設 UUID | 介面上的 `Timeout` 與 `Read UUID` 欄位 | 8 秒／`2a28` |

紀錄檔會寫到 `<選定資料夾>/<YYYYMMDD>/MiBand6_Log-<Printed|Interval>_<YYYYMMDD>-<HHMMSS>.txt`。
