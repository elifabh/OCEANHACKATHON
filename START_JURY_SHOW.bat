@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0src\run_final_jury_show.ps1"
if errorlevel 1 (
 echo Automatic show could not complete. Open the final PPTX and follow MANUAL_VIDEO_INSERTION.md.
 pause
)
