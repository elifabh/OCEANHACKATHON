@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" "src\launch_demo.py" %*
if errorlevel 1 goto failed
exit /b 0
:missing
echo The existing project Python environment is missing. See docs\overnight_20261013\RUNBOOK.md.
:failed
echo Demo could not start. The message above explains the problem.
pause
exit /b 1
