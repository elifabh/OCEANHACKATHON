$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pitchOut=Join-Path $projectRoot 'outputs/presentations_final_20261014'
$qa=Join-Path $projectRoot 'outputs/final_20261014/qa/powerpoint'
if(-not(Test-Path -LiteralPath $qa)){New-Item -ItemType Directory -Path $qa | Out-Null}
$app=New-Object -ComObject PowerPoint.Application
$initialCount=$app.Presentations.Count
$app.Visible=-1
$report=@()
try {
 foreach($name in @('SUNDAY_3_MINUTES_FINAL','SUNDAY_5_MINUTES_FINAL','FRIDAY_INVITATION')) {
  $pres=$null;$show=$null
  try {
   $pres=$app.Presentations.Open((Join-Path $pitchOut ($name+'.pptx')),-1,0,0)
   $expected=if($name -eq 'FRIDAY_INVITATION'){1}else{6}
   if($pres.Slides.Count -ne $expected){throw 'Wrong slide count'}
   $folder=Join-Path $qa $name
   if(-not(Test-Path -LiteralPath $folder)){New-Item -ItemType Directory -Path $folder | Out-Null}
   $notes=0;$effects=0
   for($i=1;$i -le $pres.Slides.Count;$i++) {
    $sl=$pres.Slides.Item($i)
    $sl.Export((Join-Path $folder ('slide-'+$i+'.png')),'PNG',1600,900)
    $effects+=$sl.TimeLine.MainSequence.Count
    foreach($sh in @($sl.NotesPage.Shapes)){if($sh.HasTextFrame -eq -1 -and $sh.TextFrame.HasText -eq -1 -and $sh.TextFrame.TextRange.Text -match 'SOURCES AND LIMITS'){$notes++}}
   }
   if($notes -ne $expected){throw 'Missing speaker notes'}
   $playback=$null;$fallback=$null
   if($expected -eq 6){
    $clip=$pres.Slides.Item(5).Shapes.Item('real-app-demo')
    $frames=@($pres.Slides.Item(5).Shapes | Where-Object {$_.Name -like 'verified-frame-*'}).Count
    $expectedFrames=if($name -match '3_MINUTES'){8}else{9}
    if($frames -ne $expectedFrames){throw 'Native fallback frames are incomplete'}
    if($pres.Slides.Item(5).TimeLine.MainSequence.Count -lt ($expectedFrames-1)){throw 'Native fallback timing is incomplete'}
    $playback=@{status='FAIL_ON_THIS_INSTALLATION';reason='Previous real slideshow tests: H.264, H.264/AAC and WMV player stayed at 0 ms; manual Play also failed. Default playback now deliberately uses native frames.';length_ms=$clip.MediaFormat.Length}
    $fallback=@{status='PASS';real_recording_frames=$frames;timed_native_effects=$pres.Slides.Item(5).TimeLine.MainSequence.Count;animation_rehearsal='PowerPoint CreateVideo, work/story_20261014/native-animation-rehearsal.mp4; visually inspected changing frames'}
   }
   $report+=@{file=$name+'.pptx';status='PASS_WITH_DECLARED_MEDIA_FALLBACK';slides=$pres.Slides.Count;notes=$notes;animation_effects=$effects;native_render='PASS';embedded_video_playback=$playback;native_frame_fallback=$fallback;powerpoint_version=$app.Version}
  } catch {Write-Output ($_ | Out-String);throw} finally {if($null -ne $show){try{$show.View.Exit()}catch{}};if($null -ne $pres){try{$pres.Saved=-1;$pres.Close()}catch{};[void][Runtime.InteropServices.Marshal]::ReleaseComObject($pres)}}
 }
 $report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $qa 'powerpoint_rehearsal.json') -Encoding UTF8
 $report | ConvertTo-Json -Depth 6
} finally {try{if($initialCount -eq 0 -and $app.Presentations.Count -eq 0){$app.Quit()}}catch{};[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
