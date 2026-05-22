# GitLab Pipeline Schedules - Utilitaire PowerShell

Utilitaire complet pour gérer les **pipeline schedules** d'un projet GitLab :
lister, créer, modifier, supprimer, activer/désactiver, lancer, surveiller,
prendre l'ownership et gérer les **variables** des schedules.

Compatible **PowerShell 5.1+** (Windows PowerShell) et **PowerShell 7+** (Linux/macOS/Windows).

## Installation

Aucune dépendance. Récupère simplement le fichier `Manage-PipelineSchedules.ps1`.

## Configuration

Ouvre `Manage-PipelineSchedules.ps1` et édite la section *Configuration* en haut :

```powershell
$DefaultToken     = "TON_TOKEN"
$DefaultProjectId = "316"
$DefaultGitLabUrl = "https://gitlab.com"
```

Tu peux aussi surcharger via variables d'environnement (`GITLAB_TOKEN`,
`GITLAB_PROJECT_ID`, `GITLAB_URL`) ou via paramètres CLI (`-Token`,
`-ProjectId`, `-GitLabUrl`). Ordre de priorité : **CLI > env var > script**.

## Utilisation

### Mode interactif (menu)

```powershell
.\Manage-PipelineSchedules.ps1
```

Menu avec : lister, détailler, créer, modifier, activer/désactiver,
play, supprimer, take ownership, gérer les variables, surveiller un pipeline.

### Mode CLI

| Action            | Exemple                                                                       |
| ----------------- | ----------------------------------------------------------------------------- |
| Lister            | `.\Manage-PipelineSchedules.ps1 -Action list`                                 |
| Filtrer           | `.\Manage-PipelineSchedules.ps1 -Action list -Status active -Filter "nightly"`|
| Détails           | `.\Manage-PipelineSchedules.ps1 -Action show -ScheduleId 42`                  |
| Créer             | `.\Manage-PipelineSchedules.ps1 -Action create -Description "Nightly" -Ref main -Cron "0 2 * * *"` |
| Modifier          | `.\Manage-PipelineSchedules.ps1 -Action update -ScheduleId 42 -Cron "30 3 * * *"` |
| Activer           | `.\Manage-PipelineSchedules.ps1 -Action activate -ScheduleId 42`              |
| Désactiver        | `.\Manage-PipelineSchedules.ps1 -Action deactivate -ScheduleId 42`            |
| Lancer maintenant | `.\Manage-PipelineSchedules.ps1 -Action play -ScheduleId 42 -Watch`           |
| Supprimer         | `.\Manage-PipelineSchedules.ps1 -Action delete -ScheduleId 42`                |
| Take ownership    | `.\Manage-PipelineSchedules.ps1 -Action take-ownership -ScheduleId 42`        |
| Surveiller        | `.\Manage-PipelineSchedules.ps1 -Action watch -PipelineId 12345`              |
| Lister variables  | `.\Manage-PipelineSchedules.ps1 -Action vars -ScheduleId 42`                  |
| Ajouter variable  | `.\Manage-PipelineSchedules.ps1 -Action var-add -ScheduleId 42 -VariableKey FOO -VariableValue bar` |
| Modifier variable | `.\Manage-PipelineSchedules.ps1 -Action var-set -ScheduleId 42 -VariableKey FOO -VariableValue baz` |
| Supprimer var     | `.\Manage-PipelineSchedules.ps1 -Action var-del -ScheduleId 42 -VariableKey FOO` |

### Options utiles

- `-DryRun` : affiche ce qui serait fait sans appeler l'API mutante.
- `-WatchTimeoutSeconds 3600` : timeout du watch (défaut 1800s).
- `-WatchIntervalSeconds 10` : période de polling du watch (défaut 5s).
- `-NoColor` : sortie sans couleurs (utile pour CI).
- `-Verbose` : trace des retries, des appels HTTP, etc.

## Améliorations vs script initial

- CRUD complet (create / update / delete) en plus de l'activate/play
- Gestion des **variables** de schedule (list / add / set / del)
- **Take ownership** d'un schedule
- **Pagination** automatique
- **Retry** exponentiel sur erreurs 5xx / 429 / réseau
- Watch avec **timeout** et changement de couleur selon le statut
- **DryRun**, validation cron, validation des paramètres
- Mode **CLI scriptable** (CI/CD) en plus du menu interactif
- Affichage en tableau avec `Format-Table`
- Confirmation pour opérations destructives (`-Confirm`, `ShouldProcess`)
- Compatible PowerShell 5.1 et 7+

## Aide intégrée

```powershell
Get-Help .\Manage-PipelineSchedules.ps1 -Detailed
```
