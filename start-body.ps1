param(
    [string]$CompanionRoot,
    [string]$Python,
    [ValidateRange(1024,65535)][int]$CompanionPort = 8765,
    [ValidateRange(1024,65535)][int]$Port = 5000,
    [ValidateRange(0,100)][int]$Volume = 10,
    [switch]$NoBrowser,
    [switch]$LibraryOnly
)
$ErrorActionPreference = 'Stop'

function Get-ProcessTokens($Process) {
    return @([regex]::Matches([string]$Process.CommandLine, '"[^"]*"|\S+') | ForEach-Object { $_.Value.Trim('"') })
}

function Test-CompanionProcess($Process, [string]$Root) {
    $tokens = @(Get-ProcessTokens $Process)
    if ($tokens.Count -lt 2) { return $false }
    $exe = [IO.Path]::GetFileName($tokens[0])
    $appIndex = if ($exe -match '^uvicorn(?:\.exe)?$') { 1 } elseif ($exe -match '^python(?:w|3(?:\.12)?)?(?:\.exe)?$' -and $tokens.Count -ge 4 -and $tokens[1] -eq '-m' -and $tokens[2] -eq 'uvicorn') { 3 } else { return $false }
    if ($tokens[$appIndex] -ne 'app.server:app') { return $false }
    $dirIndex = [array]::IndexOf($tokens, '--app-dir')
    # A module name alone does not identify the checkout used by another process.
    if ($dirIndex -lt 0) { return $false }
    if ($dirIndex -ge 0) {
        if ($dirIndex + 1 -ge $tokens.Count -or $tokens[$dirIndex + 1].TrimEnd('\','/') -ine $Root.TrimEnd('\','/')) { return $false }
    }
    return $true
}

function Test-BridgeProcess($Process, [string]$Url, [int]$TcpPort) {
    $tokens = @(Get-ProcessTokens $Process)
    if ($tokens.Count -lt 7 -or [IO.Path]::GetFileName($tokens[0]) -notmatch '^python(?:w|3(?:\.12)?)?(?:\.exe)?$' -or $tokens[1] -ne '-m' -or $tokens[2] -ne 'body_bridge') { return $false }
    $urlIndex, $portIndex = [array]::IndexOf($tokens, '--companion-url'), [array]::IndexOf($tokens, '--port')
    return ($urlIndex -ge 0 -and $urlIndex + 1 -lt $tokens.Count -and $tokens[$urlIndex + 1] -eq $Url -and
        $portIndex -ge 0 -and $portIndex + 1 -lt $tokens.Count -and $tokens[$portIndex + 1] -eq "$TcpPort")
}

function Get-Listener([int]$ListenPort) {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $ListenPort -ErrorAction SilentlyContinue)
    $owners = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($owners.Count -gt 1) { throw "Port $ListenPort has several owners. Close the conflicting service manually." }
    if ($owners.Count -eq 0) { return $null }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($owners[0])"
    if (-not $process) { throw "Cannot identify listener on port $ListenPort." }
    return [pscustomobject]@{ Process=$process; Addresses=@($listeners.LocalAddress); ProcessId=$owners[0] }
}

function Get-BodyStatus([string]$Url) {
    try {
        $status = Invoke-RestMethod "$Url/api/body/status" -TimeoutSec 3
        if ($null -ne $status.connected -and $null -ne $status.settings.volume) { return $status }
    } catch { }
    return $null
}

function Start-HiddenPython([string[]]$Arguments, [string]$Working, [string]$Name) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    # Explicit quoting supports paths containing spaces and Chinese characters.
    $quoted = @($Arguments | ForEach-Object { '"' + $_.Replace('"','\"') + '"' })
    $process = Start-Process -FilePath $Python -ArgumentList $quoted -WorkingDirectory $Working -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtime "$Name-$stamp.out.log") `
        -RedirectStandardError (Join-Path $runtime "$Name-$stamp.err.log")
    return $process
}

if ($LibraryOnly) { return }

$repo = $PSScriptRoot
$runtime = Join-Path $repo '.body-runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
try {
    $configPath = Join-Path $repo '.local-body.json'
    $config = if (Test-Path -LiteralPath $configPath) { Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
    if (-not $CompanionRoot) { $CompanionRoot = $env:XIAONUAN_COMPANION }
    if (-not $CompanionRoot -and $config) { $CompanionRoot = $config.companion_root }
    if (-not $CompanionRoot) { throw 'Run install_companion.py --target YOUR_COMPANION_PATH --remember once, or provide -CompanionRoot.' }
    $CompanionRoot = (Resolve-Path -LiteralPath $CompanionRoot).Path
    if (-not $Python -and $config) { $Python = $config.python }
    if (-not $Python) { $Python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe' }
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "Python 3.12 not found: $Python" }
    $url = "http://127.0.0.1:$CompanionPort"
    $bridge = Get-Listener $Port
    if ($bridge -and -not (Test-BridgeProcess $bridge.Process $url $Port)) {
        throw "TCP $Port is occupied by PID $($bridge.ProcessId). Close the old wifi_demo or conflicting service manually; it has not been stopped."
    }
    $companion = Get-Listener $CompanionPort
    if ($companion) {
        if (-not (Test-CompanionProcess $companion.Process $CompanionRoot)) { throw "Port $CompanionPort belongs to an unrecognized process (PID $($companion.ProcessId)); it has not been stopped." }
        if (@($companion.Addresses | Where-Object { $_ -notin @('127.0.0.1','::1') }).Count) { throw 'Companion listener must use loopback only. Close the LAN-exposed service manually.' }
    }
    & $Python (Join-Path $repo 'tools\body_setup.py') --check-deps
    if ($LASTEXITCODE -ne 0) { throw 'Missing Python packages. Install body-requirements.txt and the existing Companion requirements with the configured Python.' }
    $installOutput = & $Python (Join-Path $repo 'install_companion.py') --target $CompanionRoot --remember
    if ($LASTEXITCODE -ne 0) { throw 'Source installation failed; inspect the error above.' }
    $installed = ($installOutput -join "`n") | ConvertFrom-Json
    $backendChanged = @($installed.changed | Where-Object { $_ -in @('app/server.py','app/body_runtime.py') }).Count -gt 0
    $status = Get-BodyStatus $url
    if ($companion -and ($backendChanged -or -not $status)) {
        # Re-read the listener and its command immediately before stopping it.
        $current = Get-Listener $CompanionPort
        if (-not $current -or $current.ProcessId -ne $companion.ProcessId -or -not (Test-CompanionProcess $current.Process $CompanionRoot)) {
            throw 'Companion listener changed during startup; nothing was stopped.'
        }
        Stop-Process -Id $current.ProcessId -ErrorAction Stop
        $deadline = (Get-Date).AddSeconds(10)
        while ((Get-Listener $CompanionPort) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
        if (Get-Listener $CompanionPort) { throw 'Companion port did not close after restart request.' }
        $companion = $null
    }
    if (-not $companion) {
        $started = Start-HiddenPython @('-m','uvicorn','app.server:app','--host','127.0.0.1','--port',"$CompanionPort",'--app-dir',$CompanionRoot) $CompanionRoot 'companion'
        $companionPid = $started.Id
    } else { $companionPid = $companion.ProcessId }
    $deadline = (Get-Date).AddSeconds(60)
    while (-not (Get-BodyStatus $url) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
    if (-not (Get-BodyStatus $url)) { throw "Companion body routes are not ready. Logs: $runtime" }
    if (-not $bridge) {
        # Detect a late port collision; never stop its owner.
        if (Get-Listener $Port) { throw "TCP $Port was occupied during startup; retry after closing the conflicting service." }
        $started = Start-HiddenPython @('-m','body_bridge','--companion-url',$url,'--port',"$Port",'--volume',"$Volume") $repo 'bridge'
        $bridgePid = $started.Id
        $deadline = (Get-Date).AddSeconds(15)
        while (-not (Get-Listener $Port) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 300 }
        $bridge = Get-Listener $Port
        if (-not $bridge -or $bridge.ProcessId -ne $bridgePid -or -not (Test-BridgeProcess $bridge.Process $url $Port)) { throw "Bridge did not acquire TCP $Port. Logs: $runtime" }
    } else { $bridgePid = $bridge.ProcessId }
    @{ companion_pid=$companionPid; bridge_pid=$bridgePid; companion_url=$url; tcp_port=$Port; volume=$Volume; checked_at=(Get-Date).ToString('o') } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime 'services.json') -Encoding UTF8
    Write-Host "Companion PID $companionPid; body bridge PID $bridgePid; TCP $Port; initial volume $Volume%."
    Write-Host "Open $url . Logs: $runtime . Waiting for the board does not confirm hardware acceptance."
    if (-not $NoBrowser) { Start-Process $url }
} catch {
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $runtime 'startup-error.log') -Encoding UTF8
    Write-Error $_
    exit 1
}
