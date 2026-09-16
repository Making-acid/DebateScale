$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$candidates = @(
    "C:\Users\device\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
    (Join-Path $projectRoot "..\.venv\Scripts\python.exe")
)

$pythonExe = $null
foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) {
        try {
            & $candidate --version *> $null
            & $candidate -c "import pypdf, reportlab" *> $null
            if ($LASTEXITCODE -eq 0) {
                $pythonExe = $candidate
                break
            }
        } catch { }
    }
}

if (-not $pythonExe) {
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { $pythonExe = $command.Source }
}

if (-not $pythonExe) {
    throw "Python 3.12+ with the required report libraries was not found."
}

Set-Location -LiteralPath $projectRoot
$stateDir = Join-Path $projectRoot "web\.local"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$logPath = Join-Path $stateDir "server.log"
"[$(Get-Date -Format o)] Starting CRE v0.8.2" | Out-File -FilePath $logPath -Encoding utf8
$env:PYTHONUNBUFFERED = "1"
$ErrorActionPreference = "Continue"
& $pythonExe "web\server.py" 2>&1 | ForEach-Object {
    $line = $_.ToString()
    Write-Output $line
    Add-Content -LiteralPath $logPath -Value $line -Encoding utf8
}
