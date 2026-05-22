#Requires -Version 5.1
<#
.SYNOPSIS
    Utilitaire de gestion des pipeline schedules GitLab.

.DESCRIPTION
    Permet de lister, créer, modifier, supprimer, activer/désactiver, exécuter et
    surveiller les pipeline schedules d'un projet GitLab, ainsi que de gérer
    leurs variables.

.PARAMETER Action
    Action à exécuter. Si omis, lance le menu interactif.
    Valeurs : list, show, create, update, delete, activate, deactivate, play,
              watch, take-ownership, vars, var-add, var-set, var-del, menu

.PARAMETER ProjectId
    ID du projet GitLab. Par défaut lit $env:GITLAB_PROJECT_ID.

.PARAMETER Token
    Token GitLab (PRIVATE-TOKEN). Par défaut lit $env:GITLAB_TOKEN.

.PARAMETER GitLabUrl
    URL de base de l'instance GitLab. Par défaut https://gitlab.com.

.PARAMETER ScheduleId
    ID du schedule ciblé par l'action.

.PARAMETER DryRun
    N'effectue aucun appel mutant (create/update/delete/play). Affiche ce qui
    serait fait.

.EXAMPLE
    .\Manage-PipelineSchedules.ps1
    Lance le menu interactif.

.EXAMPLE
    .\Manage-PipelineSchedules.ps1 -Action list

.EXAMPLE
    .\Manage-PipelineSchedules.ps1 -Action play -ScheduleId 42 -Watch

.NOTES
    Compatible PowerShell 5.1+ (Windows PowerShell) et PowerShell 7+.
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet('list','show','create','update','delete','activate','deactivate',
                 'play','watch','take-ownership','vars','var-add','var-set','var-del','menu')]
    [string]$Action,

    [string]$ProjectId,
    [string]$Token,
    [string]$GitLabUrl,

    [int]$ScheduleId,
    [int]$PipelineId,

    [string]$Description,
    [string]$Cron,
    [string]$CronTimezone = 'UTC',
    [string]$Ref,
    [string]$VariableKey,
    [string]$VariableValue,
    [ValidateSet('env_var','file')]
    [string]$VariableType = 'env_var',

    [string]$Filter,
    [ValidateSet('all','active','inactive')]
    [string]$Status = 'all',

    [int]$WatchTimeoutSeconds = 1800,
    [int]$WatchIntervalSeconds = 5,

    [switch]$Watch,
    [switch]$DryRun,
    [switch]$NoColor
)

# ============================================================================
# Configuration (modifie ces valeurs si besoin)
# ============================================================================

# Token GitLab (PRIVATE-TOKEN). Laisse vide pour utiliser $env:GITLAB_TOKEN.
$DefaultToken     = "TON_TOKEN"

# ID (ou path encodé) du projet GitLab.
$DefaultProjectId = "316"

# URL de base de l'instance GitLab.
$DefaultGitLabUrl = "https://gitlab.com"

# ============================================================================
# Initialisation
# ============================================================================

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Priorité : paramètre CLI > variable d'environnement > valeur par défaut du script
if ([string]::IsNullOrWhiteSpace($Token))     { $Token     = if ($env:GITLAB_TOKEN)      { $env:GITLAB_TOKEN }      else { $DefaultToken } }
if ([string]::IsNullOrWhiteSpace($ProjectId)) { $ProjectId = if ($env:GITLAB_PROJECT_ID) { $env:GITLAB_PROJECT_ID } else { $DefaultProjectId } }
if ([string]::IsNullOrWhiteSpace($GitLabUrl)) { $GitLabUrl = if ($env:GITLAB_URL)        { $env:GITLAB_URL }        else { $DefaultGitLabUrl } }

if ([string]::IsNullOrWhiteSpace($Token) -or $Token -eq 'TON_TOKEN') {
    throw "Token GitLab manquant. Edite `$DefaultToken dans le script, passe -Token, ou définis `$env:GITLAB_TOKEN."
}
if ([string]::IsNullOrWhiteSpace($ProjectId)) {
    throw "ProjectId manquant. Edite `$DefaultProjectId dans le script, passe -ProjectId, ou définis `$env:GITLAB_PROJECT_ID."
}

