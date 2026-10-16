$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$target=Join-Path $root 'outputs/final_creative_20261015/INVISIBLE_SHIELD_CREATIVE_FINAL_v3.pptx'
$app=New-Object -ComObject PowerPoint.Application
$initial=$app.Presentations.Count
if(@($app.Presentations|Where-Object {$_.FullName -eq $target}).Count){throw 'Close the revised deck before testing its launcher; existing user windows are preserved.'}
$opened=$null;$show=$null
try {
    & (Join-Path $root 'START_CREATIVE_JURY.bat')
    if($LASTEXITCODE -ne 0){throw 'Batch launcher failed'}
    $opened=@($app.Presentations|Where-Object {$_.FullName -eq $target})[0]
    if(-not $opened){throw 'Launcher did not open the revised deck'}
    $show=$opened.SlideShowWindow
    if($show.View.Slide.SlideIndex -ne 1){throw 'Launcher did not start at slide 1'}
    if($opened.SlideShowSettings.AdvanceMode -ne 1){throw 'Launcher did not select manual advancement'}
    @{status='PASS';launcher='START_CREATIVE_JURY.bat';opened_file=$opened.FullName;application=('PowerPoint '+$app.Version);started_slide=1;advance_mode='manual';system_movie_association='Not asserted; both actual films independently played to completion in Chrome.'}|ConvertTo-Json|Set-Content (Join-Path $root 'outputs/final_creative_20261015/qa/launcher-test.json') -Encoding UTF8
    Write-Output 'PASS: actual batch opened final v3 in manual PowerPoint slideshow.'
} finally {
    if($show){try{$show.View.Exit()}catch{}}
    if($opened){$opened.Saved=-1;$opened.Close()}
    if($initial -eq 0 -and $app.Presentations.Count -eq 0){$app.Quit()}
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}
