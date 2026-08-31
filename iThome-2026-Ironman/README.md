# iThome-2026-Ironman

繁體中文 | [English](README.en.md)

## Overview

這裡是 iThome 2026 鐵人賽系列文《三個介面，一套工作流？30 天 Claude 跨領域實戰：從 claude.ai、Claude Desktop 到 Claude Code》的**產出物存放區**。文章發表在 ithelp.ithome.com.tw，這個資料夾放的是文章裡提到、但塞在文章內看不清楚也帶不走的東西：程式碼、Office 檔案、打包好的 `.exe`、操作截圖。

每天的文章會連到這裡對應的資料夾，方向是單向的——這裡的檔案是**文章的佐證**，不是獨立產品。沒有統一架構，也沒有共用的建置流程，各資料夾自成一格。想知道某個檔案為什麼長這樣、當初踩到什麼坑，答案在文章裡，不在程式碼裡。

系列共 30 天，但只有需要外連檔案的日子才會開資料夾，所以編號是跳的。跨多天的程式碼與檔案另外收在 `Prj_N/` 底下，不綁單一天。

若資料夾附了自己的 `README.md` 就以那份為準，說明比這裡詳細得多。其餘資料夾純粹是檔案存放，說明在文章裡。

## Setup & run

沒有整包的安裝或建置步驟，各資料夾各自為政。

**打包好的執行檔**（Windows，不需要 Python）：

```
.exe
```

下載後雙擊即可。單檔（onefile）版第一次啟動要解壓縮，會慢幾秒，屬正常。

**從原始碼跑 Python 專案**：

```bash
# 以 Prj_2 為例，其餘資料夾同理
cd Prj_2
pip install -r requirements.txt
python main.py

# 不開介面、直接跑完整流程驗證環境
python main.py --selftest
```

Day06 的模擬沒有 `requirements.txt`，只要 `numpy` / `scipy` / `matplotlib`：

```bash
cd Day06_20260820
pip install numpy scipy matplotlib
python descent_hda.py --no-plot
```

**PowerShell 腳本**（Day07）只讀取系統資訊、不寫入任何東西：

```powershell
powershell -ExecutionPolicy Bypass -File .\perf-check.ps1
powershell -ExecutionPolicy Bypass -File .\crash-check.ps1
```

Office 檔案、`.png`、`.html` 都是直接開啟就好，`landing_site_plate.html` 離線可用。

## Dependencies

依資料夾而異，以各自的 `requirements.txt` 為準（`Prj_1/*/requirements.txt`、`Prj_2/requirements.txt`）。Python 專案都在 Windows + Python 3.12／3.13 上跑過，用到的大致是這幾類：

- **數值與統計**：numpy、scipy、pandas、scikit-learn、statsmodels
- **繪圖**：matplotlib、seaborn
- **Office 讀寫**：openpyxl、XlsxWriter、python-docx、python-pptx
- **桌面介面與打包**：ttkbootstrap、Pillow、PyInstaller

## Configuration

沒有設定檔，也沒有環境變數要設。

## License

沿用 repo 根目錄的 [MIT License](../LICENSE)。文章內容本身的著作權屬於作者，程式碼與檔案則依 MIT 授權使用。

> 註：`Day16_20260830/` 底下的股市週報檔案是「把讀過的內容變成簡報」的流程示範，資料來源為公開財經節目的摘要，不構成投資建議。
