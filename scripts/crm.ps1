param(
    [ValidateSet('start','stop','status','sync','request','install-startup','monitor')][string]$Action = 'status',
    [string]$Path = '/rest/companies/search',
    [ValidateSet('GET','POST')][string]$Method = 'POST',
    [string]$BodyFile
)
$ErrorActionPreference = 'Stop'
$engine = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $engine 'local/crm-runtime'
$crm = 'C:/dev/gtm-crm'
$journal = Join-Path $engine 'local/GTM_Design_Partners_Etat.json'
$bun = Join-Path $env:APPDATA 'npm/node_modules/bun/bin/bun.exe'
$node = 'C:/Program Files/nodejs/node.exe'
$powershell = (Get-Process -Id $PID).Path
$control = Join-Path $runtime 'processes.json'
$stopFile = Join-Path $runtime 'STOP'
$credential = Join-Path $runtime 'credential.xml'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

function Write-JsonFile($value, $file) {
    $value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath ($file+'.tmp') -Encoding utf8
    Move-Item -LiteralPath ($file+'.tmp') -Destination $file -Force
}
function Test-Http($url) {
    try { $r=Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 8; return $r.StatusCode -eq 200 } catch { return $false }
}
function Get-ProcessState {
    if(Test-Path -LiteralPath $control) { try { return Get-Content -Raw -LiteralPath $control | ConvertFrom-Json } catch {} }
    return $null
}
function Test-OwnedProcess($entry) {
    if(-not $entry) { return $false }
    $p=Get-Process -Id $entry.id -ErrorAction SilentlyContinue
    return $null -ne $p -and $p.StartTime.ToUniversalTime().Ticks -eq ([datetimeoffset]$entry.started).UtcDateTime.Ticks
}
function Stop-OwnedTree($entry) {
    if(-not (Test-OwnedProcess $entry)) { return }
    function Stop-Children([int]$parentId) {
        foreach($child in Get-CimInstance Win32_Process -Filter "ParentProcessId=$parentId" -ErrorAction SilentlyContinue) {
            Stop-Children ([int]$child.ProcessId)
            Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    Stop-Children ([int]$entry.id)
    Stop-Process -Id $entry.id -Force -ErrorAction SilentlyContinue
}
function Invoke-Sync {
    Push-Location $crm
    try {
        & $bun run packages/db/scripts/project-from-journal.ts --journal $journal --report (Join-Path $runtime 'last-sync.json')
        if($LASTEXITCODE -ne 0) { throw 'CRM projection failed. See local/crm-runtime/supervisor.log.' }
    } finally { Pop-Location }
}
function Source-Stamp {
    $files=@(Get-Item -LiteralPath $journal)
    foreach($dir in @('inbox','evidence')) { $files += @(Get-ChildItem -LiteralPath (Join-Path $engine "local/$dir") -File -Filter '*.json') }
    return ($files | Sort-Object FullName | ForEach-Object { $_.FullName+':'+$_.LastWriteTimeUtc.Ticks+':'+$_.Length }) -join '|'
}
function Start-Worker([string]$name, [string]$file, [string[]]$arguments, [string]$directory) {
    foreach($suffix in @('out','err')) {
        $log=Join-Path $runtime "$name.$suffix.log"
        if((Test-Path -LiteralPath $log) -and (Get-Item -LiteralPath $log).Length -gt 2097152) { Move-Item -LiteralPath $log -Destination ($log+'.previous') -Force }
    }
    $p=Start-Process -FilePath $file -ArgumentList $arguments -WorkingDirectory $directory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime "$name.out.log") -RedirectStandardError (Join-Path $runtime "$name.err.log")
    return @{id=$p.Id; started=$p.StartTime.ToUniversalTime().ToString('o')}
}

switch($Action) {
    'request' {
        if(-not $Path.StartsWith('/rest/') -or $Path.Contains('..') -or $Path.Contains('://')) { throw 'Only local CRM REST paths are allowed.' }
        if($Method -eq 'POST' -and -not $Path.EndsWith('/search')) { throw 'POST is restricted to read-only search endpoints. GTM state changes belong in the journal.' }
        $saved=Import-Clixml -LiteralPath $credential
        $secret=[System.Net.NetworkCredential]::new('', $saved.Secret).Password
        try {
            $params=@{Uri=('http://localhost:3001'+$Path);Method=$Method;Headers=@{'x-api-key'=$secret};TimeoutSec=30}
            if($Method -eq 'POST') { $params.ContentType='application/json'; $params.Body=if($BodyFile){Get-Content -Raw -LiteralPath $BodyFile}else{'{}'} }
            Invoke-RestMethod @params | ConvertTo-Json -Depth 40
        } finally { $secret=$null }
    }
    'sync' { Invoke-Sync }
    'status' {
        $state=Get-ProcessState
        $report=if(Test-Path -LiteralPath (Join-Path $runtime 'last-sync.json')){Get-Content -Raw -LiteralPath (Join-Path $runtime 'last-sync.json') | ConvertFrom-Json}else{$null}
        $startup=(Get-ItemProperty -LiteralPath 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Run' -Name VisionPnlCRM -ErrorAction SilentlyContinue).VisionPnlCRM
        @{ interface='http://localhost:3000';api='http://localhost:3001';api_healthy=(Test-Http 'http://localhost:3001/health');ui_healthy=(Test-Http 'http://localhost:3000/sign-in');supervisor_alive=(Test-OwnedProcess $state.supervisor);credential_present=(Test-Path -LiteralPath $credential);startup_installed=([bool]$startup);last_sync=$report } | ConvertTo-Json -Depth 10
    }
    'install-startup' {
        $command='"'+$powershell+'" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "'+$PSCommandPath+'" -Action monitor'
        New-Item -Path 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Run' -Force | Out-Null
        New-ItemProperty -LiteralPath 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Run' -Name VisionPnlCRM -Value $command -PropertyType String -Force | Out-Null
        @{startup_installed=$true;scope='Current Windows user, at sign-in';command_file=$PSCommandPath} | ConvertTo-Json
    }
    'start' {
        if(Test-Path -LiteralPath $stopFile) { Remove-Item -LiteralPath $stopFile }
        $state=Get-ProcessState
        if(Test-OwnedProcess $state.supervisor) { @{already_running=$true;pid=$state.supervisor.id} | ConvertTo-Json; return }
        $args=@('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',('"'+$PSCommandPath+'"'),'-Action','monitor')
        $p=Start-Process -FilePath $powershell -ArgumentList $args -WindowStyle Hidden -PassThru
        @{started=$true;pid=$p.Id;logs=$runtime} | ConvertTo-Json
    }
    'stop' {
        'Stopped on request' | Set-Content -LiteralPath $stopFile
        $state=Get-ProcessState
        Stop-OwnedTree $state.api
        Stop-OwnedTree $state.app
        Stop-OwnedTree $state.supervisor
        @{stopped=$true;startup_entry_preserved=$true} | ConvertTo-Json
    }
    'monitor' {
        $mutex=[Threading.Mutex]::new($false,'Local\VisionPnlCRM')
        if(-not $mutex.WaitOne(0)) { return }
        if(Test-Path -LiteralPath $stopFile) { Remove-Item -LiteralPath $stopFile }
        $previousState=Get-ProcessState
        $state=@{supervisor=@{id=$PID;started=(Get-Process -Id $PID).StartTime.ToUniversalTime().ToString('o')};api=$(if(Test-OwnedProcess $previousState.api){$previousState.api}else{$null});app=$(if(Test-OwnedProcess $previousState.app){$previousState.app}else{$null})}
        $stamp=$null
        $dockerStarted=$false
        $env:API_HOST='127.0.0.1'
        $env:PORT='3001'
        $env:NODE_ENV='development'
        $env:NEXT_TELEMETRY_DISABLED='1'
        $env:CRM_TELEMETRY_DISABLED='1'
        $env:DO_NOT_TRACK='1'
        Write-JsonFile $state $control
        try {
            while(-not (Test-Path -LiteralPath $stopFile)) {
                try {
                    $previous=Get-Item -LiteralPath (Join-Path $runtime 'supervisor.log') -ErrorAction SilentlyContinue
                    if($previous -and $previous.Length -gt 2097152) { Move-Item -LiteralPath $previous.FullName -Destination ($previous.FullName+'.previous') -Force }
                    & docker info --format '{{.ServerVersion}}' *> $null
                    if($LASTEXITCODE -ne 0) {
                        if(-not $dockerStarted) { Start-Process -FilePath 'C:/Program Files/Docker/Docker/Docker Desktop.exe' -WindowStyle Hidden; $dockerStarted=$true }
                        throw 'Waiting for Docker Desktop'
                    }
                    $running=& docker inspect --format '{{.State.Running}}' gtm-crm-postgres 2>$null
                    if($running -ne 'true') { & docker start gtm-crm-postgres *> $null }
                    if(-not (Test-OwnedProcess $state.api)) {
                        if(Test-Http 'http://localhost:3001/health') { throw 'Port 3001 is occupied by an unmanaged server. Refusing to replace it.' }
                        $state.api=Start-Worker 'api' $bun @('run','src/main.ts') (Join-Path $crm 'apps/api')
                        Write-JsonFile $state $control
                    }
                    if(-not (Test-OwnedProcess $state.app)) {
                        if(Test-Http 'http://localhost:3000/sign-in') { throw 'Port 3000 is occupied by an unmanaged server. Refusing to replace it.' }
                        $state.app=Start-Worker 'app' $node @('node_modules/next/dist/bin/next','dev','--hostname','127.0.0.1','--port','3000') (Join-Path $crm 'apps/app')
                        Write-JsonFile $state $control
                    }
                    $nextStamp=Source-Stamp
                    if($nextStamp -ne $stamp) {
                        Invoke-Sync *> (Join-Path $runtime 'sync.log')
                        $stamp=$nextStamp
                    }
                } catch { ((Get-Date).ToUniversalTime().ToString('o')+' '+$_.Exception.Message) | Add-Content -LiteralPath (Join-Path $runtime 'supervisor.log') }
                Start-Sleep -Seconds 15
            }
        } finally {
            Stop-OwnedTree $state.api
            Stop-OwnedTree $state.app
            $mutex.ReleaseMutex()
            $mutex.Dispose()
        }
    }
}
