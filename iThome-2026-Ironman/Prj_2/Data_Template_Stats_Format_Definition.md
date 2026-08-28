# 資料格式說明文件（Data Template Stats — Format Definition）

本文件說明 `Data_Template_Stats.xlsx` 的檔案格式，以及 `Definition` 與 `Data` 兩個工作表該怎麼填。

---

## 一、Excel 檔案結構

| 工作表名稱 | 用途 |
|-----------|------|
| `Definition` | 資料的「說明書」，定義每個欄位的角色、類型、合理範圍等 |
| `Data` | 實際的分析資料，每列一筆樣本 |

> **重要**：`Definition` 與 `Data` 的特徵欄位名稱必須完全一致（大小寫、底線、空格都算），讀取時會比對，不符即報錯。

> 檔案只有這兩張工作表。資料出處寫在本文件第六節，不放進活頁簿裡。

兩個工作表都凍結在 `B2`（第一列與第一欄固定），標題列為粗體。

---

## 二、`Definition` 工作表詳解

### 2.1 整體結構

`Definition` 採**轉置（Transposed）格式**：**欄**代表特徵，**列**代表屬性。本樣板為 7 列 × 11 欄（`A1:K7`）。

| 列次 | 列名（第 0 欄） | 說明 | 本樣板填寫情形 |
|------|----------------|------|---------------|
| 第 0 列 | `Feature` | 欄位名稱（即 `Data` 的欄標題） | 10 個欄位名 |
| 第 1 列 | `Feature_Type` | 欄位角色（Info / Input / Result） | 1 Info、6 Input、3 Result |
| 第 2 列 | `Priority` | 分析優先級（High / 留空） | 9 個分析欄全填 `High`，`ID` 留空 |
| 第 3 列 | `Data_Type` | 資料類型（Continuous / Categorical / None） | `ID` 為 `None`，其餘 9 欄全 `Continuous` |
| 第 4 列 | `Continuity` | 連續型的合理範圍，格式 `最小值, 最大值` | **整列留空** |
| 第 5 列 | `Category` | 類別型的合法類別，格式 `類別1, 類別2, ...` | **整列留空**（本樣板無類別型欄位） |
| 第 6 列 | `Note` | 備注（選填） | 填入中文名稱、原始變項名與所屬構念 |

> 第 0 **欄**（最左欄）是列標籤（Feature、Feature_Type…），真正的特徵定義從第 1 欄（B 欄）開始。

### 2.2 `Feature_Type` 欄位角色

| 值（前綴） | 含義 | 程式行為 |
|-----------|------|---------|
| `Info_XX` | 資訊欄，如 ID、日期 | **不參與分析** |
| `Input_XX` | 輸入特徵（預測變項） | 模型的解釋變項（X） |
| `Result_XX` | 目標變項（結果變項） | 模型的預測目標（Y） |

`XX` 為兩位數編號，僅作識別，數字大小不影響分析順序。

### 2.3 `Data_Type` 資料類型

| 值 | 含義 | 對應行為 |
|----|------|---------|
| `Continuous` | 連續型數值 | 輸入端標準化；結果端走迴歸任務 |
| `Categorical` | 類別型 | 輸入端 One-Hot 編碼；結果端走分類任務 |
| `None` | 非分析欄（Info 欄使用） | 完全忽略 |

**本樣板 9 個分析欄全部是 `Continuous`**，因此不會出現任何分類任務；所有 Result 都是迴歸。

### 2.4 `Continuity` 與 `Category`

- `Continuity` 只對 `Continuous` 欄有意義，`Category` 只對 `Categorical` 欄有意義。
- 兩者都是**說明性資訊**，不會強制過濾超出範圍或不在清單中的值。
- 本樣板兩列皆留空——留空不影響分析，實際的數值範圍與類別空間由 `Data` 的內容決定。

---

## 三、`Data` 工作表詳解

- 範圍 `A1:J501`：第一列為欄位名稱（與 `Definition` 第 0 列相同），第 2 列起每列一筆樣本，共 **500 筆 × 10 欄**。
- 缺失值填字串 `NA`（讀取時轉為 `NaN`）。**本樣板沒有任何缺失值**，500 筆全部可用。
- 數值欄未套用特定數值格式（`General`），小數位數不固定。

---

## 四、欄位說明

### 4.1 非分析欄（Info，共 1 欄）

