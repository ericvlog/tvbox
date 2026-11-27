param(
  [switch]$Ips,
  [switch]$Status,
  [switch]$Stop,
  [int]$Wait = 0
)

$ErrorActionPreference = 'SilentlyContinue'
$ports = 8080, 8081, 8082

function Show-Ips {
  Write-Host '[1/3] 检查当前本机 IP ...'
  $ips = Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
    $_.IPAddress -notmatch '^(127\.|169\.254\.)'
  } | Sort-Object InterfaceAlias
  if (-not $ips) { Write-Host '      (没有非回环 IPv4)' -ForegroundColor Yellow; return }
  foreach ($a in $ips) { Write-Host ('      {0,-16} {1}' -f $a.IPAddress, $a.InterfaceAlias) }
}

function Test-Port([int]$p) {
  try {
    $r = Invoke-WebRequest ("http://127.0.0.1:{0}/api.php/provide/vod/?ac=list&pg=1" -f $p) -UseBasicParsing -TimeoutSec 45
    $j = $r.Content | ConvertFrom-Json
    return @{ ok = $true; count = $j.list.Count; cls = ($j.class | ForEach-Object { $_.type_name }) -join ',' }
  } catch {
    $null = $?
    try { $r2 = Invoke-WebRequest ("http://127.0.0.1:{0}/" -f $p) -UseBasicParsing -TimeoutSec 10; if ($r2.StatusCode -eq 200) { return @{ ok = $true; count = -1; cls = '' } } } catch { $null = $? }
    return @{ ok = $false; count = 0; cls = '' }
  }
}

function Wait-Ports([int]$secs) {
  $deadline = (Get-Date).AddSeconds($secs)
  do {
    $alive = 0
    foreach ($p in $ports) { if ((Test-Port $p).ok) { $alive++ } }
    if ($alive -eq 3) { return $true }
    Start-Sleep -Seconds 3
  } while ((Get-Date) -lt $deadline)
  return $false
}

function Show-Status {
  Write-Host '---------------- 状态 ----------------'
  foreach ($p in $ports) {
    $r = Test-Port $p
    if ($r.ok) {
      if ($r.count -ge 0) { Write-Host ('   {0}  OK   {1} 条   class={2}' -f $p, $r.count, $r.cls) }
      else { Write-Host ('   {0}  OK   (无列表接口)' -f $p) }
    } else {
      Write-Host ('   {0}  不可用' -f $p) -ForegroundColor Yellow
    }
  }
}

function Stop-All {
  Write-Host '正在停止（连 cmd 外壳一起杀，否则会被 :loop 重生）...'
  Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" | Where-Object {
    $_.CommandLine -match 'start-erome|start-sexkbj|tbox-gateway\\start\.cmd'
  } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
    $_.CommandLine -match '_gateway\.py'
  } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object {
    $_.CommandLine -match 'erome-login-profile|sb-gateway-profile'
  } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  Start-Sleep -Seconds 3
  Show-Status
}

if ($Ips) { Show-Ips; exit 0 }
if ($Stop) { Stop-All; exit 0 }
if ($Wait -gt 0) { if (Wait-Ports $Wait) { Write-Host '      [OK] 三个端口都在应答'; exit 0 } else { Write-Host '      [!] 有端口没应答' -ForegroundColor Yellow; exit 1 } }
Show-Status
