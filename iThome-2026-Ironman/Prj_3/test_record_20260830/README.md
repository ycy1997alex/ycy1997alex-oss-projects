# 實測紀錄 — 2026-08-30

Day 19 第 8 節那一輪實測的原始輸出與腳本。對象是同一支小米手環 6，全程唯讀：沒有寫入任何 characteristic，沒有嘗試華米認證。

## 環境

為了確認 `requirements.txt` 那兩行真的夠用，這一輪開了一個乾淨的 conda 環境重跑：

| 項目 | 版本 |
|---|---|
| OS | Windows 11 |
| Python | 3.13.15 |
| bleak | 2.0.0 |
| ttkbootstrap | 1.19.0 |

`pip install -r requirements.txt` 之外沒有裝任何東西（Pillow 是 ttkbootstrap 帶進來的相依）。

## 檔案

| 檔案 | 內容 |
|---|---|
| `01_read_session.md` | 掃描 → 連線 → 列舉 GATT → 讀取所有可讀特徵 → 摘要 → 斷線的完整紀錄 |
| `02_notify_session.md` | 訂閱所有可訂閱特徵，監看 120 秒，期間戴著手環走動 |
| `03_gui_light.png` | 圖形介面亮色，跑完摘要之後 |
| `04_gui_gatt_tree.png` | GATT 結構分頁展開 |
| `05_gui_dark.png` | 圖形介面暗色 |
| `06_gui_log.txt` | 上面那一輪圖形介面的通訊紀錄 |
| `07_gui_steps.txt` | 腳本代按了哪些按鈕、什麼時候按的 |
| `run_read_session.py` | 產生 `01_` 的腳本 |
| `run_notify_session.py` | 產生 `02_` 的腳本 |
| `run_gui_capture.py` | 產生 `03_` 到 `07_` 的腳本 |
| `diag_scan.py` | 診斷用的長時間掃描，用來確認手環到底有沒有在廣播 |

## 這些腳本跟主程式的關係

`mi_band_explorer.py` 的選單是互動式的，沒辦法在無人看顧的情況下跑完一輪。這三支腳本把選單那幾個動作按同樣的順序自動跑一遍，**解碼與 UUID 對照一律 `import` 自 `mi_band_explorer.py`，沒有再複製一份**，這樣紀錄檔跟工具本身對同一段位元組的解讀不會分歧。

`run_gui_capture.py` 也不是另外畫一個假畫面：它建出來的是 `mi_band_explorer_gui.main()` 裡那同一組 `Window` / `ExplorerView` / `ExplorerPresenter`，差別只在按鈕由腳本代按，最後照 `presenter.close()` 的五步流程關閉。

## 主要結果

- 掃描：8 秒沒掃到手環，20 秒掃到，RSSI −53 dBm
- 連線：9.9 秒
- GATT：11 個服務、46 個特徵、28 個描述元
- 讀取：29 個特徵帶 `read`，25 個成功（其中 7 個回來是零位元組）、4 個被拒，全部是 `0x02 Read Not Permitted`
- 訂閱：26 個候選，24 個成功；2 個失敗，錯誤形狀不同（`2A37` 是 ATT 的 `0x03 Write Not Permitted`，華米 `0014` 是 WinRT 的 `Access Denied`）
- 監看 120 秒：55 個封包，全部來自華米 `0007`，步數 73 → 182，間隔中位數 0.84 秒

## 隱私

紀錄檔與截圖裡的序號（`2A25`）與 MAC 位址都經過遮蔽。遮的是呈現，程式讀到的仍是完整值。

遮蔽做在兩個地方：`run_gui_capture.py` 的 `redact()` 在截圖前就地改畫面上的字串，`run_read_session.py` 的 `scrub()` 則在寫檔前掃過整份輸出。後者不能只遮「顯示位址」那幾個欄位，因為同一組位元組還會以十六進位的形式出現在廣播的廠商資料尾端，以及 `2A23` System ID 的 EUI-64 裡。

手環的位址本身放在專案根目錄的 `device.local`（由 `.gitignore` 排除），不寫死在任何會進版控的檔案裡；範本見 `device.local.example`。

## 這是單次觀察

同一支程式對同一支手環跑兩次不一定一樣。這裡的每一個數字都只代表 2026-08-30 這一輪，不是小米手環 6 的通則，也不是可重複的實驗結果。「8 秒掃不到、20 秒掃得到」這種事下一次跑就可能反過來。
