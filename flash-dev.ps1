param([Parameter(Mandatory=$true)][string]$Port)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run setup-dev.ps1 first.' }
if (-not (Test-Path -LiteralPath 'firmware\wifi.json')) {
    throw 'Create firmware/wifi.json from its example, or recover it with tools/body_probe.py --save-config.'
}
$backup = 'runtime/device-backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
& $python tools/body_device.py --port $Port --config firmware/wifi.json --backup $backup
exit $LASTEXITCODE
