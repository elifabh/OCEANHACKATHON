# Actual PowerPoint show; QA sends manual navigation commands at presenter cues.
# It does not save timers into the deck and is not the delivery launcher.
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$out=Join-Path $root 'outputs/final_creative_20261015'
$narration=Get-Content (Join-Path $out 'qa/narration-pacing.json') -Raw|ConvertFrom-Json
$app=New-Object -ComObject PowerPoint.Application;$initial=$app.Presentations.Count;$pres=$null;$show=$null;$rows=@()
try{
 $pres=$app.Presentations.Open((Join-Path $out 'INVISIBLE_SHIELD_CREATIVE_FINAL_v3.pptx'),-1,0,-1)
 foreach($slide in @($pres.Slides)){if($slide.SlideShowTransition.AdvanceOnTime -ne 0){throw 'Automatic advancement found'}}
 $pres.SlideShowSettings.ShowType=2;$pres.SlideShowSettings.AdvanceMode=1
 $show=$pres.SlideShowSettings.Run();$watch=[Diagnostics.Stopwatch]::StartNew()
 foreach($cue in $narration.slides){
  while($watch.Elapsed.TotalSeconds -lt $cue.start){Start-Sleep -Milliseconds 200}
  $show.View.GotoSlide([int]$cue.slide,-1)
  $actualStart=$watch.Elapsed.TotalSeconds
  while($watch.Elapsed.TotalSeconds -lt $cue.end){if($show.View.Slide.SlideIndex -ne $cue.slide){throw 'Uncommanded advancement'};Start-Sleep -Milliseconds 200}
  $rows+=@{slide=$cue.slide;expected_start=$cue.start;actual_start=$actualStart;expected_end=$cue.end;actual_end=$watch.Elapsed.TotalSeconds;manual_hold=$true}
  Write-Output ('Verified slide '+$cue.slide)
 }
 @{status='PASS';elapsed_seconds=$watch.Elapsed.TotalSeconds;application='PowerPoint '+$app.Version;slides=$rows;demo_slot_seconds=75;demo_playback_verified_separately=$true;human_spoken_rehearsal=$false;source='INVISIBLE_SHIELD_CREATIVE_FINAL_v3.pptx'}|ConvertTo-Json -Depth 6|Set-Content (Join-Path $out 'qa/native-10-minute-rehearsal.json') -Encoding UTF8
}finally{if($show){try{$show.View.Exit()}catch{}};if($pres){$pres.Saved=-1;$pres.Close()};if($initial -eq 0 -and $app.Presentations.Count -eq 0){$app.Quit()};[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
