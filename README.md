param (
    [Parameter(Mandatory = $true)]
    [string]$OutputXml
)

# Message permettant d'identifier une prise de PTT.
# Insensible aux majuscules/minuscules et accepte du texte
# supplémentaire entre PTT et pressed.
$PttRegex = '(?i)\bPTT\b[\s\S]*?\bpressed\b'

# Compteurs
$counts = [ordered]@{
    driver1 = 0
    driver2 = 0
    driver3 = 0
    driver4 = 0
    driver5 = 0
    driver6 = 0
    UNKNOWN = 0
}

$total = 0

# Stack des owners des keywords actuellement parcourus
$kwOwners = [System.Collections.Generic.List[string]]::new()

# Etat de lecture d'un <msg>
$inMsg = $false
$msgText = [System.Text.StringBuilder]::new()
$msgDriver = "UNKNOWN"


function Get-CurrentDriver {

    param (
        [System.Collections.Generic.List[string]]$Owners
    )

    # On part du keyword le plus proche du message
    # et on remonte jusqu'à trouver driver1 ... driver6
    for ($i = $Owners.Count - 1; $i -ge 0; $i--) {

        $owner = $Owners[$i]

        if ($owner -match '(?i)^driver\s*([1-6])$') {
            return "driver$($Matches[1])"
        }
    }

    return "UNKNOWN"
}


# Vérification du fichier
if (-not (Test-Path $OutputXml)) {
    Write-Host "Fichier introuvable : $OutputXml"
    exit 1
}


$resolvedPath = (Resolve-Path $OutputXml).Path

Write-Host ""
Write-Host "Analyse de : $resolvedPath"
Write-Host ""


$settings = [System.Xml.XmlReaderSettings]::new()
$settings.IgnoreWhitespace = $false
$settings.DtdProcessing = [System.Xml.DtdProcessing]::Ignore

$reader = $null

try {

    $reader = [System.Xml.XmlReader]::Create(
        $resolvedPath,
        $settings
    )

    while ($reader.Read()) {

        # =====================================================
        # ELEMENT OUVRANT
        # =====================================================

        if ($reader.NodeType -eq [System.Xml.XmlNodeType]::Element) {

            # Entrée dans un keyword Robot Framework
            if ($reader.Name -eq "kw") {

                $owner = $reader.GetAttribute("owner")

                if ($null -eq $owner) {
                    $owner = ""
                }

                $kwOwners.Add($owner)

                # Cas très rare : <kw ... />
                if ($reader.IsEmptyElement) {
                    $kwOwners.RemoveAt($kwOwners.Count - 1)
                }
            }

            # Entrée dans un message
            elseif ($reader.Name -eq "msg") {

                $inMsg = $true

                $msgText.Clear() | Out-Null

                # On mémorise le driver actif au moment du message
                $msgDriver = Get-CurrentDriver -Owners $kwOwners
            }
        }


        # =====================================================
        # CONTENU DU MESSAGE
        # =====================================================

        elseif (
            $inMsg -and (
                $reader.NodeType -eq [System.Xml.XmlNodeType]::Text -or
                $reader.NodeType -eq [System.Xml.XmlNodeType]::CDATA -or
                $reader.NodeType -eq [System.Xml.XmlNodeType]::SignificantWhitespace
            )
        ) {

            $msgText.Append($reader.Value) | Out-Null
        }


        # =====================================================
        # ELEMENT FERMANT
        # =====================================================

        elseif ($reader.NodeType -eq [System.Xml.XmlNodeType]::EndElement) {

            # Fin d'un message
            if ($reader.Name -eq "msg" -and $inMsg) {

                $text = $msgText.ToString()

                # Exemple :
                # PTT pressed (long hold started)
                if ($text -match $PttRegex) {

                    $total++

                    if ($counts.Contains($msgDriver)) {
                        $counts[$msgDriver]++
                    }
                    else {
                        $counts["UNKNOWN"]++
                    }
                }

                $inMsg = $false
                $msgText.Clear() | Out-Null
                $msgDriver = "UNKNOWN"
            }

            # Sortie d'un keyword
            elseif ($reader.Name -eq "kw") {

                if ($kwOwners.Count -gt 0) {
                    $kwOwners.RemoveAt($kwOwners.Count - 1)
                }
            }
        }
    }
}
catch {

    Write-Host ""
    Write-Host "Erreur pendant l'analyse du XML :"
    Write-Host $_.Exception.Message

    exit 1
}
finally {

    if ($null -ne $reader) {
        $reader.Close()
    }
}


# ============================================================
# RESULTAT
# ============================================================

Write-Host ""
Write-Host "========================================="
Write-Host "        NOMBRE DE PTT PRIS"
Write-Host "========================================="
Write-Host ""

$result = foreach ($i in 1..6) {

    $driver = "driver$i"

    [PSCustomObject]@{
        Driver = $driver
        PTT    = $counts[$driver]
    }
}

$result | Format-Table -AutoSize

Write-Host "-----------------------------------------"
Write-Host "TOTAL PTT : $total"

if ($counts["UNKNOWN"] -gt 0) {
    Write-Host "PTT sans driver identifie : $($counts["UNKNOWN"])"
}

Write-Host ""