$script:BaseUrl     = "$($GitLabUrl.TrimEnd('/'))/api/v4"
$script:ProjectUrl  = "$script:BaseUrl/projects/$([uri]::EscapeDataString($ProjectId))"
$script:SchedUrl    = "$script:ProjectUrl/pipeline_schedules"
$script:HeadersGet  = @{ 'PRIVATE-TOKEN' = $Token }
$script:HeadersPost = @{ 'PRIVATE-TOKEN' = $Token; 'Content-Type' = 'application/x-www-form-urlencoded' }

# ============================================================================
# Helpers
# ============================================================================

function Write-Color {
    param([string]$Text, [string]$Color = 'Gray')
    if ($NoColor) { Write-Host $Text } else { Write-Host $Text -ForegroundColor $Color }
}

function Get-StatusColor {
    param([string]$Status)
    switch ($Status) {
        'success'  { 'Green' }
        'running'  { 'Cyan' }
        'pending'  { 'Yellow' }
        'created'  { 'Yellow' }
        'failed'   { 'Red' }
        'canceled' { 'Yellow' }
        'skipped'  { 'DarkGray' }
        'manual'   { 'Magenta' }
        default    { 'Gray' }
    }
}

function Invoke-GitLab {
    <#
    .SYNOPSIS  Appelle l'API GitLab avec retry exponentiel sur erreurs transitoires.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Uri,
        [ValidateSet('Get','Post','Put','Delete')][string]$Method = 'Get',
        [hashtable]$Headers,
        $Body,
        [int]$MaxRetries = 3
    )

    if (-not $Headers) {
        $Headers = if ($Method -eq 'Get' -or $Method -eq 'Delete') { $script:HeadersGet } else { $script:HeadersPost }
    }

    $attempt = 0
    while ($true) {
        $attempt++
        try {
            $params = @{
                Uri     = $Uri
                Method  = $Method
                Headers = $Headers
            }
            if ($null -ne $Body) { $params.Body = $Body }
            return Invoke-RestMethod @params
        }
        catch {
            $statusCode = $null
            try { $statusCode = [int]$_.Exception.Response.StatusCode } catch {}

            $isTransient = ($statusCode -ge 500) -or ($statusCode -eq 429) -or (-not $statusCode)

            if ($isTransient -and $attempt -lt $MaxRetries) {
                $delay = [Math]::Pow(2, $attempt)
                Write-Verbose "Erreur transitoire ($statusCode), nouvelle tentative dans ${delay}s..."
                Start-Sleep -Seconds $delay
                continue
            }

            $msg = $_.Exception.Message
            try {
                $stream = $_.Exception.Response.GetResponseStream()
                if ($stream) {
                    $reader = New-Object System.IO.StreamReader($stream)
                    $msg += " | $($reader.ReadToEnd())"
                }
            } catch {}

            throw "GitLab API $Method $Uri a échoué (HTTP $statusCode) : $msg"
        }
    }
}

function Get-PagedResults {
    <#
    .SYNOPSIS  Récupère toutes les pages d'un endpoint GitLab paginé.
    #>
    param(
        [Parameter(Mandatory)][string]$Uri,
        [int]$PerPage = 100
    )

    $results = New-Object System.Collections.Generic.List[object]
    $page = 1
    do {
        $sep = if ($Uri -like '*?*') { '&' } else { '?' }
        $url = "$Uri${sep}per_page=$PerPage&page=$page"
        $batch = Invoke-GitLab -Uri $url -Method Get
        if ($null -eq $batch) { break }
        if ($batch -is [System.Collections.IEnumerable] -and -not ($batch -is [string])) {
            foreach ($item in $batch) { $results.Add($item) }
            $size = @($batch).Count
        } else {
            $results.Add($batch)
            $size = 1
        }
        $page++
    } while ($size -eq $PerPage)
    return ,$results.ToArray()
}

function Get-TimeLeft {
    param([string]$NextRunAt)
    if (-not $NextRunAt) { return 'N/A' }
    try {
        $next = [datetime]::Parse($NextRunAt).ToUniversalTime()
        $rem = $next - (Get-Date).ToUniversalTime()
        if ($rem.TotalSeconds -lt 0) { return 'Déjà passé' }
        return ('{0}j {1}h {2}m' -f $rem.Days, $rem.Hours, $rem.Minutes)
    } catch {
        return 'N/A'
    }
}

