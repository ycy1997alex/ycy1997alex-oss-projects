# Diabetes_Data_Origin.xlsx 複製一份，加上第三張 "Boostrapping" 分頁。
# 走 Excel COM 而不是 openpyxl：原本兩張表的樣式與凍結窗格要原封不動，
# 而且 Form control 的微調按鈕只有 COM 放得進去。
#
# 用法： powershell -ExecutionPolicy Bypass -File make_bootstrapping_sheet.ps1

$ErrorActionPreference = "Stop"

$here   = Split-Path -Parent $MyInvocation.MyCommand.Path
$source = Join-Path $here "Diabetes_Data_Origin.xlsx"
$target = Join-Path $here "Diabetes_Data_Origin_Bootstrapping.xlsx"

$MAX_N = 2000   # 抽樣次數上限，也是明細表的列數
$FIRST_ROW = 14 # 明細表第一列（第 13 列是欄名）
$LAST_ROW = $FIRST_ROW + $MAX_N - 1
$COLS = 11      # Data 分頁的欄數：age…target
# 明細表資料從 C 欄開始（A=第 i 次、B=抽中第幾筆），與 Data 的 A…K 差兩欄，
# 所以每一個查表公式的欄位位移都是 -2
$LAST_COL = 2 + $COLS

if (Test-Path $target) { Remove-Item $target -Force }
Copy-Item $source $target

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false