| 欄位名稱 | Feature_Type | Data_Type | 說明 |
|---------|-------------|-----------|------|
| `ID` | Info_01 | None | 樣本編號，字串。本樣板格式為 `SN` + 年月（`202608`）+ 三位流水號，`SN202608001` ~ `SN202608500`，500 筆無重複 |

### 4.2 輸入特徵（Input，共 6 欄，全為 Continuous）

| 欄位名稱 | Feature_Type | Priority | 說明 |
|---------|-------------|---------|------|
| `U_motiv` | Input_01 | High | 學習動機（`motiv`，Motivation） |
| `U_harm` | Input_02 | High | 人際和諧（`harm`，Harmony） |
| `U_stabi` | Input_03 | High | 情緒穩定度（`stabi`，Stability） |
| `U_ppsych` | Input_04 | High | 家長負向心理狀態（`ppsych`，Negative Parental Psychology），數值越高風險越高 |
| `U_ses` | Input_05 | High | 社經地位（`ses`，SES） |
| `U_verbal` | Input_06 | High | 語文智力（`verbal`，Verbal IQ） |

### 4.3 目標變項（Result，共 3 欄，全為 Continuous）

| 欄位名稱 | Feature_Type | Priority | 說明 |
|---------|-------------|---------|------|
| `U_read` | Result_01 | High | 閱讀能力（`read`，Reading） → **迴歸任務** |
| `U_arith` | Result_02 | High | 算術能力（`arith`，Arithmetic） → **迴歸任務** |
| `U_spell` | Result_03 | High | 拼字能力（`spell`，Spelling） → **迴歸任務** |

> **`Priority` 不影響分析**：決定欄位是否參與的是 `Feature_Type`。本樣板 9 個分析欄一律填 `High`，實質上等同沒有區分。

---

## 五、樣板資料特性

| 項目 | 值 |
|------|----|
| 筆數 | 500 |
| 欄數 | 10（1 Info + 6 Input + 3 Result） |
| 缺失值 | 0 |
| 類別型欄位 | 0 |

9 個數值欄都已標準化過——每一欄的平均數皆為 0、標準差皆為 9.99（可視為 z 分數 × 10 的量尺）：

| 欄位 | 最小值 | 最大值 | 平均 | 標準差 |
|------|-------|-------|------|-------|
| `U_motiv` | -33.97 | 26.47 | 0.00 | 9.99 |
| `U_harm` | -32.98 | 31.16 | 0.00 | 9.99 |
| `U_stabi` | -25.92 | 29.63 | 0.00 | 9.99 |
| `U_ppsych` | -31.09 | 33.28 | 0.00 | 9.99 |
| `U_ses` | -32.14 | 29.10 | 0.00 | 9.99 |
| `U_verbal` | -35.26 | 31.70 | 0.00 | 9.99 |
| `U_read` | -32.84 | 27.61 | 0.00 | 9.99 |
| `U_arith` | -26.70 | 33.05 | 0.00 | 9.99 |
| `U_spell` | -31.36 | 26.93 | 0.00 | 9.99 |

---

## 六、資料來源

本樣板的數值不是隨手生成的，取自 SEM 教材常用的一組公開資料。

**原始文獻**

> Worland, J., Weeks, D. G., Janes, C. L., & Strock, B. D. (1984). Intelligence, classroom behavior, and academic achievement in children at high and low risk for psychopathology: A structural equation analysis. *Journal of Abnormal Child Psychology*, 12(3), 437–454.
>
> DOI: https://doi.org/10.1007/BF00910658　·　原研究樣本為 158 名兒童（高／中／低精神病理風險），論文中發表了 12 個觀察變項的相關矩陣。

**實際使用的檔案**

UCLA OARC（原 IDRE）Mplus class notes 提供的 `worland.dat`，500 筆 × 12 欄，由上述論文已發表的相關矩陣所描述的分配隨機抽出，12 欄皆標準化為平均 0、標準差 1。

- 資料檔：https://stats.idre.ucla.edu/wp-content/uploads/2018/01/worland.dat
- 課程說明：https://stats.oarc.ucla.edu/mplus/seminars/mplus-class-notes/cfa/

同一組相關矩陣也是 Kline, R. B. *Principles and Practice of Structural Equation Modeling* 的 SEM 教學範例。

**本樣板做了什麼**

