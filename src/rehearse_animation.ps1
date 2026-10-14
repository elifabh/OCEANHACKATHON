$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$app=New-Object -ComObject PowerPoint.Application
$initialCount=$app.Presentations.Count;$pres=$null
try {
 $pres=$app.Presentations.Open((Join-Path $projectRoot 'work/story_20261014/compact-ready.pptx'),-1,0,0)
 $seconds=@(3,14,8,8,30,3)
 for($i=1;$i -le 6;$i++) {$pres.Slides.Item($i).SlideShowTransition.AdvanceTime=[double]$seconds[$i-1]}
 $movie=Join-Path $projectRoot 'work/story_20261014/native-animation-rehearsal.mp4'
 $pres.CreateVideo($movie,$true,3,720,20,75)
 $watch=[Diagnostics.Stopwatch]::StartNew()
 do {Start-Sleep -Seconds 2;$status=$pres.CreateVideoStatus;if($watch.Elapsed.TotalSeconds -gt 240){throw 'PowerPoint render exceeded four minutes'}} while($status -ne 3 -and $status -ne 4)
 if($status -ne 3){throw 'PowerPoint could not render the native animation rehearsal'}
 @{status='PASS';method='Native PowerPoint CreateVideo';seconds=66;elapsed_seconds=$watch.Elapsed.TotalSeconds;file=$movie} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $projectRoot 'work/story_20261014/native-animation-rehearsal.json') -Encoding UTF8
 Write-Output ('Native animation rehearsal rendered: '+$movie)
} finally {if($pres){try{$pres.Saved=-1;$pres.Close()}catch{}};if($initialCount -eq 0 -and $app.Presentations.Count -eq 0){$app.Quit()};[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
