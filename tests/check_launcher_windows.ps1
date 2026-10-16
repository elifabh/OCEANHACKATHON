param()
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$testRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot 'tmp\launcher_without_python'))
if (-not $testRoot.StartsWith($projectRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Test path is outside the project' }
New-Item -ItemType Directory -Force -Path (Join-Path $testRoot 'outputs') | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'START_DEMO.bat') -Destination (Join-Path $testRoot 'START_DEMO.bat') -Force
$mapLink = Join-Path $testRoot 'outputs\map'
$actualMap = Join-Path $projectRoot 'outputs\map'
if (-not (Test-Path -LiteralPath $mapLink)) { New-Item -ItemType Junction -Path $mapLink -Target $actualMap | Out-Null }
if (Test-Path -LiteralPath (Join-Path $testRoot '.venv')) { throw 'Fallback test must have no Python environment' }
$resolvedLink = Get-Item -LiteralPath $mapLink
if ($resolvedLink.Target -ne $actualMap) { throw 'Unexpected test junction target' }
$normal = Start-Process -FilePath (Join-Path $projectRoot 'START_DEMO.bat') -WorkingDirectory $projectRoot -WindowStyle Hidden -Wait -PassThru
$fallback = Start-Process -FilePath (Join-Path $testRoot 'START_DEMO.bat') -WorkingDirectory $testRoot -WindowStyle Hidden -Wait -PassThru
if ($normal.ExitCode -ne 0 -or $fallback.ExitCode -ne 0) { throw 'A launcher route failed' }
$manifest = Get-Content -LiteralPath (Join-Path $actualMap 'build_manifest.json') -Raw | ConvertFrom-Json
[ordered]@{status='PASS';build_id=$manifest.build_id;normal_exit=$normal.ExitCode;missing_python_exit=$fallback.ExitCode;no_large_inputs_copied=$true;method='Windows shell execution of the actual batch file, equivalent file association to Explorer double-click; no physical mouse double-click claimed. Offline rendering separately verified in Windows Chrome and Edge.'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $projectRoot 'outputs\product_cape_clear_20261015\qa\windows-launch.json') -Encoding utf8
Write-Output 'PASS: normal Windows launch and missing-Python fallback; both exit 0.'
