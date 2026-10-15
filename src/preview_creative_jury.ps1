param([int]$Slide=6,[int]$Seconds=65)
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$out=Join-Path $root 'outputs/final_creative_20261015'
$app=New-Object -ComObject PowerPoint.Application;$initial=$app.Presentations.Count;$pres=$null;$show=$null
try{
 $app.Visible=-1
 $pres=$app.Presentations.Open((Join-Path $out 'INVISIBLE_SHIELD_CREATIVE_FINAL_v3.pptx'),-1,0,-1)
 $pres.SlideShowSettings.ShowType=2;$pres.SlideShowSettings.AdvanceMode=1
 $show=$pres.SlideShowSettings.Run();$show.View.GotoSlide($Slide,-1)
 $watch=[Diagnostics.Stopwatch]::StartNew();Write-Output ('Running native slide '+$Slide)
 while($watch.Elapsed.TotalSeconds -lt $Seconds){Start-Sleep -Milliseconds 300}
 if($show.View.Slide.SlideIndex -ne $Slide){throw 'Slide advanced without presenter input'}
 @{status='PASS';slide=$Slide;native_elapsed=$show.View.SlideElapsedTime;manual_hold_verified_seconds=$Seconds;powerpoint_version=$app.Version}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $out ('qa/manual-hold-slide-'+$Slide+'.json')) -Encoding UTF8
}finally{if($show){try{$show.View.Exit()}catch{}};if($pres){$pres.Saved=-1;$pres.Close()};if($initial -eq 0 -and $app.Presentations.Count -eq 0){$app.Quit()};[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
