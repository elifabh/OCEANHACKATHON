$ErrorActionPreference='Stop'
$productRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pitchOut=Join-Path $productRoot 'outputs/final_delivery_20261014'
$app=New-Object -ComObject PowerPoint.Application;$initialCount=$app.Presentations.Count;$rows=@()
try {
 foreach($pair in @(@('main','SUNDAY_10_MINUTES'),@('compact','SUNDAY_5_MINUTES'),@('friday','FRIDAY_INVITATION'))){
  $pres=$null
  try{$pres=$app.Presentations.Open((Join-Path $pitchOut ($pair[1]+'.pptx')),0,0,0);$slides=@();$charts=0
   for($i=1;$i -le $pres.Slides.Count;$i++){$sl=$pres.Slides.Item($i);$png=Join-Path $pitchOut ('presentation_assets/'+$pair[0]+'/slide-'+$i+'.png');$before=(Get-FileHash -LiteralPath $png).Hash;$sl.Export($png,'PNG',1920,1080);$after=(Get-FileHash -LiteralPath $png).Hash;$chartCount=@($sl.Shapes | Where-Object {$_.HasChart -eq -1}).Count;$charts+=$chartCount;$slides+=@{slide=$i;render_unchanged=($before -eq $after);seconds=$sl.SlideShowTransition.AdvanceTime;effects=$sl.TimeLine.MainSequence.Count;charts=$chartCount}}
   $rows+=@{file=$pair[1]+'.pptx';opened_in_powerpoint=$true;slides=$slides;native_chart_count=$charts;powerpoint_version=$app.Version;status='PASS'}
  }finally{if($null -ne $pres){$pres.Close()}}
 }
 $rows | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $pitchOut 'qa/final-powerpoint-checks.json') -Encoding UTF8
 $rows | ConvertTo-Json -Depth 8
}finally{try{if($initialCount -eq 0 -and $app.Presentations.Count -eq 0){$app.Quit()}}catch{};[void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)}
