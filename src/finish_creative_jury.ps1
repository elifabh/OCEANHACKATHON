param([string]$Revision='r1')
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$out=Join-Path $root 'outputs/final_creative_20261015'
$work=Join-Path $root 'work/creative_20261015'
$contract=Get-Content -LiteralPath (Join-Path $out 'presentation_contract.json') -Raw -Encoding UTF8|ConvertFrom-Json
$app=New-Object -ComObject PowerPoint.Application
$initial=$app.Presentations.Count;$pres=$null;$scale=.75
try {
 $pres=$app.Presentations.Open((Join-Path $work 'creative-draft.pptx'),0,0,0)
 if($pres.Slides.Count -ne 12){throw 'Exactly twelve approved slides required'}
 # Restore authored image identifiers; the exporter may renumber image names.
 foreach($slide in @($pres.Slides)){
  $pictures=@($contract.imageNames|Where-Object {$_.slide -eq $slide.SlideIndex});$pictureIndex=0
  foreach($shape in @($slide.Shapes)){
   if($shape.Type -eq 13){$shape.Name=$pictures[$pictureIndex].name;$shape.AlternativeText=$pictures[$pictureIndex].alt;$pictureIndex++}
  }
 }
 # Office may disallow grouping imported custom geometry. Move each member with
 # the identical native path so the record fragment stays intact and editable.
 $expanded=@()
 foreach($cue in $contract.animations){$group=@($contract.groups|Where-Object {$_.name -eq $cue.name -and $_.slide -eq $cue.slide});if($group.Count -gt 0){if($cue.kind -eq 'shrink'){continue};foreach($member in $group[0].members){$copy=$cue|ConvertTo-Json|ConvertFrom-Json;$copy.name=$member;$expanded+=$copy}}else{$expanded+=$cue}}
 foreach($sc in $contract.scrims){$pres.Slides.Item($sc.slide).Shapes.Item($sc.name).Fill.Transparency=[single](1-$sc.opacity)}
 # Animated GIF assets are embedded as pictures, with no MP4 embedding dependency.
 foreach($gif in $contract.gifs){$slide=$pres.Slides.Item($gif.slide);$old=$slide.Shapes.Item($gif.name);$z=$old.ZOrderPosition;$old.Delete();$pic=$slide.Shapes.AddPicture((Join-Path $out ('assets/'+$gif.file)),0,-1,[single]($gif.left*$scale),[single]($gif.top*$scale),[single]($gif.width*$scale),[single]($gif.height*$scale));$pic.Name=$gif.name;$pic.AlternativeText='Scientific animation; '+$gif.file;while($pic.ZOrderPosition -gt $z){$pic.ZOrder(3)}}
 $rows=@()
 for($i=1;$i -le 12;$i++){
  $slide=$pres.Slides.Item($i)
  $slide.SlideShowTransition.EntryEffect=0
  $slide.SlideShowTransition.AdvanceOnTime=0
  $slide.SlideShowTransition.AdvanceOnClick=-1
  foreach($note in @($slide.NotesPage.Shapes)){if($note.HasTextFrame -eq -1){$note.TextFrame.TextRange.Text=''}}
  $previousAt=0;$events=@()
  foreach($cue in @($expanded|Where-Object {$_.slide -eq $i}|Sort-Object at)){
   $shape=$slide.Shapes.Item([string]$cue.name)
   $type=switch($cue.kind){'motion'{0};'grow'{59};'shrink'{59};'wipe'{22};'exit'{1};'rise'{39};'fly'{2};default{1}}
   $effect=$slide.TimeLine.MainSequence.AddEffect($shape,$type,0,2)
   $effect.Timing.Duration=[single]$cue.duration
   # All WithPrevious effects share this slide-start animation group.
   # PowerPoint native-render inspection confirms absolute delays within the group.
   $effect.Timing.TriggerDelayTime=[single]$cue.at
   if($cue.kind -eq 'motion'){
    $b=$effect.Behaviors.Add(1)
    $dx=([double]$cue.dx).ToString('0.########',[Globalization.CultureInfo]::InvariantCulture)
    $dy=([double]$cue.dy).ToString('0.########',[Globalization.CultureInfo]::InvariantCulture)
    $b.MotionEffect.Path='M 0 0 L '+$dx+' '+$dy+' E'
    $b.Timing.Duration=[single]$cue.duration
    if($cue.autoReverse){$effect.Timing.AutoReverse=-1}
   }
   if($cue.kind -eq 'grow' -or $cue.kind -eq 'shrink'){$effect.EffectParameters.Size=[single]$cue.scale}
   if($cue.kind -eq 'wipe' -or $cue.kind -eq 'fly'){$effect.EffectParameters.Direction=if($cue.direction){[int]$cue.direction}else{2}}
   if($cue.kind -eq 'exit'){$effect.Exit=-1}
   $events+=@{name=$cue.name;kind=$cue.kind;at=$cue.at;duration=$cue.duration;relative_delay=$effect.Timing.TriggerDelayTime}
  }
  if($i -eq 7){foreach($shape in @($slide.Shapes)){if($shape.HasChart -eq -1){$shape.Chart.SeriesCollection(1).DataLabels().Position=2;$eff=$slide.TimeLine.MainSequence.AddEffect($shape,22,0,2);$eff.Timing.Duration=2;$eff.Timing.TriggerDelayTime=14;$eff.EffectParameters.Direction=4}}}
  $overflow=@()
  foreach($shape in @($slide.Shapes)){if($shape.HasTextFrame -eq -1 -and $shape.TextFrame.HasText -eq -1){if($shape.TextFrame2.TextRange.BoundHeight -gt $shape.Height+3){$overflow+=@{shape=$shape.Name;text=$shape.TextFrame.TextRange.Text;bound=$shape.TextFrame2.TextRange.BoundHeight;height=$shape.Height}}}}
  $rows+=@{slide=$i;manual_advance=$true;native_effects=$slide.TimeLine.MainSequence.Count;events=$events;overflow=$overflow}
 }
 $pres.SlideShowSettings.AdvanceMode=1
 $pres.SlideShowSettings.ShowType=1
 $pres.SlideShowSettings.LoopUntilStopped=0
 $candidate=Join-Path $work ('creative-native-'+$Revision+'.pptx')
 $pres.SaveAs($candidate,24)
 # Static fallback shows each animation's final explanatory frame.
 foreach($gif in $contract.gifs){$slide=$pres.Slides.Item($gif.slide);$old=$slide.Shapes.Item($gif.name);$z=$old.ZOrderPosition;$old.Delete();$pic=$slide.Shapes.AddPicture((Join-Path $out ('assets/'+$gif.poster)),0,-1,[single]($gif.left*$scale),[single]($gif.top*$scale),[single]($gif.width*$scale),[single]($gif.height*$scale));while($pic.ZOrderPosition -gt $z){$pic.ZOrder(3)}}
 for($i=1;$i -le 12;$i++){$pres.Slides.Item($i).Export((Join-Path $out ('slides/slide-'+$i+'.png')),'PNG',1920,1080)}
 $pres.SaveAs((Join-Path $out ('INVISIBLE_SHIELD_CREATIVE_'+$Revision+'.pdf')),32)
 @{status='AUTHORED_PENDING_VISUAL_AND_PLAYBACK_QA';build_id=$contract.build_id;revision=$Revision;candidate=$candidate;manual_slide_advancement=$true;automatic_slide_transitions=$false;powerpoint_version=$app.Version;rows=$rows;embedded_animation_assets=$contract.gifs;mp4_embedded=$false}|ConvertTo-Json -Depth 10|Set-Content -LiteralPath (Join-Path $out ('qa/native-authoring-'+$Revision+'.json')) -Encoding UTF8
 Write-Output $candidate
}finally{if($null -ne $pres){$pres.Saved=-1;$pres.Close()};if($initial -eq 0 -and $app.Presentations.Count -eq 0){$app.Quit()};[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