function ConvertTo-FormEncoded {
    param([hashtable]$Data)
    $pairs = foreach ($k in $Data.Keys) {
        if ($null -eq $Data[$k]) { continue }
        '{0}={1}' -f [uri]::EscapeDataString($k), [uri]::EscapeDataString([string]$Data[$k])
    }
    return ($pairs -join '&')
}

function Confirm-Action {
    param([string]$Message, [switch]$Destructive)
    if ($DryRun) { Write-Color "[DRY-RUN] $Message" 'DarkYellow'; return $false }
    $color = if ($Destructive) { 'Red' } else { 'Yellow' }
    Write-Color $Message $color
    $ans = Read-Host 'Confirmer ? (O/N)'
    return ($ans -match '^[OoYy]')
}

function Test-CronExpression {
    param([string]$Cron)
    if ([string]::IsNullOrWhiteSpace($Cron)) { return $false }
    $parts = $Cron.Trim() -split '\s+'
    return ($parts.Count -eq 5)
}

# ============================================================================
# API : Pipeline Schedules
# ============================================================================

function Get-Schedules {
    [CmdletBinding()]
    param(
        [string]$Filter,
        [ValidateSet('all','active','inactive')][string]$Status = 'all'
    )
    $all = Get-PagedResults -Uri $script:SchedUrl
    if ($Status -eq 'active')   { $all = @($all | Where-Object { $_.active }) }
    if ($Status -eq 'inactive') { $all = @($all | Where-Object { -not $_.active }) }
    if ($Filter) { $all = @($all | Where-Object { $_.description -like "*$Filter*" }) }
    return $all
}

function Get-Schedule {
    param([Parameter(Mandatory)][int]$ScheduleId)
    return Invoke-GitLab -Uri "$script:SchedUrl/$ScheduleId" -Method Get
}

function Get-LastSchedulePipelineStatus {
    param([Parameter(Mandatory)][int]$ScheduleId)
    try {
        $pipelines = Invoke-GitLab -Uri "$script:SchedUrl/$ScheduleId/pipelines" -Method Get
        if ($pipelines -and @($pipelines).Count -gt 0) { return @($pipelines)[0].status }
        return 'Aucun run'
    } catch { return 'Erreur' }
}

function New-Schedule {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)][string]$Description,
        [Parameter(Mandatory)][string]$Ref,
        [Parameter(Mandatory)][string]$Cron,
        [string]$CronTimezone = 'UTC',
        [bool]$Active = $true
    )
    if (-not (Test-CronExpression $Cron)) {
        throw "Expression cron invalide (attendu 5 champs) : '$Cron'"
    }
    $body = ConvertTo-FormEncoded @{
        description   = $Description
        ref           = $Ref
        cron          = $Cron
        cron_timezone = $CronTimezone
        active        = $Active.ToString().ToLower()
    }
    if ($DryRun) { Write-Color "[DRY-RUN] POST $script:SchedUrl body=$body" 'DarkYellow'; return }
    if ($PSCmdlet.ShouldProcess("schedule '$Description'", 'Create')) {
        return Invoke-GitLab -Uri $script:SchedUrl -Method Post -Body $body
    }
}

function Set-Schedule {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)][int]$ScheduleId,
        [string]$Description,
        [string]$Ref,
        [string]$Cron,
        [string]$CronTimezone,
        [Nullable[bool]]$Active
    )
    $fields = @{}
    if ($PSBoundParameters.ContainsKey('Description'))  { $fields.description   = $Description }
    if ($PSBoundParameters.ContainsKey('Ref'))          { $fields.ref           = $Ref }
    if ($PSBoundParameters.ContainsKey('Cron')) {
        if (-not (Test-CronExpression $Cron)) { throw "Cron invalide : '$Cron'" }
        $fields.cron = $Cron
    }
    if ($PSBoundParameters.ContainsKey('CronTimezone')) { $fields.cron_timezone = $CronTimezone }
    if ($PSBoundParameters.ContainsKey('Active') -and $null -ne $Active) {
        $fields.active = ([bool]$Active).ToString().ToLower()
    }
    if ($fields.Count -eq 0) { throw 'Aucun champ à mettre à jour.' }
    $body = ConvertTo-FormEncoded $fields
    if ($DryRun) { Write-Color "[DRY-RUN] PUT $script:SchedUrl/$ScheduleId body=$body" 'DarkYellow'; return }
    if ($PSCmdlet.ShouldProcess("schedule #$ScheduleId", 'Update')) {
        return Invoke-GitLab -Uri "$script:SchedUrl/$ScheduleId" -Method Put -Body $body
    }
}

