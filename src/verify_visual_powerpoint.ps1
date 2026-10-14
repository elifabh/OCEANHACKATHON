param([switch]$Final)
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$work=Join-Path $root 'work/visual_v2';$out=Join-Path $root 'outputs/presentations_visual_v2_20261014'
$app=New-Object -ComObject PowerPoint.Application;$initialCount=$app.Presentations.Count;$pres=$null
try {
 if($Final){
  $rows=@()
  foreach($v in @('compact','extended','friday')){
   $name=if($v -eq 'compact'){'SUNDAY_3_MINUTES_FINAL_VERIFIED'}elseif($v -eq 'extended'){'SUNDAY_5_MINUTES_FINAL_VERIFIED'}else{'FRIDAY_INVITATION'}
   $pres=$app.Presentations.Open((Join-Path $out ($name+'.pptx')),-1,0,0)
   $dir=Join-Path $work ('final-render-'+$v);New-Item -ItemType Directory -Force -Path $dir | Out-Null
   for($i=1;$i -le $pres.Slides.Count;$i++){$pres.Slides.Item($i).Export((Join-Path $dir ('slide-'+$i+'.png')),'PNG',1920,1080)}
   $rows+=@{variant=$v;slides=$pres.Slides.Count;native_open='PASS';native_render='PASS';version=$app.Version}
   $pres.Close();$pres=$null
  }
  $rows | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $work 'final-powerpoint-check.json') -Encoding UTF8
 } else {
  $pres=$app.Presentations.Open((Join-Path $work 'compact-native.pptx'),-1,0,0)
  $seconds=@(3,14,3,8,30,3)
  for($i=1;$i -le 6;$i++){$pres.Slides.Item($i).SlideShowTransition.AdvanceTime=[double]$seconds[$i-1]}
  $movie=Join-Path $work 'native-animation-rehearsal.mp4'
  $pres.CreateVideo($movie,$true,3,720,20,75)
  $watch=[Diagnostics.Stopwatch]::StartNew()
  do {Start-Sleep -Seconds 2;$status=$pres.CreateVideoStatus;if($watch.Elapsed.TotalSeconds -gt 240){throw 'Native rehearsal render exceeded four minutes'}} while($status -ne 3 -and $status -ne 4)
  if($status -ne 3){throw 'Native PowerPoint animation render failed'}
  @{status='PASS';method='PowerPoint CreateVideo, real native animations';expected_nominal_seconds=61;file=$movie;elapsed_seconds=$watch.Elapsed.TotalSeconds} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $work 'native-animation-rehearsal.json') -Encoding UTF8
  $pres.Saved=-1;$pres.Close();$pres=$null
 }
} finally {if($pres){try{$pres.Saved=-1;$pres.Close()}catch{}};if($initialCount -eq 0 -and $app.Presentations.Count -eq 0){$app.Quit()};[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
