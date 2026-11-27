@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set BASE=C:\Users\plsharevme\tvbox-gateway
set REPO=C:\Users\plsharevme\tvbox-repo
set PS=powershell -NoProfile -ExecutionPolicy Bypass -File "%BASE%\status.ps1"
cd /d "%BASE%"

if /i "%~1"=="menu" goto menu
if /i "%~1"=="stop" goto stoponly
if /i "%~1"=="status" goto statusonly
if /i "%~1"=="ip" goto iponly
goto auto

:auto
cls
echo ==========================================================
echo   TVBox local gateways  :8080 spankbang  :8081 sexkbj  :8082 erome
echo ==========================================================
echo.
%PS% -Ips
echo.
echo [2/3] starting gateways (already-running ones are skipped) ...
wscript "%BASE%\start-all-hidden.vbs"
%PS% -Wait 90
echo.
echo [3/3] syncing configured IP to this machine's current LAN IP ...
if not exist "%REPO%\.git" (
  echo       [!] repo not found: %REPO%  - skipped
  goto done
)
pushd "%REPO%"
node tools\update-gateway-ip.mjs --push > "%BASE%\last-ip-sync.log" 2>&1
set RC=%ERRORLEVEL%
popd
powershell -NoProfile -Command "Get-Content '%BASE%\last-ip-sync.log' -Encoding UTF8 | Select-Object -Last 7 | ForEach-Object { '      ' + $_ }"
if not "%RC%"=="0" (
  echo       [!] sync failed - see last-ip-sync.log
) else (
  echo       [OK] synced - no commit when the IP did not change
)

:done
echo.
%PS% -Status
echo.
echo Gateways keep running in background - you can close this window.
echo For stop / restart / logs: run this icon again and press M within 8s.
echo.
choice /c MQ /t 8 /d Q /n /m "M=menu   Q=close now (auto-close in 8s): " >nul
if errorlevel 2 exit /b 0
goto menu

:menu
cls
echo ==========================================
echo   TVBox local gateways
echo ==========================================
echo.
%PS% -Status
echo.
echo   [1] start all  (background, no window)
echo   [2] stop all
echo   [3] restart all
echo   [4] re-sync local IP and push
echo   [5] status only
echo   [6] open log folder
echo   [0] exit
echo.
set /p CH=select: 
if "%CH%"=="1" goto start
if "%CH%"=="2" goto stop
if "%CH%"=="3" goto restart
if "%CH%"=="4" goto ip
if "%CH%"=="5" goto status
if "%CH%"=="6" goto logs
if "%CH%"=="0" exit /b 0
goto menu

:start
echo starting all gateways in background ...
wscript "%BASE%\start-all-hidden.vbs"
timeout /t 12 >nul
goto status

:restart
%PS% -Stop
wscript "%BASE%\start-all-hidden.vbs"
timeout /t 12 >nul
goto status

:stop
:stoponly
%PS% -Stop
if /i "%~1"=="stop" exit /b 0
goto menu

:statusonly
%PS% -Status
exit /b 0

:status
echo.
%PS% -Status
echo.
pause
goto menu

:ip
:iponly
pushd "%REPO%"
node tools\update-gateway-ip.mjs --push
popd
if /i "%~1"=="ip" exit /b 0
echo.
pause
goto menu

:logs
start "" "%BASE%"
goto menu
