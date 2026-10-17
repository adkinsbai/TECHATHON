param([string]$Python)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$venv = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not $Python -and (Test-Path -LiteralPath $venv)) {
    $Python = $venv
}
if (-not $Python) {
    $Python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Install Python 3.12, or pass -Python with its full executable path.'
}
& $Python -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required.' }
if (-not (Test-Path -LiteralPath $venv)) {
    & $Python -m venv (Join-Path $PSScriptRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the development environment.' }
}
& $venv -m pip install -r body-requirements.txt -r companion/requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $venv tools/body_setup.py --check-deps
if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
Write-Host 'Ready. Run start-dev.cmd. Data remains in %APPDATA%\Xiaonuan.'