function Remove-Schedule {
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact='High')]
    param([Parameter(Mandatory)][int]$ScheduleId)
    if ($DryRun) { Write-Color "[DRY-RUN] DELETE $script:SchedUrl/$ScheduleId" 'DarkYellow'; return }
    if ($PSCmdlet.ShouldProcess("schedule #$ScheduleId", 'Delete')) {
        Invoke-GitLab -Uri "$script:SchedUrl/$ScheduleId" -Method Delete | Out-Null
    }
}

function Invoke-SchedulePlay {
    [CmdletBinding(SupportsShouldProcess)]
    param([Parameter(Mandatory)][int]$ScheduleId)
    if ($DryRun) { Write-Color "[DRY-RUN] POST $script:SchedUrl/$ScheduleId/play" 'DarkYellow'; return }
    if ($PSCmdlet.ShouldProcess("schedule #$ScheduleId", 'Play')) {
        return Invoke-GitLab -Uri "$script:SchedUrl/$ScheduleId/play" -Method Post
    }
}

function Invoke-ScheduleTakeOwnership {
    [CmdletBinding(SupportsShouldProcess)]
    param([Parameter(Mandatory)][int]$ScheduleId)
    if ($DryRun) { Write-Color "[DRY-RUN] POST $script:SchedUrl/$ScheduleId/take_ownership" 'DarkYellow'; return }
    if ($PSCmdlet.ShouldProcess("schedule #$ScheduleId", 'Take ownership')) {
        return Invoke-GitLab -Uri "$script:SchedUrl/$ScheduleId/take_ownership" -Method Post
    }
}

# ============================================================================
# API : Variables de Schedule
# ============================================================================

function Get-ScheduleVariables {
    param([Parameter(Mandatory)][int]$ScheduleId)
    $sched = Get-Schedule -ScheduleId $ScheduleId
    if ($sched.PSObject.Properties.Name -contains 'variables') {
        return $sched.variables
    }
    return @()
}

function Add-ScheduleVariable {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)][int]$ScheduleId,
        [Parameter(Mandatory)][string]$Key,
        [Parameter(Mandatory)][string]$Value,
        [ValidateSet('env_var','file')][string]$Type = 'env_var'
    )
    $body = ConvertTo-FormEncoded @{
        key            = $Key
        value          = $Value
        variable_type  = $Type
    }
    if ($DryRun) { Write-Color "[DRY-RUN] POST variables key=$Key" 'DarkYellow'; return }
    if ($PSCmdlet.ShouldProcess("schedule #$ScheduleId var $Key", 'Add')) {
        return Invoke-GitLab -Uri "$script:SchedUrl/$ScheduleId/variables" -Method Post -Body $body
    }
}

function Set-ScheduleVariable {
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory)][int]$ScheduleId,
        [Parameter(Mandatory)][string]$Key,
        [Parameter(Mandatory)][string]$Value,
        [ValidateSet('env_var','file')][string]$Type
    )
    $fields = @{ value = $Value }
    if ($PSBoundParameters.ContainsKey('Type')) { $fields.variable_type = $Type }
    $body = ConvertTo-FormEncoded $fields
    $url = "$script:SchedUrl/$ScheduleId/variables/$([uri]::EscapeDataString($Key))"
    if ($DryRun) { Write-Color "[DRY-RUN] PUT variables key=$Key" 'DarkYellow'; return }
    if ($PSCmdlet.ShouldProcess("schedule #$ScheduleId var $Key", 'Update')) {
        return Invoke-GitLab -Uri $url -Method Put -Body $body
    }
}

