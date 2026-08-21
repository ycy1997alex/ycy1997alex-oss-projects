# Crash / unexpected shutdown history check - ASCII only
# Run:  powershell -ExecutionPolicy Bypass -File .\crash-check.ps1
# Some sections need Administrator for full detail.

$ErrorActionPreference = 'SilentlyContinue'
$out = New-Object System.Collections.ArrayList
function W($s){ [void]$out.Add($s); Write-Host $s }
function Line($t){ W ""; W ("=" * 70); W $t; W ("=" * 70) }

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
W ("Generated  : " + (Get-Date))
W ("Admin mode : " + $isAdmin)
$os = Get-CimInstance Win32_OperatingSystem
W ("Last boot  : " + $os.LastBootUpTime)

Line "A. KERNEL-POWER 41 - UNEXPECTED SHUTDOWN / POWER LOSS"
W "(machine lost power or hard-reset without a clean shutdown)"
$e41 = Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'; Id=41} -MaxEvents 40
if ($e41) {
  foreach ($e in $e41) {
    $p = $e.Properties
    $bug = ''
    if ($p.Count -ge 3) { $bug = "BugcheckCode=" + $p[2].Value }
    W ("{0}  {1}" -f $e.TimeCreated, $bug)
  }
  W ("TOTAL: " + $e41.Count)
} else { W "  none found" }

Line "B. BUGCHECK 1001 - BLUE SCREEN (BSOD)"
$e1001 = Get-WinEvent -FilterHashtable @{LogName='System'; Id=1001} -MaxEvents 60 |
         Where-Object { $_.ProviderName -match 'BugCheck|Windows Error Reporting' }
if ($e1001) {
  foreach ($e in $e1001) {
    $m = ($e.Message -replace "`r`n"," " -replace "\s+"," ")
    if ($m.Length -gt 240) { $m = $m.Substring(0,240) }
    W ("{0}  [{1}]" -f $e.TimeCreated, $e.ProviderName)
    W ("    " + $m)
  }
  W ("TOTAL: " + $e1001.Count)
} else { W "  none found" }

Line "C. EVENTLOG 6008 - PREVIOUS SHUTDOWN WAS UNEXPECTED"
$e6008 = Get-WinEvent -FilterHashtable @{LogName='System'; Id=6008} -MaxEvents 40
if ($e6008) {
  foreach ($e in $e6008) {
    $m = ($e.Message -replace "`r`n"," " -replace "\s+"," ")
    if ($m.Length -gt 200) { $m = $m.Substring(0,200) }
    W ("{0}  {1}" -f $e.TimeCreated, $m)
  }
  W ("TOTAL: " + $e6008.Count)
} else { W "  none found" }

Line "D. SHUTDOWN / RESTART TIMELINE (1074 clean, 6005 boot, 6006 clean stop, 109 kernel init shutdown)"
$ids = 1074,6005,6006,109
$ev = Get-WinEvent -FilterHashtable @{LogName='System'; Id=$ids} -MaxEvents 80
if ($ev) {
  foreach ($e in ($ev | Sort-Object TimeCreated -Descending)) {
    $m = ($e.Message -replace "`r`n"," " -replace "\s+"," ")
    if ($m.Length -gt 160) { $m = $m.Substring(0,160) }
    W ("{0}  id={1,-5} {2}" -f $e.TimeCreated, $e.Id, $m)
  }
} else { W "  none found" }

Line "E. CRITICAL LEVEL EVENTS IN SYSTEM LOG (last 90 days)"
$since = (Get-Date).AddDays(-90)
$crit = Get-WinEvent -FilterHashtable @{LogName='System'; Level=1; StartTime=$since} -MaxEvents 60
if ($crit) {
  foreach ($e in $crit) {
    $m = ($e.Message -replace "`r`n"," " -replace "\s+"," ")
    if ($m.Length -gt 180) { $m = $m.Substring(0,180) }
    W ("{0}  id={1,-6} {2}" -f $e.TimeCreated, $e.Id, $e.ProviderName)
    W ("    " + $m)
  }
  W ("TOTAL: " + $crit.Count)
} else { W "  none found" }

Line "F. DISK / STORAGE ERRORS (disk, storahci, nvme, ntfs, volmgr)"
$since = (Get-Date).AddDays(-180)
$dsk = Get-WinEvent -FilterHashtable @{LogName='System'; Level=1,2; StartTime=$since} -MaxEvents 400 |
       Where-Object { $_.ProviderName -match 'disk|storahci|stornvme|nvme|Ntfs|volmgr|Disk' }
if ($dsk) {
  $dsk | Group-Object ProviderName,Id | Sort-Object Count -Descending | ForEach-Object {
    W ("{0,5} x  {1}" -f $_.Count, $_.Name)
  }
  W ""
  W "Most recent 15:"
  foreach ($e in ($dsk | Select-Object -First 15)) {
    $m = ($e.Message -replace "`r`n"," " -replace "\s+"," ")
    if ($m.Length -gt 160) { $m = $m.Substring(0,160) }
    W ("{0}  id={1,-5} {2}" -f $e.TimeCreated, $e.Id, $m)
  }
} else { W "  none found" }

