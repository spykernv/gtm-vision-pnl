param(
    [Parameter(Mandatory=$true)][string]$PlanFile,
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$engineRoot = Split-Path -Parent $PSScriptRoot
$planPath = (Resolve-Path -LiteralPath $PlanFile).Path
$localRoot = [IO.Path]::GetFullPath((Join-Path $engineRoot 'local')) + [IO.Path]::DirectorySeparatorChar
if (-not $planPath.StartsWith($localRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'Le plan doit rester dans local/.' }
$outputDir = Split-Path -Parent $planPath
$plan = Get-Content -Raw -LiteralPath $planPath -Encoding UTF8 | ConvertFrom-Json
$journalPath = Join-Path $engineRoot 'local/GTM_Design_Partners_Etat.json'
$journal = Get-Content -Raw -LiteralPath $journalPath -Encoding UTF8 | ConvertFrom-Json
$hash = (Get-FileHash -LiteralPath $journalPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($hash -ne $plan.journal_sha256) { throw 'Le journal a changé : requalifier le plan avant projection.' }
if ($plan.schema_version -ne 1) { throw 'Version de plan inconnue.' }
if (@($plan.entries | Group-Object company_id | Where-Object Count -ne 1).Count) { throw 'Entreprise répétée dans le plan.' }
foreach ($entry in $plan.entries) {
    $record = @($journal.records | Where-Object { $_.Rang -eq $entry.rank -and $_.Entreprise -eq $entry.company })
    if ($record.Count -ne 1 -or $entry.rank -lt 6 -or $entry.rank -gt 50) { throw 'Prospect hors périmètre.' }
    $excluded = @($journal.sent | Where-Object { $_.company -eq $entry.company -and $_.conversation_state -in @('STOPPED','BOUNCED','HANDOFF','BOOKED') })
    if ($excluded.Count) { throw "Prospect suspendu : $($entry.company)" }
    if ($entry.activity_type -notin @('TASK','NOTE')) { throw 'Type d''activité interdit.' }
    if (-not $entry.body.EndsWith("Référence : $($entry.marker)")) { throw 'Référence de déduplication absente.' }
    if ($entry.activity_type -eq 'TASK') {
        if ($entry.status -eq 'PUBLIC_BUSINESS_PHONE') {
            if ($entry.phone -notmatch '^\+(33|32|41)\d{8,9}$' -or $entry.source_url -notmatch '^https://') { throw 'Numéro ou preuve invalide.' }
        } elseif ($entry.status -eq 'PHONE_TO_ENRICH') {
            if ($entry.phone -or -not $entry.reason -or $entry.marker -notmatch '^CC-ENRICH-') { throw 'Tâche de recherche invalide.' }
        } else { throw 'Statut de tâche inconnu.' }
    }
}
if (-not $Apply) {
    [pscustomobject]@{ mode='preview'; leads=@($plan.entries).Count; tasks=@($plan.entries | Where-Object activity_type -eq TASK).Count; notes=@($plan.entries | Where-Object activity_type -eq NOTE).Count } | ConvertTo-Json
    exit 0
}

function Save-Json($Value, [string]$Destination) {
    $temporary = "$Destination.tmp"
    [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 45), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $Destination -Force
}

$receiptPath = Join-Path $outputDir 'crm-receipts.json'
$receipts = @{}
if (Test-Path -LiteralPath $receiptPath) {
    $previous = Get-Content -Raw -LiteralPath $receiptPath -Encoding UTF8 | ConvertFrom-Json
    foreach ($receipt in $previous.entries) { $receipts[[string]$receipt.rank] = $receipt }
}
function Save-Receipts {
    Save-Json ([ordered]@{ checked_at=[DateTimeOffset]::UtcNow.ToString('o'); entries=@($receipts.Values | Sort-Object rank) }) $receiptPath
}

$credential = Import-Clixml -LiteralPath (Join-Path $engineRoot 'local/crm-runtime/credential.xml')
$apiSecret = [System.Net.NetworkCredential]::new('', $credential.Secret).Password
$lock = $null
try {
    $lock = [IO.File]::Open((Join-Path $outputDir 'projection.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    function Request-Crm([string]$Method, [string]$Path, $Body=$null) {
        if ($Path -notmatch '^/rest/(companies|contacts|activities)(/|\?|$)') { throw 'Route hors périmètre.' }
        $parameters = @{ Uri="http://127.0.0.1:3001$Path"; Method=$Method; Headers=@{'x-api-key'=$apiSecret}; TimeoutSec=30 }
        if ($null -ne $Body) {
            $parameters.ContentType = 'application/json'
            $parameters.Body = [Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Depth 30 -Compress))
        }
        Invoke-RestMethod @parameters
    }
    function Read-Timeline([string]$CompanyId) {
        $entries = @()
        $cursor = $null
        do {
            $path = "/rest/activities?companyId=$CompanyId&filter=all&limit=100"
            if ($cursor) { $path += '&cursor=' + [uri]::EscapeDataString($cursor) }
            $page = Request-Crm GET $path
            $entries += @($page.entries)
            $cursor = $page.nextCursor
        } while ($cursor)
        return $entries
    }
    foreach ($entry in $plan.entries) {
        $key = [string]$entry.rank
        if (-not $receipts.ContainsKey($key)) {
            $receipts[$key] = [pscustomobject]@{ rank=$entry.rank; company_id=$entry.company_id; company=$entry.company; contact_id=$null; activity_id=$null; pending=$null; verified_at=$null }
        }
        $receipt = $receipts[$key]
        $company = Request-Crm GET "/rest/companies/$($entry.company_id)"
        if ($company.name -ne $entry.company -or $company.archivedAt) { throw 'La fiche entreprise a changé.' }
        $backupPath = Join-Path $outputDir "before-company-$key.json"
        if (-not (Test-Path -LiteralPath $backupPath)) { Save-Json $company $backupPath }
        if ($entry.activity_type -eq 'TASK' -and $entry.status -eq 'PUBLIC_BUSINESS_PHONE') {
            if ($company.phone -and $company.phone -ne $entry.phone) { throw "Numéro existant différent : $($entry.company). Ne pas écraser." }
            if ($company.phone -ne $entry.phone) {
                $receipt.pending = 'company_phone'
                Save-Receipts
                $null = Request-Crm PATCH "/rest/companies/$($entry.company_id)" @{data=@{phone=$entry.phone}}
                $receipt.pending = $null
                Save-Receipts
            }
            $contacts = @()
            $pageNumber = 1
            do {
                $page = Request-Crm POST '/rest/contacts/search' @{page=$pageNumber;pageSize=100;company=@($entry.company_id)}
                $contacts += @($page.rows)
                $pageNumber++
            } while ($contacts.Count -lt $page.total)
            $matches = @($contacts | Where-Object { $_.firstName -eq $entry.contact_first_name -and $_.lastName -eq $entry.contact_last_name })
            if ($matches.Count -gt 1) { throw 'Plusieurs accueils identiques : réconciliation nécessaire.' }
            if ($matches.Count -eq 1) {
                $contact = Request-Crm GET "/rest/contacts/$($matches[0].id)"
                if ($contact.phone -ne $entry.phone) { throw 'Coordonnée du contact déjà existant différente.' }
                $receipt.contact_id = $contact.id
                if ($receipt.pending -eq 'contact_create') { $receipt.pending = $null }
            } else {
                if ($receipt.contact_id -or $receipt.pending -eq 'contact_create') { throw 'Création de contact antérieure incertaine : ne pas recommencer automatiquement.' }
                $receipt.pending = 'contact_create'
                Save-Receipts
                $contact = Request-Crm POST '/rest/contacts' @{ firstName=$entry.contact_first_name;lastName=$entry.contact_last_name;phone=$entry.phone;title=$entry.line_kind;companyId=$entry.company_id;ownerId=$entry.owner_id }
                $receipt.contact_id = $contact.id
                $receipt.pending = $null
                Save-Receipts
            }
        }
        $timeline = @(Read-Timeline $entry.company_id)
        $matches = @($timeline | Where-Object { $_.type -eq $entry.activity_type -and $_.body -and $_.body.EndsWith("Référence : $($entry.marker)") })
        if ($matches.Count -gt 1) { throw 'Activité en double : réconciliation nécessaire.' }
        if ($matches.Count -eq 1) {
            if ($matches[0].body -ne $entry.body -or $matches[0].subject -ne $entry.subject) { throw 'La tâche a été modifiée : conserver son contenu et réconcilier.' }
            $receipt.activity_id = $matches[0].id
            $receipt.pending = $null
        } else {
            if ($receipt.activity_id -or $receipt.pending -eq 'activity_create') { throw 'Création d''activité antérieure incertaine : ne pas recommencer automatiquement.' }
            $payload = @{ type=$entry.activity_type;subject=$entry.subject;body=$entry.body;companyId=$entry.company_id }
            if ($receipt.contact_id) { $payload.contactId = $receipt.contact_id }
            $receipt.pending = 'activity_create'
            Save-Receipts
            $activity = Request-Crm POST '/rest/activities' $payload
            $receipt.activity_id = $activity.id
            $receipt.pending = $null
            Save-Receipts
        }
        $timeline = @(Read-Timeline $entry.company_id)
        $check = @($timeline | Where-Object { $_.id -eq $receipt.activity_id -and $_.body -eq $entry.body -and $_.subject -eq $entry.subject })
        if ($check.Count -ne 1) { throw 'La relecture de l''activité a échoué.' }
        if ($entry.activity_type -eq 'TASK' -and $entry.status -eq 'PUBLIC_BUSINESS_PHONE') {
            $company = Request-Crm GET "/rest/companies/$($entry.company_id)"
            $contact = Request-Crm GET "/rest/contacts/$($receipt.contact_id)"
            if ($company.phone -ne $entry.phone -or $contact.phone -ne $entry.phone) { throw 'La relecture du numéro a échoué.' }
        }
        $receipt.verified_at = [DateTimeOffset]::UtcNow.ToString('o')
        Save-Receipts
        [pscustomobject]@{rank=$entry.rank;company=$entry.company;type=$entry.activity_type;verified=$true} | ConvertTo-Json -Compress
    }
    $tasks = Request-Crm GET '/rest/activities/my-tasks?window=all&limit=100'
    Save-Json $tasks (Join-Path $outputDir 'crm-tasks-after.json')
    [pscustomobject]@{verified_leads=$receipts.Count;open_tasks=$tasks.Count;receipt=$receiptPath} | ConvertTo-Json -Compress
} finally {
    if ($lock) { $lock.Dispose() }
    $apiSecret = $null
    $credential = $null
}