原始 12 欄取其中 9 欄，對應 SEM 教材慣用的三個潛在因素；`extra`、`vissp`、`mem` 三欄未納入。數值一律乘以 10（平均 0、標準差 10），除此之外未做任何變更。`ID` 是本樣板自行編製的流水號，不是原始資料欄位。

| 潛在因素 | 原始欄位 | 本樣板欄位 |
|---|---|---|
| 適應（Adjustment） | `motiv` / `harm` / `stabi` | `U_motiv` / `U_harm` / `U_stabi` |
| 風險（Risk） | `ppsych` / `ses` / `verbal` | `U_ppsych` / `U_ses` / `U_verbal` |
| 學業成就（Achievement） | `read` / `arith` / `spell` | `U_read` / `U_arith` / `U_spell` |

> **這組三因素分法對應的是九變項版本。** 完整的十二變項版本在 UCLA 的講義裡是四個因素：`adjust`（`motiv` / `extra` / `harm` / `stabi`，教師對課堂表現的評定）、`family`（`ppsych` / `ses`）、`cog`（`verbal` / `vissp` / `mem`，標準化認知測驗）、`achieve`（`read` / `arith` / `spell`）。兩種分法都有人用，差別在於九變項版把 `verbal` 併進「風險」，十二變項版把它留在「認知能力」。

### 6.1 欄位中文名稱對照

中文名稱是本樣板自行翻譯的，英文標籤取自上述教學文件。同樣的對照也寫在 `Definition` 的 `Note` 列。

| 本樣板欄位 | 原始欄位 | 英文標籤 | 中文 | 構念 |
|---|---|---|---|---|
| `U_motiv` | `motiv` | Motivation | 學習動機 | 課堂適應（教師評定） |
| `U_harm` | `harm` | Harmony | 人際和諧 | 課堂適應（教師評定） |
| `U_stabi` | `stabi` | Stability | 情緒穩定度 | 課堂適應（教師評定） |
| `U_ppsych` | `ppsych` | Negative Parental Psychology | 家長負向心理狀態 | 家庭風險 |
| `U_ses` | `ses` | SES | 社經地位 | 家庭風險 |
| `U_verbal` | `verbal` | Verbal IQ | 語文智力 | 認知能力測驗 |
| `U_read` | `read` | Reading | 閱讀能力 | 學業成就 |
| `U_arith` | `arith` | Arithmetic | 算術能力 | 學業成就 |
| `U_spell` | `spell` | Spelling | 拼字能力 | 學業成就 |

> `harm`（Harmony）屬於**課堂適應**，是老師對學生課堂表現的評定，跟家庭沒有關係；家庭那一組只有 `ppsych` 與 `ses` 兩欄。`ppsych` 數值越高代表家長精神病理的程度越高，也就是風險越高。

> 因為資料是照著已發表的相關矩陣生成、抽樣誤差已被消去的，`Data` 算出來的相關係數會剛好等於原文發表的值（36 組兩兩相關與三位小數的誤差都在 1e-7 以內）。這個性質很適合拿來驗證程式算得對不對，但也代表 p 值衡量的是生成設定而非真實抽樣，**不應解讀為對真實母體的推論證據**。

---

## 七、如何準備自己的資料

1. **複製樣板**並重新命名。
2. **修改 `Definition`**：
   - 第 0 列（`Feature`）填欄位名稱。
   - 第 1 列（`Feature_Type`）指定角色（`Info_XX` / `Input_XX` / `Result_XX`）。
   - 第 3 列（`Data_Type`）填 `Continuous` 或 `Categorical`，Info 欄填 `None`。
   - 第 4、5、6 列（`Continuity` / `Category` / `Note`）選填；本樣板的 `Continuity` 與 `Category` 留空，`Note` 填的是原始變項名稱，兩種寫法都是合法狀態。
3. **修改 `Data`**：
   - 第一列欄位名稱需與 `Definition` 第 0 列**完全一致**。
   - 第 2 列起填資料，缺失值寫 `NA`。
   - 訓練資料：Input 與 Result 都要有值。
   - 推論資料：Input 必須齊備；Result 可整欄不放、只填部分列或全部填滿（見 3.1）。
4. **注意事項**：
   - `Definition` 不得有重複欄位名稱。
   - `Feature_Type` 不含 `Input` 或 `Result` 的欄位不會進入分析。
   - SEM Pipeline 需要至少 **2 個連續型 Input**；Prediction Pipeline 建議樣本數 ≥ 50，SEM Pipeline 建議 ≥ 100。本樣板 500 筆均滿足。
