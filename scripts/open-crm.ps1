$ErrorActionPreference = 'Stop'
$engine = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $engine 'local/crm-runtime'
$url = 'http://localhost:3000'

function Test-Ready([string]$address) {
    try {
        return (Invoke-WebRequest -Uri $address -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200
    } catch { return $false }
}

try {
    & (Join-Path $PSScriptRoot 'crm.ps1') -Action start | Out-Null
    $deadline = [DateTime]::UtcNow.AddMinutes(3)
    $ready = $false
    do {
        $ready = (Test-Ready 'http://localhost:3001/health') -and (Test-Ready "$url/sign-in")
        if ($ready) { break }
        Start-Sleep -Seconds 2
    } while ([DateTime]::UtcNow -lt $deadline)

    if (-not $ready) {
        throw 'Le CRM ne répond pas encore après trois minutes. Son démarrage continue en arrière-plan. Réessayez dans un instant.'
    }

    # The browser is intentionally visible: this is the user's desktop launcher.
    Start-Process -FilePath $url
    [pscustomobject]@{opened_at=[DateTime]::UtcNow.ToString('o');url=$url;ready=$true} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime 'last-open.json') -Encoding utf8
} catch {
    $message = "Impossible d'ouvrir Vision P&L CRM.`n`n$($_.Exception.Message)`n`nLes journaux sont dans :`n$runtime"
    (New-Object -ComObject WScript.Shell).Popup($message, 0, 'Vision P&L CRM', 16) | Out-Null
    exit 1
}
