$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$file=Join-Path $root 'outputs/final_creative_20261015/INVISIBLE_SHIELD_CREATIVE_FINAL_v3.pptx'
if(-not(Test-Path -LiteralPath $file)){throw 'Creative jury deck is missing.'}
$app=New-Object -ComObject PowerPoint.Application
$app.Visible=-1
$pres=$app.Presentations.Open($file,-1,0,-1)
$pres.SlideShowSettings.AdvanceMode=1
$pres.SlideShowSettings.ShowType=1
$pres.SlideShowSettings.LoopUntilStopped=0
$show=$pres.SlideShowSettings.Run()
# Intentionally leave the user's show open. No timer advances the slides.
