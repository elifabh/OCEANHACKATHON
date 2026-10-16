@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" "src\check_final_delivery.py"
set "ocean_result=%ERRORLEVEL%"
if "%~1"=="--no-pause" exit /b %ocean_result%
pause
exit /b %ocean_result%