function Remove-ScheduleVariable {
    [CmdletBinding(SupportsShouldProcess, ConfirmImpact='Medium')]
    param(
        [Parameter(Mandatory)][int]$ScheduleId,
        [Parameter(Mandatory)][string]$Key
    )
    $url = "$script:SchedUrl/$ScheduleId/variables/$([uri]::EscapeDataString($Key))"
    if ($DryRun) { Write-Color "[DRY-RUN] DELETE variables key=$Key" 'DarkYellow'; return }
    if ($PSCmdlet.ShouldProcess("schedule #$ScheduleId var $Key", 'Delete')) {
        Invoke-GitLab -Uri $url -Method Delete | Out-Null
    }
}

# ============================================================================
# Pipelines : Watch / Cancel / Retry
# ============================================================================

function Watch-Pipeline {
    param(
        [Parameter(Mandatory)][int]$PipelineId,
        [int]$TimeoutSeconds = 1800,
        [int]$IntervalSeconds = 5
    )

    Write-Color "`nSurveillance du pipeline $PipelineId (timeout ${TimeoutSeconds}s)..." 'Cyan'
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastStatus = $null

    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds $IntervalSeconds
        try {
            $p = Invoke-GitLab -Uri "$script:ProjectUrl/pipelines/$PipelineId" -Method Get
            if ($p.status -ne $lastStatus) {
                Write-Color ("[{0}] Statut : {1}" -f (Get-Date -Format 'HH:mm:ss'), $p.status) (Get-StatusColor $p.status)
                $lastStatus = $p.status
            }
            switch ($p.status) {
                'success'  { Write-Color "`nPipeline terminé avec succès." 'Green'; Write-Host "URL : $($p.web_url)"; return $p }
                'failed'   { Write-Color "`nPipeline échoué." 'Red';                Write-Host "URL : $($p.web_url)"; return $p }
                'canceled' { Write-Color "`nPipeline annulé." 'Yellow';             Write-Host "URL : $($p.web_url)"; return $p }
                'skipped'  { Write-Color "`nPipeline skipped." 'Yellow';            Write-Host "URL : $($p.web_url)"; return $p }
            }
        } catch {
            Write-Color "Erreur récupération pipeline : $_" 'Red'
        }
    }
    Write-Color "`nTimeout atteint." 'Yellow'
}

function Stop-Pipeline {
    [CmdletBinding(SupportsShouldProcess)]
    param([Parameter(Mandatory)][int]$PipelineId)
    if ($PSCmdlet.ShouldProcess("pipeline #$PipelineId", 'Cancel')) {
        return Invoke-GitLab -Uri "$script:ProjectUrl/pipelines/$PipelineId/cancel" -Method Post
    }
}

# ============================================================================
# Affichage
# ============================================================================

function Show-SchedulesTable {
    param([object[]]$Schedules)

    if (-not $Schedules -or $Schedules.Count -eq 0) {
        Write-Color 'Aucun schedule.' 'Yellow'
        return
    }

    Write-Color "`n=========== Schedules GitLab (projet $ProjectId) ===========" 'Cyan'

    $rows = foreach ($s in $Schedules) {
        $lastStatus = Get-LastSchedulePipelineStatus -ScheduleId $s.id
        $timeLeft   = if ($s.active) { Get-TimeLeft $s.next_run_at } else { '-' }
        [pscustomobject]@{
            ID          = $s.id
            Active      = if ($s.active) { 'oui' } else { 'non' }
            Description = $s.description
            Ref         = $s.ref
            Cron        = $s.cron
            TZ          = $s.cron_timezone
            LastStatus  = $lastStatus
            NextRun     = $s.next_run_at
            Dans        = $timeLeft
            Owner       = if ($s.owner) { $s.owner.username } else { '-' }
        }
    }
    $rows | Format-Table -AutoSize | Out-Host
}

