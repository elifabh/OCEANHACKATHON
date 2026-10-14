$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$app=New-Object -ComObject PowerPoint.Application;$pres=$null;$show=$null
try {
 $pres=$app.Presentations.Open((Join-Path $root 'outputs/presentations_visual_v2_20261014/SUNDAY_3_MINUTES_FINAL_VERIFIED.pptx'),-1,0,-1)
 $pres.SlideShowSettings.ShowType=2;$pres.SlideShowSettings.AdvanceMode=2
 $show=$pres.SlideShowSettings.Run();$show.View.GotoSlide(5)
 $samples=@()
 for($n=0;$n -lt 7;$n++){Start-Sleep -Seconds 5;$samples+=@{elapsed=($n+1)*5;slide=$show.View.Slide.SlideIndex;state=$show.View.State}}
 @{method='Live installed PowerPoint windowed slideshow';samples=$samples;version=$app.Version} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $root 'work/visual_v2/live-slideshow.json') -Encoding UTF8
}finally{if($show){try{$show.View.Exit()}catch{}};if($pres){try{$pres.Close()}catch{}};[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
