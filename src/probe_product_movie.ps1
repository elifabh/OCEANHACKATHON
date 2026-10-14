$ErrorActionPreference='Stop'
$productRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pitchOut=Join-Path $productRoot 'outputs/final_delivery_20261014'
$movie=Join-Path $pitchOut 'DEMO_75_SECONDS.mp4'
$app=New-Object -ComObject PowerPoint.Application;$initialCount=$app.Presentations.Count;$pres=$null;$show=$null
$result=@{source_file=$movie;source_sha256=(Get-FileHash -LiteralPath $movie).Hash;build_id=(Get-Content -LiteralPath (Join-Path $productRoot 'outputs/map/build_manifest.json') -Raw | ConvertFrom-Json).build_id;powerpoint_version=$app.Version;final_decks_modified=$false;fallback='Verified native timed app stills; continuous film in offline HTML'}
try {
 $pres=$app.Presentations.Add(0);$pres.PageSetup.SlideWidth=960;$pres.PageSetup.SlideHeight=540;$sl=$pres.Slides.Add(1,12)
 $clip=$sl.Shapes.AddMediaObject2($movie,0,-1,0,0,960,540);$clip.Name='final-movie-playback-probe';$clip.AnimationSettings.PlaySettings.PlayOnEntry=-1;$clip.AnimationSettings.PlaySettings.HideWhileNotPlaying=0
 $probe=Join-Path $productRoot 'work/product_pitch/final-movie-playback-probe.pptx';$pres.SaveAs($probe,24);$pres.Close();$pres=$null
 $app.Visible=-1;$pres=$app.Presentations.Open($probe,0,0,-1);$clip=$pres.Slides.Item(1).Shapes.Item('final-movie-playback-probe');$pres.SlideShowSettings.ShowType=2;$pres.SlideShowSettings.AdvanceMode=1;$show=$pres.SlideShowSettings.Run();Start-Sleep -Milliseconds 700
 $player=$show.View.Player($clip.Id);$player.Play();$samples=@()
 for($i=1;$i -le 5;$i++){Start-Sleep -Seconds 1;$samples+=@{second=$i;position_ms=$player.CurrentPosition;state=$player.State}}
 $maximum=($samples | ForEach-Object {$_.position_ms} | Measure-Object -Maximum).Maximum
 $result.status=if($maximum -gt 1500){'PASS'}else{'FAIL_PLAYER_DID_NOT_ADVANCE'};$result.samples=$samples;$result.duration_ms=$clip.MediaFormat.Length;$result.saved_reopened_visible=$true;$result.play_invoked=$true
}catch{$result.status='BLOCKED_RUNTIME';$result.error=$_.Exception.Message}
finally{if($null -ne $show){try{$show.View.Exit()}catch{}};if($null -ne $pres){try{$pres.Saved=-1;$pres.Close()}catch{}};try{if($initialCount -eq 0 -and $app.Presentations.Count -eq 0){$app.Quit()}}catch{};[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
$result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $pitchOut 'qa/powerpoint-movie-probe.json') -Encoding UTF8
$result | ConvertTo-Json -Depth 8
