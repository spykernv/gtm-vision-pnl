param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    & python -X utf8 scripts/gtm.py @Arguments
    if ($LASTEXITCODE -ne 0) { throw "GTM operation failed: $LASTEXITCODE" }
} finally { Pop-Location }
