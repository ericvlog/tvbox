@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
:loop
python erome_gateway.py --port 8082 --log "%~dp0erome-gateway.log"
if errorlevel 100 exit /b 0
timeout /t 5 >nul
goto loop
