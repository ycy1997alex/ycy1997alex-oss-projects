# demo — 互動示範頁

iThome 2026 鐵人賽文章裡用到的互動示範頁，每一個都是**單一 HTML 檔**：CSS 與 JS
全部 inline，沒有建置步驟、沒有外部相依，直接用瀏覽器打開就能跑。

原本放在個人網站的 `static/demo/` 底下，2026-08-31 移到這裡集中管理。舊網址
（`https://ycy1997alex.github.io/demo/<name>/`）保留為轉址頁，已發布文章裡的連結不受影響。

## 線上位置

由 GitHub Pages 提供，網址前綴為：

```
https://ycy1997alex.github.io/ycy1997alex-oss-projects/iThome-2026-Ironman/demo/
```

| 資料夾 | 頁面 | 出自 |
|---|---|---|
| `flight-simulation/` | 飛機起飛與降落模擬 | Day 05 |
| `attention-battery/` | 注意力測驗組 | Day 05 |
| `dmn-glassbrain/` | 預設模式網路玻璃腦 | Day 05 |
| `prompt-yt-financial/` | 投資理財 YT 影片摘要提示詞 | Day 04 |

> `prompt-yt-financial` 在個人網站上的舊資料夾名是 `prompt_yt_financial`（底線），
> 搬過來時一併改成連字號，與其他三個一致。舊網址仍可正常轉址。

## 密碼

四個頁面都需要密碼才能開啟。內容以 **AES-GCM-256** 加密，金鑰由 **PBKDF2-SHA256**
跑 250,000 輪導出，密碼不正確就解不開——不是把內容藏起來的假保護。密碼寫在對應的
iThome 文章裡。

每頁都掛了 `noindex, nofollow`，不會被搜尋引擎收錄。

## 執行方式

沒有建置流程，直接開檔即可：

```
start flight-simulation/index.html
```

解密用的 `crypto.subtle` 需要 secure context，而 `file://` 依規範屬於
potentially trustworthy origin，所以本機直接開檔也能正常解密。若要模擬線上環境，
也可以起一個本機伺服器：

```
python -m http.server 8000
```

然後開 `http://localhost:8000/flight-simulation/`。
