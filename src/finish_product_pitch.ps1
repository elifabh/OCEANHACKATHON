$ErrorActionPreference='Stop'
$productRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pitchWork=Join-Path $productRoot 'work/product_pitch'
$pitchOut=Join-Path $productRoot 'outputs/final_delivery_20261014'
$timing=Get-Content -LiteralPath (Join-Path $pitchWork 'timing.json') -Raw | ConvertFrom-Json
$app=New-Object -ComObject PowerPoint.Application
$initialCount=$app.Presentations.Count
$checks=@()
try {
 foreach($variant in @('main','compact','friday')) {
  $pres=$null
  try {
   $pres=$app.Presentations.Open((Join-Path $pitchWork ($variant+'-draft.pptx')),0,0,0)
   $render=Join-Path $pitchOut ('presentation_assets/'+$variant)
   if(-not(Test-Path -LiteralPath $render)){New-Item -ItemType Directory -Path $render | Out-Null}
   $duration=0;$notesCount=0;$effects=0
   for($i=1;$i -le $pres.Slides.Count;$i++) {
    $sl=$pres.Slides.Item($i)
    $sl.SlideShowTransition.EntryEffect=1793;$sl.SlideShowTransition.Duration=.4;$sl.SlideShowTransition.AdvanceOnClick=-1
    if($variant -ne 'friday'){$seconds=$timing.$variant[$i-1];$sl.SlideShowTransition.AdvanceOnTime=-1;$sl.SlideShowTransition.AdvanceTime=$seconds;$duration+=$seconds}else{$sl.SlideShowTransition.AdvanceOnTime=0}
    foreach($sh in @($sl.NotesPage.Shapes)){if($sh.HasTextFrame -eq -1 -and $sh.TextFrame.HasText -eq -1 -and $sh.TextFrame.TextRange.Text -match 'SOURCES AND LIMITS'){$notesCount++}}
    $cues=@()
    foreach($sh in @($sl.Shapes)){
     if($sh.Name -like 'reveal-*'){$at=if($i -eq 6){3.0}elseif($i -eq 10){[double]($sh.Name.Split('-')[-1])*3}else{1.0};$cues+=@{shape=$sh;at=$at;duration=.7}}
     if($sh.HasChart -eq -1){if($i -eq 5){$sh.Chart.Axes(2).MinimumScale=0;$sh.Chart.Axes(2).MaximumScale=1.6};if($i -eq 6){$sh.Chart.Axes(2).MinimumScale=0;$sh.Chart.Axes(2).MaximumScale=120};if($i -eq 7){$sh.Chart.Axes(2).MinimumScale=0;$sh.Chart.Axes(2).MaximumScale=4}}
    }
    if($i -eq 3 -and $variant -ne 'friday'){
     $sl.Export((Join-Path $render 'slide-3-initial.png'),'PNG',1920,1080)
     $zoom=$sl.Shapes.AddPicture((Join-Path $pitchOut 'presentation_assets/map-all.png'),0,-1,42,108.75,397.5,375)
     $zoom.Name='cork-map-reveal';$cues+=@{shape=$zoom;at=8.0;duration=1.2}
    }
    if($i -eq 6 -and $variant -ne 'friday'){
     $hidden=@($sl.Shapes | Where-Object {$_.Name -like 'reveal-*'})
     foreach($sh in $hidden){$sh.Visible=0};$sl.Export((Join-Path $render 'slide-6-initial.png'),'PNG',1920,1080);foreach($sh in $hidden){$sh.Visible=-1}
    }
    if($i -eq 8 -and $variant -ne 'friday'){
     $frames=@('selection','habitat','protection','economics','biodiversity','report-preview')
     $at=if($variant -eq 'main'){@(0,12,25,38,53,65)}else{@(0,5,10,15,21,26)}
     for($j=0;$j -lt $frames.Count;$j++){
      $frame=$sl.Shapes.AddPicture((Join-Path $pitchOut ('presentation_assets/'+$frames[$j]+'.png')),0,-1,42,99,876,391.5)
      $frame.Name='app-still-'+($j+1)
      if($j -gt 0){$cues+=@{shape=$frame;at=[double]$at[$j];duration=.3}}
     }
     $link=$sl.Shapes.AddTextbox(1,680,493,240,18);$link.TextFrame.TextRange.Text='OPEN CONTINUOUS OFFLINE FILM';$link.TextFrame.TextRange.Font.Name='Segoe UI';$link.TextFrame.TextRange.Font.Size=10;$link.ActionSettings(1).Hyperlink.Address='OFFLINE_PRESENTATION.html'
    }
    foreach($cue in @($cues | Sort-Object {$_.at})){$effect=$sl.TimeLine.MainSequence.AddEffect($cue.shape,10,0,2);$effect.Timing.Duration=[single]$cue.duration;$effect.Timing.TriggerDelayTime=[single]$cue.at}
    $effects+=$sl.TimeLine.MainSequence.Count
    $sl.Export((Join-Path $render ('slide-'+$i+'.png')),'PNG',1920,1080)
   }
   $pres.SlideShowSettings.AdvanceMode=2
   $pres.SaveAs((Join-Path $pitchWork ($variant+'-native.pptx')),24)
   if($notesCount -ne $pres.Slides.Count){throw 'Speaker notes incomplete'}
   $checks+=@{variant=$variant;slides=$pres.Slides.Count;notes=$notesCount;seconds=$duration;effects=$effects;native_render='PASS';powerpoint_version=$app.Version;embedded_movie=$false;fallback='Timed real application stills captured before video';primary='Offline HTML continuous movie, to be recorded after slide freeze'}
  }finally{if($null -ne $pres){$pres.Close()}}
 }
 $checks | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $pitchWork 'native-checks.json') -Encoding UTF8
 $checks | ConvertTo-Json -Depth 6
}finally{try{if($initialCount -eq 0 -and $app.Presentations.Count -eq 0){$app.Quit()}}catch{};[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
