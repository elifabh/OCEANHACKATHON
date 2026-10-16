$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$work=Join-Path $root 'work/final_overnight'
$out=Join-Path $root 'outputs/final_overnight_20261015'
$contract=Get-Content -LiteralPath (Join-Path $work 'deck-contract.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$render=Join-Path $out 'presentation_assets/slides'
New-Item -ItemType Directory -Force -Path $render | Out-Null
$app=New-Object -ComObject PowerPoint.Application
$initialCount=$app.Presentations.Count
$pres=$null
try {
 $pres=$app.Presentations.Open((Join-Path $work 'jury-draft.pptx'),0,0,0)
 if($pres.Slides.Count -ne 12){throw 'Exactly 12 slides required'}
 $rows=@();$sum=0
 for($i=1;$i -le 12;$i++) {
  $sl=$pres.Slides.Item($i)
  $sl.SlideShowTransition.EntryEffect=1793
  $sl.SlideShowTransition.Duration=.5
  $sl.SlideShowTransition.AdvanceOnClick=-1
  $sl.SlideShowTransition.AdvanceOnTime=-1
  $sl.SlideShowTransition.AdvanceTime=[single]$contract.native_slide_seconds[$i-1]
  $sum += $contract.native_slide_seconds[$i-1]
  foreach($note in @($sl.NotesPage.Shapes)){if($note.HasTextFrame -eq -1){$note.TextFrame.TextRange.Text=''}}
  $pictureIndex=0
  foreach($sh in @($sl.Shapes)) {
   if($sh.Type -eq 13){
    if($i -eq 1){$sh.Name=if($pictureIndex -eq 0){'A_1_fade_KELP'}else{'A_22_fade_COAST'}}
    if($i -eq 5){$sh.Name='A_8_zoom_CAPE_MAP'}
    if($i -eq 8){$sh.Name='A_6_fade_ECOLOGY'}
    if($i -eq 10){$sh.Name='A_35_fade_DEMO_POSTER'}
    if($i -eq 12){$sh.Name='A_0_rise_KELP'}
    $pictureIndex++
   }
  }
  $cues=@();$overflow=@()
  foreach($sh in @($sl.Shapes)) {
   if($sh.Name -match '^A_([0-9.]+)_(fade|fly|rise|zoom|wipe)_'){$cues+=@{shape=$sh;at=[double]$Matches[1];kind=$Matches[2]}}
   if($sh.HasChart -eq -1){$cues+=@{shape=$sh;at=22;kind='fade'}}
   if($sh.HasTextFrame -eq -1 -and $sh.TextFrame.HasText -eq -1){
    if($sh.TextFrame2.TextRange.BoundHeight -gt $sh.Height+5){$overflow+=@{name=$sh.Name;text=$sh.TextFrame.TextRange.Text;box_height=$sh.Height;text_height=$sh.TextFrame2.TextRange.BoundHeight}}
   }
  }
  foreach($c in @($cues|Sort-Object {$_.at})) {
   $effectType=switch($c.kind){'fade'{10};'zoom'{23};'wipe'{22};default{2}}
   $effect=$sl.TimeLine.MainSequence.AddEffect($c.shape,$effectType,0,2)
   $effect.Timing.Duration=if($c.kind -eq 'wipe'){4.0}elseif($c.kind -eq 'fade'){.8}else{1.2}
   if($c.kind -eq 'wipe'){$effect.EffectParameters.Direction=2}
   $effect.Timing.TriggerDelayTime=[single]$c.at
  }
  if($i -eq 10){$sl.Shapes.Item('A_35_fade_DEMO_POSTER').Visible=0}
  $sl.Export((Join-Path $render ('slide-'+$i+'.png')),'PNG',1920,1080)
  if($i -eq 10){$sl.Shapes.Item('A_35_fade_DEMO_POSTER').Visible=-1}
  $rows+=@{slide=$i;seconds=$contract.native_slide_seconds[$i-1];effects=$sl.TimeLine.MainSequence.Count;overflow=$overflow;render='PowerPoint 16 native export'}
 }
 if($sum -ne 600){throw 'Timing must total 600 seconds including the 75-second demo'}
 $pres.SlideShowSettings.AdvanceMode=2
 $pres.SaveAs((Join-Path $work 'jury-native.pptx'),24)
 $pres.Slides.Item(10).Shapes.Item('A_35_fade_DEMO_POSTER').Visible=0
 $pres.SaveAs((Join-Path $out 'INVISIBLE_SHIELD_JURY_10_MIN_FINAL.pdf'),32)
 @{status='PASS';build_id=$contract.build_id;slides=12;seconds=$sum;powerpoint_version=$app.Version;rows=$rows;notes='All note text cleared';video_status='Poster reserved on slide 10 at 35 seconds; actual recording and bounded insertion occur last'} | ConvertTo-Json -Depth 7 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $out 'qa/powerpoint-render.json')
 Write-Output ('Rendered 12 slides; '+$sum+' seconds; source build '+$contract.build_id)
}finally{if($null -ne $pres){$pres.Close()};if($initialCount -eq 0 -and $app.Presentations.Count -eq 0){$app.Quit()};[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
