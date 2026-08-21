# Windows Performance Check - ASCII only, safe for any encoding
# Usage: powershell -ExecutionPolicy Bypass -File .\check-perf.ps1

$ErrorActionPreference = 'SilentlyContinue'
$out = New-Object System.Collections.ArrayList
function W($s){ [void]$out.Add($s); Write-Host $s }
function Line($t){ W ""; W ("=" * 62); W $t; W ("=" * 62) }

Line "1. SYSTEM"
$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
$up = (Get-Date) - $os.LastBootUpTime
W ("Model        : {0} {1}" -f $cs.Manufacturer, $cs.Model)
W ("Windows      : {0} build {1}" -f $os.Caption, $os.BuildNumber)
W ("Uptime       : {0}d {1}h {2}m" -f $up.Days, $up.Hours, $up.Minutes)
if ($up.Days -ge 7) { W "  [WARN] Uptime over 7 days - consider reboot" }

Line "2. MEMORY"
$totalGB = [math]::Round($cs.TotalPhysicalMemory/1GB,1)
$freeGB  = [math]::Round($os.FreePhysicalMemory/1MB,1)
$usedGB  = [math]::Round($totalGB - $freeGB,1)
$pct     = [math]::Round(($usedGB/$totalGB)*100,1)
W ("Total RAM    : {0} GB" -f $totalGB)
W ("Used         : {0} GB ({1} pct)" -f $usedGB, $pct)
W ("Free         : {0} GB" -f $freeGB)
if ($pct -ge 90) { W "  [CRIT] RAM nearly full - likely the main cause" }
elseif ($pct -ge 80) { W "  [WARN] RAM high" }
else { W "  [OK] RAM usage normal" }
W ""
W "DIMM slots:"
Get-CimInstance Win32_PhysicalMemory | ForEach-Object {
  W ("  {0,-16} {1,4} GB  {2} MHz  {3}" -f $_.DeviceLocator, [math]::Round($_.Capacity/1GB,0), $_.ConfiguredClockSpeed, $_.Manufacturer)
}
W ""
$pf = Get-CimInstance Win32_PageFileUsage
if ($pf) {
  W ("Pagefile     : current {0} MB / peak {1} MB  [{2}]" -f $pf.CurrentUsage, $pf.PeakUsage, $pf.Name)
  if ($pf.PeakUsage -gt 4000) { W "  [WARN] High pagefile peak - system ran out of RAM before" }
}

Line "3. TOP 15 BY MEMORY"
W ("{0,-32} {1,10} {2,6}" -f "Process", "RAM_MB", "Count")
Get-Process | Group-Object ProcessName | ForEach-Object {
  New-Object psobject -Property @{
    PName = $_.Name
    MB    = [math]::Round((($_.Group | Measure-Object WorkingSet64 -Sum).Sum)/1MB,0)
    N     = $_.Count
  }
} | Sort-Object MB -Descending | Select-Object -First 15 | ForEach-Object {
  W ("{0,-32} {1,10} {2,6}" -f $_.PName, $_.MB, $_.N)
}

Line "4. TOP 10 BY CPU TIME"
W ("{0,-32} {1,10}" -f "Process", "CPU_sec")
Get-Process | Group-Object ProcessName | ForEach-Object {
  New-Object psobject -Property @{
    PName = $_.Name
    CPU   = [math]::Round((($_.Group | Measure-Object CPU -Sum).Sum),0)
  }
} | Sort-Object CPU -Descending | Select-Object -First 10 | ForEach-Object {
  W ("{0,-32} {1,10}" -f $_.PName, $_.CPU)
}

Line "5. CURRENT LOAD"
$cpu = (Get-CimInstance Win32_Processor | Measure-Object LoadPercentage -Average).Average
W ("CPU load     : {0} pct" -f $cpu)
$d = (Get-Counter '\PhysicalDisk(_Total)\% Disk Time').CounterSamples.CookedValue
if ($d -ne $null) {
  W ("Disk busy    : {0} pct" -f [math]::Round($d,0))
  if ($d -gt 80) { W "  [WARN] Disk saturated" }
}

Line "6. STARTUP ITEMS"
Get-CimInstance Win32_StartupCommand | Sort-Object Name | ForEach-Object {
  W ("  {0,-28} {1}" -f $_.Name, $_.Command)
}

Line "7. DISK SPACE"
Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {
  $t = [math]::Round($_.Size/1GB,1)
  $f = [math]::Round($_.FreeSpace/1GB,1)
  $p = 0
  if ($t -gt 0) { $p = [math]::Round(($f/$t)*100,1) }
  W ("{0} total {1} GB, free {2} GB ({3} pct)" -f $_.DeviceID, $t, $f, $p)
  if ($p -lt 10) { W "  [CRIT] Under 10 pct free - SSD slows down" }
  elseif ($p -lt 20) { W "  [WARN] Low free space" }
}

Line "8. PHYSICAL DISKS"
Get-PhysicalDisk | ForEach-Object {
  W ("  {0,-30} {1,-6} {2,7} GB  health={3}" -f $_.FriendlyName, $_.MediaType, [math]::Round($_.Size/1GB,0), $_.HealthStatus)
}

Line "9. POWER PLAN"
powercfg /getactivescheme | ForEach-Object { W $_ }
W "  Note: Power-saver or MSI Center silent mode throttles the CPU."

Line "10. TOP 20 FOLDERS IN USER PROFILE"
W "Scanning, may take 1-2 minutes..."
Get-ChildItem $env:USERPROFILE -Directory -Force | ForEach-Object {
  $sz = (Get-ChildItem $_.FullName -Recurse -Force -File -EA SilentlyContinue | Measure-Object Length -Sum).Sum
  New-Object psobject -Property @{ P = $_.FullName; GB = [math]::Round($sz/1GB,2) }
} | Sort-Object GB -Descending | Select-Object -First 20 | ForEach-Object {
  W ("{0,9} GB  {1}" -f $_.GB, $_.P)
}

Line "11. CACHE SIZES"
$targets = @(
  "$env:TEMP",
  "$env:WINDIR\Temp",
  "$env:LOCALAPPDATA\pip\Cache",
  "$env:USERPROFILE\.cache",
  "$env:USERPROFILE\anaconda3\pkgs",
  "$env:APPDATA\npm-cache",
  "$env:LOCALAPPDATA\npm-cache",
  "$env:LOCALAPPDATA\Microsoft\Windows\INetCache",
  "$env:LOCALAPPDATA\Google\Chrome\User Data\Default\Cache",
  "$env:LOCALAPPDATA\NVIDIA\DXCache",
  "$env:LOCALAPPDATA\D3DSCache",
  "$env:LOCALAPPDATA\CrashDumps",
  "$env:WINDIR\SoftwareDistribution\Download",
  "$env:USERPROFILE\Downloads"
)
foreach ($t in $targets) {
  if (Test-Path $t) {
    $sz = (Get-ChildItem $t -Recurse -Force -File -EA SilentlyContinue | Measure-Object Length -Sum).Sum
    W ("{0,9} MB  {1}" -f [math]::Round($sz/1MB,0), $t)
  }
}

Line "END OF REPORT"
$dest = Join-Path $PSScriptRoot 'perf-report.txt'
$out | Out-File -FilePath $dest -Encoding ASCII
Write-Host ""
Write-Host ("Report saved to: " + $dest) -ForegroundColor Green