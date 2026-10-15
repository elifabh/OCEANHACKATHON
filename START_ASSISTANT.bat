@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" goto fallback
start "" ".venv\Scripts\pythonw.exe" "src\assistant_server.py"
exit /b 0
:fallback
call START_DEMO.bat
