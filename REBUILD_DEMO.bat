@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" "src\build_map.py"
set "ocean_result=%ERRORLEVEL%"
if not "%ocean_result%"=="0" echo Build failed. Read the error above; no raw data were changed.
if "%~1"=="--no-pause" exit /b %ocean_result%
pause
exit /b %ocean_result%
