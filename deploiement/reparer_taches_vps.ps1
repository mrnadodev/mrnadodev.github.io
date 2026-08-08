# ╔══════════════════════════════════════════════════════════════════════╗
# ║  NADOEDGE · Réparation des tâches planifiées du VPS                    ║
# ║                                                                       ║
# ║  À lancer UNE FOIS, en PowerShell administrateur sur le serveur.      ║
# ║  Relançable sans risque : chaque tâche est remplacée, pas dupliquée.  ║
# ║                                                                       ║
# ║  Corrige trois défauts constatés le 8 août 2026, quand le scanner     ║
# ║  est resté mort huit heures sans que rien ne le signale.              ║
# ║                                                                       ║
# ║  1. AUCUN JOURNAL. La tâche lançait python sans rediriger sa sortie.  ║
# ║     Le collecteur est mort avec le code 255 sans laisser une ligne.   ║
# ║                                                                       ║
# ║  2. AUCUNE RELANCE RÉELLE. -RestartCount ne s'applique que si la      ║
# ║     tâche ÉCHOUE À DÉMARRER. Un processus qui démarre puis se termine ║
# ║     est vu comme « terminé », jamais comme « échoué » : aucune        ║
# ║     relance n'est déclenchée. Le seul déclencheur étant AtStartup, le ║
# ║     scanner restait mort jusqu'au prochain redémarrage de la machine. ║
# ║     On ajoute une répétition toutes les 5 minutes : Windows l'ignore  ║
# ║     quand la tâche tourne déjà (IgnoreNew), et la relance sinon.      ║
# ║                                                                       ║
# ║  3. AUCUNE MESURE. La mémoire validée est passée de 2,5 à 53,4 Go     ║
# ║     sans qu'on puisse dire ni quand ni à cause de quoi. La sonde      ║
# ║     enregistre la courbe.                                             ║
# ╚══════════════════════════════════════════════════════════════════════╝

$ErrorActionPreference = "Stop"
$Dossier = "C:\nadoedge"
$Logs    = Join-Path $Dossier "logs"

if (-not (Test-Path $Dossier)) { throw "Dossier introuvable : $Dossier" }
New-Item -ItemType Directory -Force $Logs | Out-Null

$python = (Get-Command python).Source
Write-Host "python : $python" -ForegroundColor DarkGray

# Réglages communs. ExecutionTimeLimit à zéro : le collecteur tourne sans fin,
# Windows ne doit jamais décider qu'il a « trop duré ».
$reglages = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

function Poser-Tache {
    param($Nom, $Commande, $Description, [switch]$Actif)

    if (Get-ScheduledTask -TaskName $Nom -ErrorAction SilentlyContinue) {
        # Arrêter avant de supprimer : sinon le processus en cours survit à la
        # tâche qui le pilotait, et continue de tourner sans que rien ne le
        # surveille — un Chromium de plus dans une machine déjà à court de
        # mémoire.
        Stop-ScheduledTask -TaskName $Nom -ErrorAction SilentlyContinue
        Start-Sleep 2
        Unregister-ScheduledTask -TaskName $Nom -Confirm:$false
    }

    # cmd.exe sert uniquement de porte-redirection : le Planificateur de
    # tâches ne sait pas rediriger une sortie par lui-même.
    $action = New-ScheduledTaskAction -Execute "cmd.exe" `
        -Argument "/c $Commande" -WorkingDirectory $Dossier

    $auDemarrage = New-ScheduledTaskTrigger -AtStartup
    $repetition  = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
        -RepetitionInterval (New-TimeSpan -Minutes 5) `
        -RepetitionDuration (New-TimeSpan -Days 3650)

    Register-ScheduledTask -TaskName $Nom `
        -Action $action -Trigger @($auDemarrage, $repetition) -Settings $reglages `
        -User "SYSTEM" -RunLevel Highest -Description $Description | Out-Null

    if (-not $Actif) { Disable-ScheduledTask -TaskName $Nom | Out-Null }
    Write-Host "  tache posee : $Nom" -ForegroundColor Green
}

Write-Host "`nTaches du scanner" -ForegroundColor Cyan
Poser-Tache -Nom "NADOEDGE-Scanner" -Actif `
  -Commande "`"$python`" -m surebet.main --collector --sport football >> `"$Logs\scanner-football.log`" 2>&1" `
  -Description "NADOEDGE - collecteur football (journal + relance toutes les 5 min)"

# Basketball posé mais DÉSACTIVÉ : un second collecteur, c'est un second
# Chromium. Tant que la fuite mémoire n'est pas comprise, on n'ajoute pas
# une variable à l'équation. À réactiver quand la courbe sera stable.
Poser-Tache -Nom "NADOEDGE-Scanner-Basket" `
  -Commande "`"$python`" -m surebet.main --collector --sport basketball >> `"$Logs\scanner-basket.log`" 2>&1" `
  -Description "NADOEDGE - collecteur basketball (journal + relance toutes les 5 min)"

Write-Host "`nSonde memoire" -ForegroundColor Cyan
$tacheSonde = "NADOEDGE-Sonde-Memoire"
if (Get-ScheduledTask -TaskName $tacheSonde -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $tacheSonde -Confirm:$false
}
Register-ScheduledTask -TaskName $tacheSonde `
    -Action (New-ScheduledTaskAction -Execute "powershell.exe" `
             -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Dossier\outils\sonde_memoire.ps1`"" `
             -WorkingDirectory $Dossier) `
    -Trigger (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
              -RepetitionInterval (New-TimeSpan -Minutes 5) `
              -RepetitionDuration (New-TimeSpan -Days 3650)) `
    -Settings $reglages -User "SYSTEM" -RunLevel Highest `
    -Description "NADOEDGE - releve la memoire validee et les principaux consommateurs" | Out-Null
Start-ScheduledTask -TaskName $tacheSonde
Write-Host "  tache posee : $tacheSonde" -ForegroundColor Green

Write-Host "`nDemarrage" -ForegroundColor Cyan
Start-ScheduledTask -TaskName "NADOEDGE-Scanner"
Start-Sleep 3
foreach ($t in "NADOEDGE-Scanner", "NADOEDGE-Scanner-Basket", $tacheSonde) {
    "  {0,-26} {1}" -f $t, (Get-ScheduledTask -TaskName $t).State | Write-Host
}

Write-Host @"

Termine.

  Journaux      $Logs\scanner-football.log
                $Logs\scanner-basket.log
  Mesures       $Logs\memoire.csv

Le basketball est pose mais ARRETE : demarrez-le quand vous le voudrez par
  Start-ScheduledTask -TaskName NADOEDGE-Scanner-Basket
Deux collecteurs, c'est deux navigateurs Chromium — a n'activer qu'une fois
la fuite memoire comprise.

Dans quelques heures, la courbe se lit ainsi :
  Get-Content $Logs\memoire.csv -Tail 20
"@ -ForegroundColor Gray
