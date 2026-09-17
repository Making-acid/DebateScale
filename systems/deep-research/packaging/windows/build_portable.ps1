param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$repoRoot = Resolve-Path (Join-Path $projectRoot "..\..")
$releaseRoot = Join-Path $repoRoot "release"
$workRoot = Join-Path $projectRoot "build\portable"
$distRoot = Join-Path $workRoot "dist"
$packageName = "DebateScale-Windows-v0.8.2"
$packageRoot = Join-Path $releaseRoot $packageName

New-Item -ItemType Directory -Force -Path $releaseRoot | Out-Null
if (Test-Path -LiteralPath $workRoot) {
    Remove-Item -LiteralPath $workRoot -Recurse -Force
}
if (Test-Path -LiteralPath $packageRoot) {
    Remove-Item -LiteralPath $packageRoot -Recurse -Force
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --noconsole `
    --name "DebateScale" `
    --paths (Join-Path $projectRoot "src") `
    --add-data "$(Join-Path $projectRoot 'web\static');web\static" `
    --add-data "$(Join-Path $projectRoot 'src\cre\prompts');cre\prompts" `
    --hidden-import faster_whisper `
    --hidden-import yt_dlp `
    --distpath $distRoot `
    --workpath (Join-Path $workRoot "work") `
    --specpath (Join-Path $workRoot "spec") `
    (Join-Path $projectRoot "web\server.py")

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

Move-Item -LiteralPath (Join-Path $distRoot "DebateScale") -Destination $packageRoot
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "shutdown.bat") -Destination $packageRoot
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README.txt") -Destination $packageRoot
Copy-Item -LiteralPath (Join-Path $repoRoot "LICENSE") -Destination $packageRoot

$zipPath = Join-Path $releaseRoot "$packageName.zip"
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Compress-Archive -LiteralPath $packageRoot -DestinationPath $zipPath -CompressionLevel Optimal
Write-Output $zipPath
