@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "C:\Users\plsharevme\tvbox-gateway"
set BASE=C:\Users\plsharevme\tvbox-gateway

:menu
cls
echo ==========================================
echo   TVBox 本机网关 (8080 spankbang / 8081 sexkbj / 8082 erome)
echo ==========================================
echo.
for %%p in (8080 8081 8082) do (
  powershell -NoProfile -Command "if((Get-NetTCPConnection -LocalPort %%p -State Listen -EA 0)){'  %%p  : 运行中'}else{'  %%p  : 未启动'}"
)
echo.
echo   [1] 启动全部（后台无窗口）
echo   [2] 停止全部
echo   [3] 重启全部
echo   [4] 更新配置里的本机 IP 并 push
echo   [5] 只看状态（跑一次检测）
echo   [6] 打开日志目录
echo   [0] 退出
echo.
set /p CH=选择: 
if "%CH%"=="1" goto start
if "%CH%"=="2" goto stop
if "%CH%"=="3" goto restart
if "%CH%"=="4" goto ip
if "%CH%"=="5" goto status
if "%CH%"=="6" goto logs
if "%CH%"=="0" exit /b 0
goto menu

:start
echo 正在后台启动三个网关...
wscript "%BASE%\start-all-hidden.vbs"
timeout /t 12 >nul
goto status

:stop
echo 正在停止...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | ?{$_.CommandLine -match 'start-erome|start-sexkbj|tbox-gateway\\start.cmd'} | %%{Stop-Process -Id $_.ProcessId -Force -EA 0}"
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ?{$_.CommandLine -match '_gateway.py'} | %%{Stop-Process -Id $_.ProcessId -Force -EA 0}"
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | ?{$_.CommandLine -match 'erome-login-profile|sb-gateway-profile'} | %%{Stop-Process -Id $_.ProcessId -Force -EA 0}"
timeout /t 3 >nul
goto status

:restart
call :dostop
wscript "%BASE%\start-all-hidden.vbs"
timeout /t 12 >nul
goto status

:dostop
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | ?{$_.CommandLine -match 'start-erome|start-sexkbj|tbox-gateway\\start.cmd'} | %%{Stop-Process -Id $_.ProcessId -Force -EA 0}"
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | ?{$_.CommandLine -match '_gateway.py'} | %%{Stop-Process -Id $_.ProcessId -Force -EA 0}"
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | ?{$_.CommandLine -match 'erome-login-profile|sb-gateway-profile'} | %%{Stop-Process -Id $_.ProcessId -Force -EA 0}"
timeout /t 3 >nul
exit /b 0

:status
echo.
echo --- 端口与接口 ---
powershell -NoProfile -Command "foreach($p in 8080,8081,8082){ try{ $r=Invoke-WebRequest \"http://127.0.0.1:$p/api.php/provide/vod/?ac=list&pg=1\" -UseBasicParsing -TimeoutSec 60; $j=$r.Content|ConvertFrom-Json; '{0}  OK  {1} 条' -f $p,$j.list.Count }catch{ '{0}  不可用' -f $p } }"
echo.
pause
goto menu

:ip
cd /d "C:\Users\plsharevme\tvbox-repo"
node tools\update-gateway-ip.mjs --push
echo.
pause
goto menu

:logs
start "" "C:\Users\plsharevme\tvbox-gateway"
goto menu
