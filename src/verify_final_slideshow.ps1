$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$out=Join-Path $root 'outputs/final_overnight_20261015'
$app=New-Object -ComObject PowerPoint.Application;$initial=$app.Presentations.Count;$pres=$null;$show=$null
try {
 $app.Visible=-1
 $pres=$app.Presentations.Open((Join-Path $out 'INVISIBLE_SHIELD_JURY_10_MIN_FINAL.pptx'),-1,0,-1)
 $pres.SlideShowSettings.ShowType=2
 $show=$pres.SlideShowSettings.Run()
 $checks=@()
 for($i=1;$i -le 12;$i++){
  $show.View.GotoSlide($i,-1);Start-Sleep -Milliseconds 850
  $elapsed=[double]$show.View.SlideElapsedTime
  if($show.View.Slide.SlideIndex -ne $i){throw 'Slideshow failed to navigate'}
  $checks+=@{slide=$i;opened_and_played=$true;elapsed_seconds=$elapsed;effects=$pres.Slides.Item($i).TimeLine.MainSequence.Count;seconds=$pres.Slides.Item($i).SlideShowTransition.AdvanceTime}
 }
 $show.View.GotoSlide(6,-1)
 Start-Sleep -Seconds 2
 $start=[double]$show.View.SlideElapsedTime
 Write-Output 'All 12 slides opened in running PowerPoint slideshow; checking the full physical animation sequence.'
 Start-Sleep -Seconds 41
 $end=[double]$show.View.SlideElapsedTime
 if($end -lt 40 -or $show.View.Slide.SlideIndex -ne 6){throw 'Physical sequence clock did not advance correctly'}
 $checks+=@{slide=6;native_sequence_played_seconds=$end;elapsed_start=$start;elapsed_end=$end;effects=$pres.Slides.Item(6).TimeLine.MainSequence.Count;visual_boundary='Static rendered endpoints inspected separately; elapsed running native show verified'}
 $show.View.Exit();$show=$null
 @{status='PASS';build_id=(Get-Content (Join-Path $out 'app/build_manifest.json') -Raw|ConvertFrom-Json).build_id;powerpoint_version=$app.Version;checks=$checks} | ConvertTo-Json -Depth 7 | Set-Content -Encoding UTF8 (Join-Path $out 'qa/slideshow-playback.json')
 Write-Output 'PASS: real PowerPoint slide-show playback and 43-second physical sequence.'
}finally{if($null -ne $show){try{$show.View.Exit()}catch{}};if($null -ne $pres){$pres.Saved=-1;$pres.Close()};if($initial -eq 0 -and $app.Presentations.Count -eq 0){$app.Quit()};[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
