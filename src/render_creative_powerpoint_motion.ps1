$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$out=Join-Path $root 'outputs/final_creative_20261015'
$app=New-Object -ComObject PowerPoint.Application;$initial=$app.Presentations.Count;$pres=$null
try{
 $pres=$app.Presentations.Open((Join-Path $out 'INVISIBLE_SHIELD_CREATIVE_FINAL_v3.pptx'),-1,0,0)
 $target=Join-Path $out 'qa/POWERPOINT_NATIVE_ANIMATION_REVIEW.mp4'
 $pres.CreateVideo($target,$false,32,1080,24,85)
 $watch=[Diagnostics.Stopwatch]::StartNew();$last=-1
 while($watch.Elapsed.TotalSeconds -lt 900){$status=$pres.CreateVideoStatus;if($status -ne $last){Write-Output ('PowerPoint video status '+$status);$last=$status};if($status -eq 3){break};if($status -eq 4){throw 'PowerPoint native video render failed'};Start-Sleep -Seconds 2}
 if($pres.CreateVideoStatus -ne 3){throw 'Native video render timeout'}
 @{status='RENDERED_PENDING_FRAME_INSPECTION';build_id='6a84de90fe69';renderer='Microsoft PowerPoint '+$app.Version;seconds_per_slide=32;slides=12;fps=24;vertical_resolution=1080;source='INVISIBLE_SHIELD_CREATIVE_FINAL_v3.pptx';review_video_only=$true;does_not_replace_live_narration_or_demo=$true;render_elapsed_seconds=$watch.Elapsed.TotalSeconds}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $out 'qa/native-motion-render.json') -Encoding UTF8
 Write-Output $target
}finally{if($pres){$pres.Saved=-1;$pres.Close()};if($initial -eq 0 -and $app.Presentations.Count -eq 0){$app.Quit()};[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
