param([switch]$Restart)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run setup-dev.ps1 first.' }
if ($Restart) {
    $owners = @(Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
    if ($owners.Count -gt 1) { throw 'Several processes own port 8765; cannot restart.' }
    if ($owners.Count -eq 1) {
        $running = Get-CimInstance Win32_Process -Filter "ProcessId=$($owners[0])"
        $tokens = @([regex]::Matches([string]$running.CommandLine, '"[^"]*"|\S+') |
            ForEach-Object { $_.Value.Trim('"') })
        # Windows venv's launcher can delegate to the base python.exe. In that
        # case identify its still-running parent through this exact venv path.
        if ($tokens.Count -eq 3 -and $tokens[1] -eq '-m' -and
                $tokens[2] -eq 'xiaonuan_app' -and $tokens[0] -ine $python) {
            $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($running.ParentProcessId)"
            if ($parent -and $parent.ExecutablePath -ieq $python) {
                $tokens = @([regex]::Matches([string]$parent.CommandLine, '"[^"]*"|\S+') |
                    ForEach-Object { $_.Value.Trim('"') })
            }
        }
        if ($tokens.Count -ne 3 -or $tokens[0] -ine $python -or
            $tokens[1] -ne '-m' -or $tokens[2] -ne 'xiaonuan_app') {
            throw 'The listener is not this checkout''s source app. Close it manually first.'
        }
        $status = Invoke-RestMethod 'http://127.0.0.1:8765/api/setup/status' -TimeoutSec 5
        if ($status.app -ne 'xiaonuan') { throw 'Unrecognized service; cannot restart.' }
        Invoke-RestMethod 'http://127.0.0.1:8765/api/setup/shutdown' -Method Post `
            -Headers @{'X-Xiaonuan'='takeover'} -TimeoutSec 5 | Out-Null
        for ($attempt = 0; $attempt -lt 40; $attempt++) {
            if (-not (Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 250
        }
        if (Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction SilentlyContinue) {
            throw 'The source app has not stopped; no second instance was started.'
        }
        # The HTTP listener closes before SSE cleanup and the TCP bridge exit.
        # Starting earlier can permanently fail the new bridge's bind to 5000.
        Wait-Process -Id $running.ProcessId -Timeout 15 -ErrorAction SilentlyContinue
        if (Get-Process -Id $running.ProcessId -ErrorAction SilentlyContinue) {
            throw 'Source cleanup is still running; no second instance was started.'
        }
    }
}
& $python -m xiaonuan_app
exit $LASTEXITCODE
