@echo off
setlocal
cd /d "%~dp0"
rem Default opens the self-contained app directly. No server or terminal must stay open.
if not exist ".venv\Scripts\python.exe" goto offline
".venv\Scripts\python.exe" "src\launch_demo.py" %*
if errorlevel 1 goto failed
exit /b 0
:offline
if not exist "outputs\final_overnight_20261015\app\index.html" goto missing
start "" "%~dp0outputs\final_overnight_20261015\app\index.html"
exit /b 0
:missing
echo Built application is missing. Run REBUILD_DEMO.bat with the project Python environment.
:failed
echo Demo could not start. The message above explains the problem.
pause
exit /b 1