try {
    $wb = $excel.Workbooks.Open($target)
    $excel.Calculation = -4135   # xlCalculationManual（要先有活頁簿才設得動），
                                 # 免得亂數在建表過程中一直重算
    $ws = $wb.Worksheets.Add([System.Type]::Missing, $wb.Worksheets.Item($wb.Worksheets.Count))
    $ws.Name = "Boostrapping"

    # ── 說明 ──────────────────────────────────────────────
    $ws.Range("A1").Value2 = "Bootstrapping 抽樣示範"
    $ws.Range("A1").Font.Size = 16
    $ws.Range("A1").Font.Bold = $true

    $ws.Range("A2").Value2 = "母體是 Data 分頁的 442 筆資料。每一列是一次抽樣：隨機挑一個列號，把那一筆的整列資料抄過來，然後放回去 —— 所以同一筆可能被抽中好幾次。抽 N 次，就得到 N 筆重抽出來的樣本。"
    $ws.Range("A3").Value2 = "按 F9 重新抽樣，下面每一個數字都會換一組。同一份資料、同樣的做法，每次結果都略有不同 —— 這就是 bootstrap 在量的東西。"

    # ── 參數 ──────────────────────────────────────────────
    $ws.Range("A5").Value2 = "抽樣次數 N"
    $ws.Range("C5").Value2 = 1000
    $ws.Range("A6").Value2 = "（右邊的微調按鈕可以改）"
    $ws.Range("A5:A6").Font.Bold = $true
    $ws.Range("C5").Interior.Color = 15849925        # 淡藍：可以改的那一格

    # ── 統計對照：每一欄的抽樣結果 vs 母體，欄位與下面的明細表對齊 ──
    $ws.Range("A8").Value2 = "N 次抽樣平均"
    $ws.Range("A9").Value2 = "母體平均（442 筆）"
    $ws.Range("A10").Value2 = "N 次抽樣標準差"
    $ws.Range("A11").Value2 = "母體標準差（442 筆）"
    $ws.Range("A8:A11").Font.Bold = $true

    $statCols = $ws.Range($ws.Cells.Item(8, 3), $ws.Cells.Item(11, $LAST_COL))
    $ws.Range($ws.Cells.Item(8, 3), $ws.Cells.Item(8, $LAST_COL)).FormulaR1C1 =
        "=AVERAGE(R${FIRST_ROW}C:R${LAST_ROW}C)"
    $ws.Range($ws.Cells.Item(9, 3), $ws.Cells.Item(9, $LAST_COL)).FormulaR1C1 =
        "=AVERAGE(Data!R2C[-2]:R443C[-2])"
    $ws.Range($ws.Cells.Item(10, 3), $ws.Cells.Item(10, $LAST_COL)).FormulaR1C1 =
        "=STDEV.S(R${FIRST_ROW}C:R${LAST_ROW}C)"
    $ws.Range($ws.Cells.Item(11, 3), $ws.Cells.Item(11, $LAST_COL)).FormulaR1C1 =
        "=STDEV.S(Data!R2C[-2]:R443C[-2])"
    $statCols.NumberFormat = "0.000"
    $ws.Range($ws.Cells.Item(8, 1), $ws.Cells.Item(8, $LAST_COL)).Interior.Color = 13434879
    $ws.Range($ws.Cells.Item(10, 1), $ws.Cells.Item(10, $LAST_COL)).Interior.Color = 13434879

    # ── 明細表 ────────────────────────────────────────────
    $ws.Cells.Item($FIRST_ROW - 1, 1).Value2 = "第 i 次"
    $ws.Cells.Item($FIRST_ROW - 1, 2).Value2 = "抽中第幾筆"
    # 欄名直接引用 Data 的標題列，改資料欄名時這裡跟著變
    $ws.Range($ws.Cells.Item($FIRST_ROW - 1, 3), $ws.Cells.Item($FIRST_ROW - 1, $LAST_COL)).FormulaR1C1 =
        "=Data!R1C[-2]"
    $headerRow = $ws.Range($ws.Cells.Item($FIRST_ROW - 1, 1), $ws.Cells.Item($FIRST_ROW - 1, $LAST_COL))
    $headerRow.Font.Bold = $true
    $headerRow.Interior.Color = 15132390
    $headerRow.HorizontalAlignment = -4108

    # 超過 N 的列留白，改 N 時表格會自己伸縮
    $ws.Range($ws.Cells.Item($FIRST_ROW, 1), $ws.Cells.Item($LAST_ROW, 1)).FormulaR1C1 =
        "=IF(ROW()-$($FIRST_ROW - 1)<=R5C3,ROW()-$($FIRST_ROW - 1),"""")"
    # 先抽列號再查整列，資料欄才會來自同一筆（每一格各寫一次 RANDBETWEEN 會各抽各的）
    $ws.Range($ws.Cells.Item($FIRST_ROW, 2), $ws.Cells.Item($LAST_ROW, 2)).FormulaR1C1 =
        "=IF(RC1="""","""",RANDBETWEEN(1,442))"
    $ws.Range($ws.Cells.Item($FIRST_ROW, 3), $ws.Cells.Item($LAST_ROW, $LAST_COL)).FormulaR1C1 =
        "=IF(RC2="""","""",INDEX(Data!R2C[-2]:R443C[-2],RC2))"

    $ws.Range($ws.Cells.Item($FIRST_ROW, 3), $ws.Cells.Item($LAST_ROW, $LAST_COL)).NumberFormat = "0.0###"
    $ws.Range("A:A").ColumnWidth = 22
    $ws.Range("B:B").ColumnWidth = 12
    $ws.Range($ws.Cells.Item(1, 3), $ws.Cells.Item(1, $LAST_COL)).EntireColumn.ColumnWidth = 9

    # ── 一顆微調按鈕（Form control，不需要巨集）──────────
    $spinN = $ws.Shapes.AddFormControl(9, 180, 62, 16, 26)   # 9 = xlSpinner
    $spinN.ControlFormat.Min = 100
    $spinN.ControlFormat.Max = $MAX_N
    $spinN.ControlFormat.SmallChange = 100
    $spinN.ControlFormat.LinkedCell = "`$C`$5"
    $spinN.ControlFormat.Value = 1000   # 綁定當下會把微調鈕的現值寫進 C5，所以預設值要在這裡給

    # ── 凍結窗格：欄名以上與左邊兩欄固定 ────────────────
    $ws.Activate()
    $excel.ActiveWindow.FreezePanes = $false
    $ws.Range("C$FIRST_ROW").Select()
    $excel.ActiveWindow.FreezePanes = $true
    $ws.Range("A1").Select()

    $excel.Calculation = -4105   # xlCalculationAutomatic
    $excel.CalculateFull()
    $wb.Save()
    $wb.Close($true)
    Write-Output "written: $target"
}
finally {
    $excel.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
}