Line "G. HARDWARE ERRORS (WHEA - CPU/PCIe/memory machine checks)"
$whea = Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-WHEA-Logger'} -MaxEvents 40
if ($whea) {
  foreach ($e in $whea) {
    $m = ($e.Message -replace "`r`n"," " -replace "\s+"," ")
    if ($m.Length -gt 200) { $m = $m.Substring(0,200) }
    W ("{0}  id={1,-5} lvl={2}" -f $e.TimeCreated, $e.Id, $e.LevelDisplayName)
    W ("    " + $m)
  }
  W ("TOTAL: " + $whea.Count)
} else { W "  none found  [GOOD - no hardware machine-check errors]" }

Line "H. THERMAL EVENTS (Kernel-Processor-Power / thermal throttling)"
$th = Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Processor-Power'} -MaxEvents 30
if ($th) {
  $th | Group-Object Id | ForEach-Object { W ("{0,5} x  EventID {1}" -f $_.Count, $_.Name) }
  foreach ($e in ($th | Select-Object -First 8)) {
    $m = ($e.Message -replace "`r`n"," " -replace "\s+"," ")
    if ($m.Length -gt 180) { $m = $m.Substring(0,180) }
    W ("{0}  id={1}  {2}" -f $e.TimeCreated, $e.Id, $m)
  }
} else { W "  none found" }

Line "I. APPLICATION CRASHES (Application Error 1000, top offenders, 180 days)"
$since = (Get-Date).AddDays(-180)
$app = Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='Application Error'; StartTime=$since} -MaxEvents 500
if ($app) {
  W "Crash count by application:"
  $app | ForEach-Object { ($_.Properties[0].Value) } | Group-Object | Sort-Object Count -Descending |
    Select-Object -First 20 | ForEach-Object { W ("{0,5} x  {1}" -f $_.Count, $_.Name) }
  W ""
  W "Most recent 10:"
  foreach ($e in ($app | Select-Object -First 10)) {
    W ("{0}  {1}  mod={2}" -f $e.TimeCreated, $e.Properties[0].Value, $e.Properties[3].Value)
  }
  W ("TOTAL: " + $app.Count)
} else { W "  none found" }

Line "J. APP HANGS (Application Hang 1002, 180 days)"
$hang = Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='Application Hang'; StartTime=$since} -MaxEvents 200
if ($hang) {
  $hang | ForEach-Object { ($_.Properties[0].Value) } | Group-Object | Sort-Object Count -Descending |
    Select-Object -First 15 | ForEach-Object { W ("{0,5} x  {1}" -f $_.Count, $_.Name) }
  W ("TOTAL: " + $hang.Count)
} else { W "  none found" }

Line "K. MEMORY DUMP FILES"
foreach ($p in @("$env:WINDIR\MEMORY.DMP", "$env:WINDIR\Minidump")) {
  if (Test-Path $p) {
    Get-ChildItem $p -File -EA SilentlyContinue | Sort-Object LastWriteTime -Descending |
      Select-Object -First 25 | ForEach-Object {
        W ("{0}  {1,10} KB  {2}" -f $_.LastWriteTime, [math]::Round($_.Length/1KB,0), $_.FullName)
      }
    if ((Get-Item $p) -is [System.IO.FileInfo]) {
      $f = Get-Item $p
      W ("{0}  {1,10} KB  {2}" -f $f.LastWriteTime, [math]::Round($f.Length/1KB,0), $f.FullName)
    }
  } else { W ("  not present: " + $p) }
}

Line "L. USER-MODE CRASH DUMPS"
$cd = "$env:LOCALAPPDATA\CrashDumps"
if (Test-Path $cd) {
  Get-ChildItem $cd -File | Sort-Object LastWriteTime -Descending | Select-Object -First 30 | ForEach-Object {
    W ("{0}  {1,9} MB  {2}" -f $_.LastWriteTime, [math]::Round($_.Length/1MB,1), $_.Name)
  }
} else { W "  none" }

Line "M. WINDOWS ERROR REPORTING - RECENT REPORTS"
$wer = "$env:LOCALAPPDATA\Microsoft\Windows\WER\ReportArchive"
if (Test-Path $wer) {
  Get-ChildItem $wer -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 25 | ForEach-Object {
    W ("{0}  {1}" -f $_.LastWriteTime, $_.Name)
  }
} else { W "  none" }

Line "N. RELIABILITY SCORE HISTORY (last 30 entries)"
Get-CimInstance Win32_ReliabilityStabilityMetrics -EA SilentlyContinue |
  Sort-Object TimeGenerated -Descending | Select-Object -First 30 | ForEach-Object {
    W ("{0}  score={1}" -f $_.TimeGenerated, [math]::Round($_.SystemStabilityIndex,2))
  }

Line "O. BATTERY / POWER SOURCE HEALTH"
$bat = Get-CimInstance Win32_Battery
if ($bat) {
  foreach ($b in $bat) {
    W ("Battery: {0}  status={1}  estCharge={2} pct  design={3}" -f $b.Name, $b.BatteryStatus, $b.EstimatedChargeRemaining, $b.DesignVoltage)
  }
} else { W "  no battery reported (desktop or battery removed)" }

Line "END"
$dest = Join-Path $PSScriptRoot 'crash-report.txt'
$out | Out-File -FilePath $dest -Encoding ASCII
Write-Host ""
Write-Host ("Saved to: " + $dest) -ForegroundColor Green