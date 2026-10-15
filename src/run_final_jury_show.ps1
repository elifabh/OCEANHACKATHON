param([switch]$Acceptance)
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$out=Join-Path $root 'outputs/final_overnight_20261015'
$build=(Get-Content -LiteralPath (Join-Path $out 'app/build_manifest.json') -Raw|ConvertFrom-Json).build_id
$contract=Get-Content -LiteralPath (Join-Path $out 'presentation_contract.json') -Raw|ConvertFrom-Json
if($contract.build_id -ne $build){throw 'Presentation/app build mismatch'}
$run=Join-Path $root ('work/final_overnight/show-'+[DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force -Path $run|Out-Null
$node=Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
$movieArgs='"'+(Join-Path $root 'src/play_jury_movie.mjs')+'" "'+$run+'"'
$movieProcess=Start-Process -FilePath $node -ArgumentList $movieArgs -WorkingDirectory $root -WindowStyle Hidden -PassThru
$app=$null;$pres=$null;$show=$null;$rows=@();$initial=0;$result=@{build_id=$build;mode='Native PowerPoint with independent actual Chrome MP4 playback';human_narration_rehearsed=$false;timed_schedule_seconds=600}
try{
 for($i=0;$i -lt 100 -and -not(Test-Path (Join-Path $run 'ready.json'));$i++){Start-Sleep -Milliseconds 100}
 if(-not(Test-Path (Join-Path $run 'ready.json'))){throw 'Video player did not become ready'}
 $app=New-Object -ComObject PowerPoint.Application;$initial=$app.Presentations.Count;$app.Visible=-1
 $pres=$app.Presentations.Open((Join-Path $out 'INVISIBLE_SHIELD_JURY_10_MIN_FINAL.pptx'),-1,0,-1)
 $pres.SlideShowSettings.ShowType=1;$pres.SlideShowSettings.AdvanceMode=2;$pres.SlideShowSettings.LoopUntilStopped=0
 $pres.SlideShowSettings.StartingSlide=1;$pres.SlideShowSettings.EndingSlide=12
 $show=$pres.SlideShowSettings.Run();$watch=[Diagnostics.Stopwatch]::StartNew();$last=0;$cue=$false
 while($watch.Elapsed.TotalSeconds -lt 635){
  try{$pos=$show.View.CurrentShowPosition;$elapsed=$show.View.SlideElapsedTime;if($show.View.State -eq 5 -or $pos -gt 12){break}}catch{break}
  if($pos -gt 0 -and $pos -ne $last){$rows+=@{slide=$pos;elapsed_seconds=$watch.Elapsed.TotalSeconds};$last=$pos;Write-Output ('Slide '+$pos+' at '+[Math]::Round($watch.Elapsed.TotalSeconds,1)+'s')}
  if($pos -eq 10 -and $elapsed -ge 35 -and -not $cue){Set-Content -LiteralPath (Join-Path $run 'go') -Value 'play';$cue=$true;$result.movie_cue_seconds=$watch.Elapsed.TotalSeconds}
  Start-Sleep -Milliseconds 200
 }
 $result.elapsed_seconds=$watch.Elapsed.TotalSeconds;$result.slide_transitions=$rows
 if(Test-Path (Join-Path $run 'movie-played.json')){$result.movie=Get-Content -LiteralPath (Join-Path $run 'movie-played.json') -Raw|ConvertFrom-Json}
 if($last -ne 12 -or $rows.Count -ne 12 -or $result.movie.status -ne 'PASS'){throw 'Full slide/movie journey did not complete'}
 if([Math]::Abs($watch.Elapsed.TotalSeconds-600) -gt 12){throw 'Native schedule drift exceeds transition tolerance'}
 $result.status='PASS';$result.checks=@('All twelve slides played in approved order in actual Windows PowerPoint','Real silent 75-second MP4 played completely after slide ten narration','Total native show completed within 12-second transition/startup tolerance of the 600-second schedule')
}catch{$result.status='FAIL';$result.error=$_.Exception.Message;Write-Output $_.Exception.Message}
finally{
 Set-Content -LiteralPath (Join-Path $run 'stop') -Value 'end'
 if($null -ne $show){try{$show.View.Exit()}catch{}}
 if($null -ne $pres){try{$pres.Saved=-1;$pres.Close()}catch{}}
 if($null -ne $app){try{if($initial -eq 0 -and $app.Presentations.Count -eq 0){$app.Quit()}}catch{};[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
 $result|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $run 'result.json') -Encoding UTF8
 if($Acceptance){$result|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $out 'qa/full-jury-rehearsal.json') -Encoding UTF8}
}
$result|ConvertTo-Json -Depth 8
if($result.status -ne 'PASS'){exit 1}
