param([switch]$SkipMovieProbe)
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pitchWork=Join-Path $projectRoot 'work/jury_release_20261014'
$pitchOut=Join-Path $projectRoot 'outputs/jury_release_20261014'
$timing=Get-Content -LiteralPath (Join-Path $pitchWork 'timing.json') -Raw | ConvertFrom-Json
$app=New-Object -ComObject PowerPoint.Application
$initialCount=$app.Presentations.Count
$checks=@()
try {
 if(-not $SkipMovieProbe) {
  $pres=$null;$show=$null
  try {
   $pres=$app.Presentations.Add(0);$pres.PageSetup.SlideWidth=960;$pres.PageSetup.SlideHeight=540
   $sl=$pres.Slides.Add(1,12)
   $movie=Join-Path $pitchOut 'DEMO_55_SECONDS.mp4'
   $clip=$sl.Shapes.AddMediaObject2($movie,0,-1,0,0,960,540)
   $clip.Name='clean-native-movie-probe';$clip.AnimationSettings.PlaySettings.PlayOnEntry=-1
   $clip.AnimationSettings.PlaySettings.HideWhileNotPlaying=0
   $probe=Join-Path $pitchWork 'movie-packaging-probe.pptx';$pres.SaveAs($probe,24);$pres.Close();$pres=$null
   # Reopen a saved package in a visible PowerPoint window, not just a hidden COM object.
   $app.Visible=-1;$pres=$app.Presentations.Open($probe,0,0,-1)
   $clip=$pres.Slides.Item(1).Shapes.Item('clean-native-movie-probe')
   $pres.SlideShowSettings.ShowType=2;$pres.SlideShowSettings.AdvanceMode=1
   $show=$pres.SlideShowSettings.Run();Start-Sleep -Milliseconds 700
   $player=$show.View.Player($clip.Id);$player.Play();$samples=@()
   for($k=0;$k -lt 5;$k++){Start-Sleep -Milliseconds 1000;$samples+=@{second=$k+1;position_ms=$player.CurrentPosition;state=$player.State}}
   $maxPosition=($samples | ForEach-Object { $_.position_ms } | Measure-Object -Maximum).Maximum
   $probeResult=@{powerpoint_version=$app.Version;status=if($maxPosition -gt 1500){'PASS'}else{'FAIL_PLAYER_DID_NOT_ADVANCE'};saved_and_reopened=$true;visible_window=$true;play_invoked=$true;length_ms=$clip.MediaFormat.Length;samples=$samples;source_file=$movie;package=$probe;action='No codec installation or registry changes. Final PPTX uses a labelled native frame sequence; primary offline HTML uses the actual continuous movie.'}
   $probeResult | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $pitchWork 'movie-probe.json') -Encoding UTF8
  } finally {if($null -ne $show){try{$show.View.Exit()}catch{}};if($null -ne $pres){try{$pres.Saved=-1;$pres.Close()}catch{}}}
 }
 foreach($variant in @('compact','extended','friday')) {
  $pres=$null
  try {
   $pres=$app.Presentations.Open((Join-Path $pitchWork ($variant+'-draft-clean.pptx')),0,0,0)
   $render=Join-Path $pitchWork ('render-'+$variant)
   if(-not(Test-Path -LiteralPath $render)){New-Item -ItemType Directory -Path $render | Out-Null}
   $duration=0;$notesCount=0;$effects=0
   for($i=1;$i -le $pres.Slides.Count;$i++) {
    $sl=$pres.Slides.Item($i)
    $sl.SlideShowTransition.EntryEffect=1793;$sl.SlideShowTransition.Duration=.4;$sl.SlideShowTransition.AdvanceOnClick=-1
    if($variant -ne 'friday'){$seconds=$timing.$variant[$i-1];$sl.SlideShowTransition.AdvanceOnTime=-1;$sl.SlideShowTransition.AdvanceTime=$seconds;$duration+=$seconds}
    else{$sl.SlideShowTransition.AdvanceOnTime=0}
    foreach($sh in @($sl.NotesPage.Shapes)){if($sh.HasTextFrame -eq -1 -and $sh.TextFrame.HasText -eq -1 -and $sh.TextFrame.TextRange.Text -match 'SOURCES AND LIMITS'){$notesCount++}}
    foreach($sh in @($sl.Shapes)){
     if($sh.Name -like 'reveal-*'){
      $effect=$sl.TimeLine.MainSequence.AddEffect($sh,10,0,2);$effect.Timing.Duration=.7
      $effect.Timing.TriggerDelayTime=if($i -eq 4){3}elseif($sh.Name -match 'clare|Kilkee'){5}elseif($sh.Name -match 'galway|Kilkieran'){3}else{1}
     }
     if($sh.HasChart -eq -1){$sh.Chart.Axes(2).MaximumScale=120}
    }
    if($i -eq 4 -and $variant -ne 'friday'){
     $hidden=@($sl.Shapes | Where-Object {$_.Name -like 'reveal-*'})
     foreach($sh in $hidden){$sh.Visible=0}
     $sl.Export((Join-Path $render 'slide-4-without.png'),'PNG',1920,1080)
     foreach($sh in $hidden){$sh.Visible=-1}
    }
    # Preserve the initial geographic locator as well as its timed Cork reveal.
    if($i -eq 2 -and $variant -ne 'friday'){
     $sl.Export((Join-Path $render 'slide-2-initial.png'),'PNG',1920,1080)
     $zoom=$sl.Shapes.AddPicture((Join-Path $pitchWork 'cork-reveal-crop.png'),0,-1,42,108.75,397.5,375)
     $zoom.Name='cork-map-reveal';$fade=$sl.TimeLine.MainSequence.AddEffect($zoom,10,0,2);$fade.Timing.TriggerDelayTime=12;$fade.Timing.Duration=1
    }
    if($i -eq 5 -and $variant -ne 'friday'){
     $tag=if($variant -eq 'compact'){'30'}else{'55'}
     $frameTimes=Get-Content -LiteralPath (Join-Path $pitchWork ('frames-'+$tag+'.json')) -Raw | ConvertFrom-Json
     for($j=0;$j -lt $frameTimes.Count;$j++){
      $frame=$sl.Shapes.AddPicture((Join-Path $pitchOut ('fallback_stills/'+$tag+'_'+($j+1).ToString('00')+'.png')),0,-1,0,0,960,540)
      $frame.Name='recording-frame-'+($j+1)
      if($j -gt 0){$fade=$sl.TimeLine.MainSequence.AddEffect($frame,10,0,2);$fade.Timing.TriggerDelayTime=[double]$frameTimes[$j];$fade.Timing.Duration=.15}
     }
     $label=$sl.Shapes.AddTextbox(1,495,0,465,16)
     $label.Name='frame-fallback-disclosure';$label.Fill.Visible=-1;$label.Fill.ForeColor.RGB=3814674;$label.Line.Visible=0
     $label.TextFrame.TextRange.Text='TIMED REAL-RECORDING FRAMES / CONTINUOUS FILM IN OFFLINE_PRESENTATION.html'
     $label.TextFrame.TextRange.Font.Name='Segoe UI';$label.TextFrame.TextRange.Font.Size=8;$label.TextFrame.TextRange.Font.Color.RGB=16777215
     $label.TextFrame.MarginTop=1;$label.TextFrame.MarginBottom=1;$label.TextFrame.MarginLeft=3
     $label.ActionSettings(1).Hyperlink.Address='OFFLINE_PRESENTATION.html'
     foreach($sh in @($sl.NotesPage.Shapes)){if($sh.HasTextFrame -eq -1 -and $sh.TextFrame.HasText -eq -1 -and $sh.TextFrame.TextRange.Text -match 'SOURCES AND LIMITS'){$sh.TextFrame.TextRange.Text='POWERPOINT PATH: This scene uses timed still frames from the real recording, not an embedded playing movie. The primary offline HTML presentation plays the actual film continuously in the same page. '+[Environment]::NewLine+$sh.TextFrame.TextRange.Text}}
    }
    # These WithPrevious effects share one parallel timing group in saved OOXML.
    # Use absolute offsets from that group's start; confirmed by native video render.
    for($z=$sl.TimeLine.MainSequence.Count;$z -ge 1;$z--){$sl.TimeLine.MainSequence.Item($z).Delete()}
    $cues=@()
    foreach($sh in @($sl.Shapes)){
     if($sh.Name -like 'reveal-*'){
      $at=if($i -eq 4){3}elseif($sh.Name -match 'clare|Kilkee'){5}elseif($sh.Name -match 'galway|Kilkieran'){3}else{1}
      $cues+=@{shape=$sh;at=[double]$at;duration=.7}
     }
     if($sh.Name -eq 'cork-map-reveal'){$cues+=@{shape=$sh;at=12.0;duration=1.0}}
     if($sh.Name -match '^recording-frame-(\d+)$'){
      $frameIndex=[int]$Matches[1]-1
      if($frameIndex -gt 0){$cues+=@{shape=$sh;at=[double]$frameTimes[$frameIndex];duration=.15}}
     }
    }
    foreach($cue in @($cues | Sort-Object {$_.at})){
     $effect=$sl.TimeLine.MainSequence.AddEffect($cue.shape,10,0,2)
     $effect.Timing.Duration=[single]$cue.duration;$effect.Timing.TriggerDelayTime=[single]$cue.at
    }
    $effects+=$sl.TimeLine.MainSequence.Count
    $sl.Export((Join-Path $render ('slide-'+$i+'.png')),'PNG',1920,1080)
   }
   $pres.SlideShowSettings.AdvanceMode=2
   $pres.SaveAs((Join-Path $pitchWork ($variant+'-native.pptx')),24)
   if($notesCount -ne $pres.Slides.Count){throw 'Speaker notes incomplete'}
   $checks+=@{variant=$variant;slides=$pres.Slides.Count;notes=$notesCount;seconds=$duration;effects=$effects;native_render='PASS';powerpoint_version=$app.Version;movie_in_final=$false;fallback='Timed native recording frames';primary='Offline HTML with continuous real movie'}
  } finally {if($null -ne $pres){try{$pres.Close()}catch{}}}
 }
 $checks | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $pitchWork 'native-checks.json') -Encoding UTF8
 $checks | ConvertTo-Json -Depth 6
} finally {try{if($initialCount -eq 0 -and $app.Presentations.Count -eq 0){$app.Quit()}}catch{};[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
