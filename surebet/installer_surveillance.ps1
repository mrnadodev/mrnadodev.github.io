# ============================================================================
#  Surebet Haiti - installation de la surveillance automatique (Windows)
#
#  Enregistre une TACHE PLANIFIEE qui lance la surveillance continue :
#   - au demarrage de session (logon) ;
#   - relancee automatiquement si elle s'arrete ;
#   - tourne en tache de fond (les alertes partent sur Telegram).
#
#  UTILISATION : clic droit sur ce fichier -> "Executer avec PowerShell".
#  (Si un message de securite apparait, voir la note en bas.)
#
#  Pour DESINSTALLER : relancer avec le parametre -Remove :
#     powershell -ExecutionPolicy Bypass -File installer_surveillance.ps1 -Remove
# ============================================================================
param([switch]$Remove)

$ErrorActionPreference = "Stop"
$TaskName   = "SurebetHaiti-Surveillance"
$ProjectDir = Split-Path -Parent $PSScriptRoot          # racine du depot
$BatPath    = Join-Path $PSScriptRoot "Surveillance.bat"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "Tache '$TaskName' supprimee. La surveillance ne demarrera plus automatiquement."
    return
}

if (-not (Test-Path $BatPath)) {
    Write-Output "ERREUR : Surveillance.bat introuvable a cote de ce script."
    return
}

# Action : lancer Surveillance.bat (qui contient la boucle de redemarrage)
$action = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument "/c `"$BatPath`"" -WorkingDirectory $ProjectDir

# Declencheur : a l'ouverture de session de l'utilisateur courant
$trigger = New-ScheduledTaskTrigger -AtLogOn

# Reglages : relance si echec, pas de limite de duree, demarre meme sur batterie
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Output "OK : surveillance installee (tache '$TaskName')."
Write-Output "     Elle demarrera a chaque ouverture de session Windows."
Write-Output ""
Write-Output "Demarrer MAINTENANT sans attendre la prochaine session ?"
$rep = Read-Host "Taper O pour demarrer tout de suite, ou Entree pour plus tard"
if ($rep -eq "O" -or $rep -eq "o") {
    Start-ScheduledTask -TaskName $TaskName
    Write-Output "Surveillance demarree. Les alertes arriveront sur @NADOTOBET."
}

# --------------------------------------------------------------------------
# NOTE si PowerShell bloque l'execution du script :
#   ouvrir PowerShell et lancer :
#     powershell -ExecutionPolicy Bypass -File "chemin\vers\installer_surveillance.ps1"
# --------------------------------------------------------------------------
