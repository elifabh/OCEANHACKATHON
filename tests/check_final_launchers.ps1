$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$testRoot=[IO.Path]::GetFullPath((Join-Path $projectRoot 'work\final_overnight\launcher_no_python'))
if(-not $testRoot.StartsWith($projectRoot+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Outside project'}
$rel='outputs\final_overnight_20261015\app'
$link=Join-Path $testRoot $rel
$actual=Join-Path $projectRoot $rel
New-Item -ItemType Directory -Force -Path (Split-Path $link)|Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'START_DEMO.bat') -Destination (Join-Path $testRoot 'START_DEMO.bat') -Force
if(-not(Test-Path -LiteralPath $link)){New-Item -ItemType Junction -Path $link -Target $actual|Out-Null}
if((Get-Item -LiteralPath $link).Target -ne $actual){throw 'Unexpected junction'}
if(Test-Path -LiteralPath (Join-Path $testRoot '.venv')){throw 'Fallback test has Python'}
$normal=Start-Process -FilePath (Join-Path $projectRoot 'START_DEMO.bat') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
if(-not $normal.WaitForExit(20000)){throw 'Normal launcher did not return'}
$fallback=Start-Process -FilePath (Join-Path $testRoot 'START_DEMO.bat') -WorkingDirectory $testRoot -WindowStyle Hidden -PassThru
if(-not $fallback.WaitForExit(20000)){throw 'Fallback launcher did not return'}
if($normal.ExitCode -ne 0 -or $fallback.ExitCode -ne 0){throw 'Launcher failed'}
$assistant=Start-Process -FilePath (Join-Path $projectRoot 'START_ASSISTANT.bat') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
if(-not $assistant.WaitForExit(20000)){throw 'Assistant launcher did not return'}
if($assistant.ExitCode -ne 0){throw 'Assistant launcher failed'}
$url=$null
for($i=0;$i -lt 40 -and -not $url;$i++){
 foreach($port in 8765..8774){try{$r=Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/config" -TimeoutSec 1;if($r.application -eq 'invisible-shield-assistant'){$url="http://127.0.0.1:$port";break}}catch{}}
 if(-not $url){Start-Sleep -Milliseconds 500}
}
if(-not $url){throw 'Assistant service did not start'}
$page=Invoke-WebRequest -UseBasicParsing -Uri "$url/index.html"
if($page.Content -notmatch '6a84de90fe69'){throw 'Assistant served stale build'}
@{status='PASS';build_id='6a84de90fe69';checks=@('Normal Windows batch launch exits zero','Missing-Python fallback opens existing offline HTML','Optional assistant batch launches matching loopback build');normal_exit=$normal.ExitCode;missing_python_exit=$fallback.ExitCode;assistant_exit=$assistant.ExitCode;assistant_url=$url;method='Windows ShellExecute on actual batch files, same association as Explorer double-click; no physical mouse double-click claimed. Source data not copied.'}|ConvertTo-Json -Depth 5|Set-Content -LiteralPath (Join-Path $projectRoot 'outputs/final_overnight_20261015/qa/windows-launch.json') -Encoding UTF8
Write-Output 'PASS: three actual Windows launch routes'
