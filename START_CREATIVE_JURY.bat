@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0src\start_creative_jury.ps1"
if errorlevel 1 (
  echo PowerPoint could not start. Open the PPTX in outputs\final_creative_20261015 and press F5.
  pause
)