function Show-ScheduleDetail {
    param([Parameter(Mandatory)][int]$ScheduleId)
    $s = Get-Schedule -ScheduleId $ScheduleId
    Write-Color "`n=========== Schedule #$($s.id) ===========" 'Cyan'
    Write-Host "Description   : $($s.description)"
    Write-Host "Ref           : $($s.ref)"
    Write-Host "Cron          : $($s.cron) ($($s.cron_timezone))"
    Write-Host "Active        : $($s.active)"
    Write-Host "Next run      : $($s.next_run_at)"
    Write-Host "Dans          : $(Get-TimeLeft $s.next_run_at)"
    Write-Host "Created       : $($s.created_at)"
    Write-Host "Updated       : $($s.updated_at)"
    Write-Host "Owner         : $(if ($s.owner) { $s.owner.username } else { '-' })"
    $last = Get-LastSchedulePipelineStatus -ScheduleId $ScheduleId
    Write-Color "Last status   : $last" (Get-StatusColor $last)

    if ($s.PSObject.Properties.Name -contains 'variables' -and $s.variables) {
        Write-Color "`nVariables :" 'Cyan'
        $s.variables | Format-Table key, variable_type, value -AutoSize | Out-Host
    }
}

# ============================================================================
# Menu interactif
# ============================================================================

function Invoke-InteractiveMenu {
    while ($true) {
        Write-Color "`n========= Pipeline Schedules - Menu =========" 'Cyan'
        Write-Host '  1) Lister les schedules'
        Write-Host '  2) Détails d''un schedule'
        Write-Host '  3) Créer un schedule'
        Write-Host '  4) Modifier un schedule'
        Write-Host '  5) Activer / Désactiver'
        Write-Host '  6) Lancer maintenant (play)'
        Write-Host '  7) Supprimer un schedule'
        Write-Host '  8) Take ownership'
        Write-Host '  9) Variables (list/add/set/del)'
        Write-Host ' 10) Surveiller un pipeline'
        Write-Host '  Q) Quitter'

        $c = Read-Host 'Choix'
        try {
            switch ($c) {
                '1' { Show-SchedulesTable (Get-Schedules) }
                '2' {
                    $id = [int](Read-Host 'ID du schedule')
                    Show-ScheduleDetail -ScheduleId $id
                }
                '3' {
                    $d = Read-Host 'Description'
                    $r = Read-Host 'Ref (branche)'
                    $cr = Read-Host 'Cron (ex: "0 9 * * *")'
                    $tz = Read-Host 'Timezone (def: UTC)'
                    if ([string]::IsNullOrWhiteSpace($tz)) { $tz = 'UTC' }
                    $res = New-Schedule -Description $d -Ref $r -Cron $cr -CronTimezone $tz
                    if ($res) { Write-Color "Créé : #$($res.id)" 'Green' }
                }
                '4' {
                    $id = [int](Read-Host 'ID du schedule')
                    $params = @{ ScheduleId = $id }
                    $v = Read-Host 'Nouvelle description (vide = inchangé)'
                    if ($v) { $params.Description = $v }
                    $v = Read-Host 'Nouvelle ref (vide = inchangé)'
                    if ($v) { $params.Ref = $v }
                    $v = Read-Host 'Nouveau cron (vide = inchangé)'
                    if ($v) { $params.Cron = $v }
                    $v = Read-Host 'Nouvelle timezone (vide = inchangé)'
                    if ($v) { $params.CronTimezone = $v }
                    $res = Set-Schedule @params
                    if ($res) { Show-ScheduleDetail -ScheduleId $id }
                }
                '5' {
                    $id = [int](Read-Host 'ID du schedule')
                    $a = Read-Host 'A = activer, D = désactiver'
                    $active = if ($a -match '^[Aa]') { $true } elseif ($a -match '^[Dd]') { $false } else { throw 'Choix invalide' }
                    $res = Set-Schedule -ScheduleId $id -Active $active
                    if ($res) {
                        Write-Color "Schedule #$id : active=$($res.active)" 'Green'
                        if ($res.active) { Show-ScheduleDetail -ScheduleId $id }
                    }
                }
                '6' {
                    $id = [int](Read-Host 'ID du schedule')
                    $res = Invoke-SchedulePlay -ScheduleId $id
                    Write-Color 'Schedule déclenché.' 'Green'
                    $pid_ = if ($res -and $res.PSObject.Properties.Name -contains 'pipeline' -and $res.pipeline) {
                                $res.pipeline.id
                            } elseif ($res -and $res.PSObject.Properties.Name -contains 'id') {
                                $res.id
                            } else { $null }
                    if ($pid_) {
                        Write-Host "Pipeline ID : $pid_"
                        $w = Read-Host 'Surveiller ? (O/N)'
                        if ($w -match '^[OoYy]') { Watch-Pipeline -PipelineId $pid_ -TimeoutSeconds $WatchTimeoutSeconds -IntervalSeconds $WatchIntervalSeconds }
                    } else {
                        Write-Color 'Pipeline ID non récupéré (le play peut être asynchrone).' 'Yellow'
                    }
                }
                '7' {
                    $id = [int](Read-Host 'ID du schedule à supprimer')
                    if (Confirm-Action -Message "Supprimer définitivement le schedule #$id ?" -Destructive) {
                        Remove-Schedule -ScheduleId $id -Confirm:$false
                        Write-Color 'Supprimé.' 'Green'
                    }
                }
                '8' {
                    $id = [int](Read-Host 'ID du schedule')
                    Invoke-ScheduleTakeOwnership -ScheduleId $id | Out-Null
                    Write-Color 'Ownership pris.' 'Green'
                }
                '9' {
                    $id = [int](Read-Host 'ID du schedule')
                    Write-Host 'a) lister  b) ajouter  c) modifier  d) supprimer'
                    $sub = Read-Host 'Choix'
                    switch ($sub) {
                        'a' { (Get-ScheduleVariables -ScheduleId $id) | Format-Table key, variable_type, value -AutoSize | Out-Host }
                        'b' {
                            $k = Read-Host 'Clé'; $v = Read-Host 'Valeur'
                            Add-ScheduleVariable -ScheduleId $id -Key $k -Value $v | Out-Null
                            Write-Color 'Variable ajoutée.' 'Green'
                        }
                        'c' {
                            $k = Read-Host 'Clé'; $v = Read-Host 'Nouvelle valeur'
                            Set-ScheduleVariable -ScheduleId $id -Key $k -Value $v | Out-Null
                            Write-Color 'Variable mise à jour.' 'Green'
                        }
                        'd' {
                            $k = Read-Host 'Clé à supprimer'
                            if (Confirm-Action -Message "Supprimer la variable '$k' ?" -Destructive) {
                                Remove-ScheduleVariable -ScheduleId $id -Key $k -Confirm:$false
                                Write-Color 'Variable supprimée.' 'Green'
                            }
                        }
                    }
                }
                '10' {
                    $pid_ = [int](Read-Host 'Pipeline ID')
                    Watch-Pipeline -PipelineId $pid_ -TimeoutSeconds $WatchTimeoutSeconds -IntervalSeconds $WatchIntervalSeconds | Out-Null
                }
                'q' { return }
                'Q' { return }
                default { Write-Color 'Choix invalide.' 'Red' }
            }
        } catch {
            Write-Color "Erreur : $_" 'Red'
        }
    }
}

