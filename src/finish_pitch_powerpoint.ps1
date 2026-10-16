param([switch]$RenderOnly)
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pitchWork=Join-Path $projectRoot 'work/story_20261014'
$pitchOut=Join-Path $projectRoot 'outputs/presentations_final_20261014'
$timing=Get-Content -LiteralPath (Join-Path $pitchWork 'timing.json') -Raw | ConvertFrom-Json
$app=New-Object -ComObject PowerPoint.Application
$initialCount=$app.Presentations.Count
$checks=@()
try {
 foreach($variant in @('compact','extended','friday')) {
  $pres=$null
  try {
   $source=Join-Path $pitchWork ($variant+'-draft.pptx')
   $pres=$app.Presentations.Open($source,0,0,0)
   $slideCount=$pres.Slides.Count
   $duration=0
   for($i=1;$i -le $slideCount;$i++) {
    $sl=$pres.Slides.Item($i)
    $sl.SlideShowTransition.EntryEffect=1793
    $sl.SlideShowTransition.Duration=0.35
    $sl.SlideShowTransition.AdvanceOnClick=-1
    if($variant -ne 'friday') {
     $seconds=$timing.$variant[$i-1]
     $sl.SlideShowTransition.AdvanceOnTime=-1
     $sl.SlideShowTransition.AdvanceTime=$seconds
     $duration+=$seconds
    }
    $delay=0.6
    foreach($sh in @($sl.Shapes)) {
     if($sh.Name -like 'reveal-*') {
      $effect=$sl.TimeLine.MainSequence.AddEffect($sh,10,0,2)
      $effect.Timing.TriggerDelayTime=$delay
      $effect.Timing.Duration=0.55
      $delay+=1.3
     }
    }
    if($i -eq 2 -and $variant -ne 'friday') {
     $zoom=$sl.Shapes.AddPicture((Join-Path $pitchWork 'cork-zoom-panel.png'),0,-1,48.75,112.5,345,355.5)
     $zoom.Name='cork-zoom'
     $fade=$sl.TimeLine.MainSequence.AddEffect($zoom,10,0,2)
     $fade.Timing.TriggerDelayTime=9
     $fade.Timing.Duration=1.0
     $effect=$sl.TimeLine.MainSequence.AddEffect($zoom,59,0,2)
     $effect.Timing.TriggerDelayTime=9
     $effect.Timing.Duration=1.6
     $effect.EffectParameters.Size=100
    }
    if($i -eq 3 -and $variant -ne 'friday') {
     $layerDelay=0.0
     foreach($layer in @('satellite','model','historical')) {
      $layerPicture=$sl.Shapes.AddPicture((Join-Path $projectRoot ('outputs/final_20261014/qa/pitch_'+$layer+'.png')),0,-1,48,116.25,525,270)
      $layerPicture.Name='map-layer-'+$layer
      $layerEffect=$sl.TimeLine.MainSequence.AddEffect($layerPicture,10,0,2)
      $layerEffect.Timing.TriggerDelayTime=$layerDelay
      $layerEffect.Timing.Duration=0.6
      $layerDelay+=2.5
     }
    }
    if($i -eq 4 -and $variant -ne 'friday') {
     $without=$sl.Shapes.AddPicture((Join-Path $projectRoot 'outputs/final_20261014/qa/wave_without.png'),0,-1,48,142.5,556.5,209.25)
     $without.Name='without-kelp'
     $with=$sl.Shapes.AddPicture((Join-Path $projectRoot 'outputs/final_20261014/qa/wave_concept.png'),0,-1,48,142.5,556.5,209.25)
     $with.Name='with-kelp'
     $waveEffect=$sl.TimeLine.MainSequence.AddEffect($with,10,0,2)
     $waveEffect.Timing.TriggerDelayTime=3
     $waveEffect.Timing.Duration=0.7
     foreach($shape in @($sl.Shapes)) {if($shape.HasChart -eq -1){$shape.Chart.Axes(2).MaximumScale=115}}
    }
   }
   $mediaInfo=$null
   if($variant -ne 'friday') {
    $s5=$pres.Slides.Item(5)
    for($j=$s5.Shapes.Count;$j -ge 1;$j--) {if($s5.Shapes.Item($j).Type -eq 13){$s5.Shapes.Item($j).Delete()}}
    if($variant -eq 'compact') {$movie='DEMO_30_SECONDS.mp4';$poster='demo_short_poster.png'} else {$movie='DEMO_55_SECONDS.mp4';$poster='demo_full_poster.png'}
    $clip=$s5.Shapes.AddMediaObject2((Join-Path $pitchOut $movie),0,-1,24,27,912,513)
    $clip.Name='real-app-demo'
    $clip.MediaFormat.SetDisplayPictureFromFile((Join-Path $pitchOut $poster))
    $clip.AnimationSettings.PlaySettings.PlayOnEntry=-1
    $clip.AnimationSettings.PlaySettings.HideWhileNotPlaying=0
    $clip.AnimationSettings.PlaySettings.RewindMovie=-1
    $clip.AnimationSettings.AdvanceMode=2
    $clip.AnimationSettings.AdvanceTime=0
    foreach($mediaEffect in @($s5.TimeLine.MainSequence)) {
     $mediaEffect.Timing.TriggerType=2
     $mediaEffect.Timing.TriggerDelayTime=0
    }
    $pres.SlideShowSettings.AdvanceMode=2
    # Native MP4/WMV playback failed on this installed PowerPoint. Preserve the
    # embedded recording but use genuine, timed recording frames as the default.
    $clip.AnimationSettings.PlaySettings.PlayOnEntry=0
    for($ei=$s5.TimeLine.MainSequence.Count;$ei -ge 1;$ei--) {
     if($s5.TimeLine.MainSequence.Item($ei).Shape.Id -eq $clip.Id){$s5.TimeLine.MainSequence.Item($ei).Delete()}
    }
    $clip.ZOrder(1)
    $frameSeconds=if($variant -eq 'compact'){@(0,3,7,11,16,20,23,27)}else{@(0,5,12,20,27,34,40,46,51)}
    $durationTag=if($variant -eq 'compact'){'30'}else{'55'}
    for($fi=0;$fi -lt $frameSeconds.Count;$fi++) {
     $frameFile=Join-Path $pitchOut ('fallback_stills/'+$durationTag+'_'+($fi+1).ToString('00')+'.png')
     $frame=$s5.Shapes.AddPicture($frameFile,0,-1,24,27,912,513)
     $frame.Name='verified-frame-'+($fi+1)
     if($fi -gt 0){$frameEffect=$s5.TimeLine.MainSequence.AddEffect($frame,10,0,2);$frameEffect.Timing.TriggerDelayTime=[double]$frameSeconds[$fi];$frameEffect.Timing.Duration=0.2}
    }
    foreach($shape in @($s5.Shapes)) {
     if($shape.HasTextFrame -eq -1 -and $shape.TextFrame.HasText -eq -1){
      if($shape.TextFrame.TextRange.Text -match '^REAL APPLICATION'){$shape.TextFrame.TextRange.Text='REAL APP / TIMED RECORDING FRAMES / CONTINUOUS MP4: OPEN OFFLINE_DEMO.html';$shape.ActionSettings(1).Hyperlink.Address='OFFLINE_DEMO.html'}
     }
    }
    foreach($shape in @($s5.NotesPage.Shapes)) {
     if($shape.HasTextFrame -eq -1 -and $shape.TextFrame.HasText -eq -1 -and $shape.TextFrame.TextRange.Text -match 'SOURCES AND LIMITS'){
      $shape.TextFrame.TextRange.Text='DELIVERY NOTE: This Windows PowerPoint could not play embedded H.264 or WMV. The default scene uses a timed sequence of genuine recording frames. The real continuous MP4 is embedded behind those frames and also plays offline in OFFLINE_DEMO.html. Choose the external film for continuous motion, or let this native fallback run for the same duration. Do not describe the frame sequence as continuous video.'+[Environment]::NewLine+[Environment]::NewLine+$shape.TextFrame.TextRange.Text
     }
    }
    $mediaInfo=@{name=$movie;embedded=$true;length_ms=$clip.MediaFormat.Length;width=$clip.Width;height=$clip.Height;effects=$s5.TimeLine.MainSequence.Count}
   }
   $candidate=Join-Path $pitchWork ($variant+'-native.pptx')
   $pres.SaveAs($candidate,24)
   $renderPath=Join-Path $pitchWork ('render-'+$variant)
   if(-not(Test-Path -LiteralPath $renderPath)){New-Item -ItemType Directory -Path $renderPath | Out-Null}
   for($i=1;$i -le $slideCount;$i++) {$pres.Slides.Item($i).Export((Join-Path $renderPath ('slide-'+$i+'.png')),'PNG',1600,900)}
   $checks+=@{variant=$variant;slides=$slideCount;seconds=$duration;powerpoint_version=$app.Version;native_render='PASS';media=$mediaInfo;path=$candidate}
  } finally {if($null -ne $pres){$pres.Close();[void][Runtime.InteropServices.Marshal]::ReleaseComObject($pres)}}
 }
 $checks | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $pitchWork 'powerpoint-native-checks.json') -Encoding UTF8
 $checks | ConvertTo-Json -Depth 5
} finally {if($initialCount -eq 0 -and $app.Presentations.Count -eq 0){$app.Quit()};[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