# ============================================================================
# Dispatcher CLI
# ============================================================================

function Invoke-CliAction {
    switch ($Action) {
        'list' { Show-SchedulesTable (Get-Schedules -Filter $Filter -Status $Status) }
        'show' {
            if (-not $ScheduleId) { throw '-ScheduleId requis.' }
            Show-ScheduleDetail -ScheduleId $ScheduleId
        }
        'create' {
            if (-not $Description -or -not $Ref -or -not $Cron) { throw '-Description, -Ref et -Cron requis.' }
            $res = New-Schedule -Description $Description -Ref $Ref -Cron $Cron -CronTimezone $CronTimezone
            if ($res) { Write-Color "Créé : #$($res.id)" 'Green' }
        }
        'update' {
            if (-not $ScheduleId) { throw '-ScheduleId requis.' }
            $p = @{ ScheduleId = $ScheduleId }
            if ($PSBoundParameters.ContainsKey('Description'))  { $p.Description  = $Description }
            if ($PSBoundParameters.ContainsKey('Ref'))          { $p.Ref          = $Ref }
            if ($PSBoundParameters.ContainsKey('Cron'))         { $p.Cron         = $Cron }
            if ($PSBoundParameters.ContainsKey('CronTimezone')) { $p.CronTimezone = $CronTimezone }
            $res = Set-Schedule @p
            if ($res) { Show-ScheduleDetail -ScheduleId $ScheduleId }
        }
        'delete' {
            if (-not $ScheduleId) { throw '-ScheduleId requis.' }
            Remove-Schedule -ScheduleId $ScheduleId
            Write-Color "Schedule #$ScheduleId supprimé." 'Green'
        }
        'activate'   {
            if (-not $ScheduleId) { throw '-ScheduleId requis.' }
            Set-Schedule -ScheduleId $ScheduleId -Active $true | Out-Null
            Write-Color "Schedule #$ScheduleId activé." 'Green'
        }
        'deactivate' {
            if (-not $ScheduleId) { throw '-ScheduleId requis.' }
            Set-Schedule -ScheduleId $ScheduleId -Active $false | Out-Null
            Write-Color "Schedule #$ScheduleId désactivé." 'Green'
        }
        'play' {
            if (-not $ScheduleId) { throw '-ScheduleId requis.' }
            $res = Invoke-SchedulePlay -ScheduleId $ScheduleId
            $pid_ = if ($res -and $res.PSObject.Properties.Name -contains 'pipeline' -and $res.pipeline) {
                        $res.pipeline.id
                    } elseif ($res -and $res.PSObject.Properties.Name -contains 'id') {
                        $res.id
                    } else { $null }
            if ($pid_) { Write-Color "Pipeline lancé : #$pid_" 'Green' }
            if ($Watch -and $pid_) {
                Watch-Pipeline -PipelineId $pid_ -TimeoutSeconds $WatchTimeoutSeconds -IntervalSeconds $WatchIntervalSeconds | Out-Null
            }
        }
        'watch' {
            if (-not $PipelineId) { throw '-PipelineId requis.' }
            Watch-Pipeline -PipelineId $PipelineId -TimeoutSeconds $WatchTimeoutSeconds -IntervalSeconds $WatchIntervalSeconds | Out-Null
        }
        'take-ownership' {
            if (-not $ScheduleId) { throw '-ScheduleId requis.' }
            Invoke-ScheduleTakeOwnership -ScheduleId $ScheduleId | Out-Null
            Write-Color 'Ownership pris.' 'Green'
        }
        'vars' {
            if (-not $ScheduleId) { throw '-ScheduleId requis.' }
            (Get-ScheduleVariables -ScheduleId $ScheduleId) |
                Format-Table key, variable_type, value -AutoSize | Out-Host
        }
        'var-add' {
            if (-not $ScheduleId -or -not $VariableKey -or -not $VariableValue) {
                throw '-ScheduleId, -VariableKey, -VariableValue requis.'
            }
            Add-ScheduleVariable -ScheduleId $ScheduleId -Key $VariableKey -Value $VariableValue -Type $VariableType | Out-Null
            Write-Color "Variable '$VariableKey' ajoutée." 'Green'
        }
        'var-set' {
            if (-not $ScheduleId -or -not $VariableKey -or -not $VariableValue) {
                throw '-ScheduleId, -VariableKey, -VariableValue requis.'
            }
            Set-ScheduleVariable -ScheduleId $ScheduleId -Key $VariableKey -Value $VariableValue -Type $VariableType | Out-Null
            Write-Color "Variable '$VariableKey' mise à jour." 'Green'
        }
        'var-del' {
            if (-not $ScheduleId -or -not $VariableKey) { throw '-ScheduleId et -VariableKey requis.' }
            Remove-ScheduleVariable -ScheduleId $ScheduleId -Key $VariableKey
            Write-Color "Variable '$VariableKey' supprimée." 'Green'
        }
        'menu'  { Invoke-InteractiveMenu }
        default { Invoke-InteractiveMenu }
    }
}

# ============================================================================
# Entrée principale
# ============================================================================

try {
    if ([string]::IsNullOrEmpty($Action)) {
        Invoke-InteractiveMenu
    } else {
        Invoke-CliAction
    }
} catch {
    Write-Color "ERREUR : $_" 'Red'
    exit 1
}
