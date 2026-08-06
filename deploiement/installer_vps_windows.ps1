# ╔══════════════════════════════════════════════════════════════════════╗
# ║  NADOEDGE · Installation du scanner sur un VPS Windows Server 2022    ║
# ║                                                                       ║
# ║  À exécuter SUR LE VPS, dans PowerShell EN ADMINISTRATEUR :           ║
# ║      Set-ExecutionPolicy -Scope Process Bypass -Force                 ║
# ║      .\installer_vps_windows.ps1                                      ║
# ║                                                                       ║
# ║  Ni Docker ni WSL : on reproduit exactement l'installation qui        ║
# ║  fonctionne déjà sur votre PC. Le scanner devient une tâche planifiée ║
# ║  qui démarre avec la machine et se relance si elle tombe.             ║
# ║                                                                       ║
# ║  Le script est idempotent : le relancer ne casse rien.                ║
# ╚══════════════════════════════════════════════════════════════════════╝
[CmdletBinding()]
param(
    [string]$Dossier = "C:\nadoedge",
    [string]$Depot   = "https://github.com/mrnadodev/mrnadodev.github.io.git",
    [string]$Branche = "dev",
    [string]$Tache   = "NADOEDGE-Scanner"
)

$ErrorActionPreference = "Stop"

function Etape($t) { Write-Host "`n=== $t" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "  [ok] $t" -ForegroundColor Green }
function Info($t)  { Write-Host "  [..] $t" }
function Alerte($t){ Write-Host "  [!!] $t" -ForegroundColor Yellow }

if (-not ([Security.Principal.WindowsPrincipal] `
        [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Lancez PowerShell en tant qu'administrateur (clic droit > Exécuter en tant qu'administrateur)."
}

# ── 0. Réseau ─────────────────────────────────────────────────────────
# TLS 1.2 explicite : Windows PowerShell 5.1 négocie parfois une version
# refusée par python.org et github.com.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
# Sans ça, Invoke-WebRequest passe l'essentiel de son temps à dessiner une
# barre de progression : un téléchargement de 30 s en prend 5 minutes.
$ProgressPreference = 'SilentlyContinue'

function Rafraichir-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path","User")
}

function Installer-Depuis-Web {
    param([string]$Nom, [string]$Url, [string]$Arguments)
    $fichier = Join-Path $env:TEMP (Split-Path $Url -Leaf)
    Info "téléchargement de $Nom…"
    Invoke-WebRequest -Uri $Url -OutFile $fichier -UseBasicParsing
    Info "installation silencieuse…"
    $p = Start-Process -FilePath $fichier -ArgumentList $Arguments -Wait -PassThru
    Remove-Item $fichier -ErrorAction SilentlyContinue
    if ($p.ExitCode -ne 0) { throw "$Nom : l'installation a échoué (code $($p.ExitCode))" }
    Rafraichir-Path
}

# ── 1. Python ─────────────────────────────────────────────────────────
# winget n'existe PAS sur Windows Server : c'est une application du Store,
# et Server n'a pas de Store. On télécharge l'installeur officiel.
Etape "Python"
$python = $null
try { $python = (Get-Command python -ErrorAction Stop).Source } catch {}
if ($python) {
    Ok "déjà installé : $(python --version 2>&1)"
} else {
    Installer-Depuis-Web -Nom "Python 3.12" `
        -Url "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe" `
        -Arguments "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_launcher=1"
    try { Get-Command python -ErrorAction Stop | Out-Null }
    catch { throw "Python installé mais introuvable dans le PATH. Fermez cette fenêtre PowerShell, rouvrez-en une en administrateur, et relancez le script." }
    Ok "Python installé : $(python --version 2>&1)"
}

# ── 2. Git ────────────────────────────────────────────────────────────
Etape "Git"
try {
    Get-Command git -ErrorAction Stop | Out-Null
    Ok "déjà installé"
} catch {
    Installer-Depuis-Web -Nom "Git" `
        -Url "https://github.com/git-for-windows/git/releases/download/v2.47.0.windows.1/Git-2.47.0-64-bit.exe" `
        -Arguments "/VERYSILENT /NORESTART /NOCANCEL /SP- /SUPPRESSMSGBOXES"
    try { Get-Command git -ErrorAction Stop | Out-Null }
    catch { throw "Git installé mais introuvable dans le PATH. Fermez cette fenêtre PowerShell, rouvrez-en une en administrateur, et relancez le script." }
    Ok "Git installé"
}

# ── 3. Le code ────────────────────────────────────────────────────────
Etape "Code du scanner"
if (Test-Path (Join-Path $Dossier ".git")) {
    Info "mise à jour…"
    git -C $Dossier fetch --quiet origin
    git -C $Dossier checkout --quiet $Branche
    git -C $Dossier pull --quiet --ff-only origin $Branche
} else {
    Info "récupération…"
    git clone --quiet --branch $Branche $Depot $Dossier
}
Ok "code dans $Dossier (branche $Branche)"

# ── 4. Dépendances ────────────────────────────────────────────────────
Etape "Dépendances Python"
Info "installation (quelques minutes la première fois)…"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r (Join-Path $Dossier "surebet\requirements.txt")
Ok "paquets installés"

Info "navigateur Chromium pour Playwright…"
python -m playwright install chromium | Out-Null
Ok "Chromium prêt"

# ── 5. Configuration ──────────────────────────────────────────────────
Etape "Configuration"
$conf = Join-Path $Dossier "surebet\.env"
if (Test-Path $conf) {
    Ok "fichier .env présent"
} else {
    Alerte "$conf est absent."
    Write-Host ""
    Write-Host "     Ce fichier contient le token Telegram : il n'est pas dans le dépôt."
    Write-Host "     Copiez-le depuis votre PC, puis relancez ce script."
    Write-Host ""
    Write-Host "     Depuis PowerShell sur VOTRE PC :"
    Write-Host "       scp surebet\.env Administrateur@IP_DU_VPS:C:/nadoedge/surebet/.env" -ForegroundColor Gray
    Write-Host ""
    Write-Host "     Ou par le presse-papiers du Bureau à distance (copier/coller le fichier)."
    Write-Host ""
    exit 1
}

# ── 6. Tâche planifiée ────────────────────────────────────────────────
# Une tâche plutôt qu'une fenêtre ouverte : elle démarre avec la machine,
# tourne sans session ouverte, et se relance toute seule si elle tombe.
Etape "Démarrage automatique"

$existante = Get-ScheduledTask -TaskName $Tache -ErrorAction SilentlyContinue
if ($existante) {
    Info "tâche existante, remplacement…"
    Unregister-ScheduledTask -TaskName $Tache -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute  (Get-Command python).Source `
    -Argument "-m surebet.main --collector --sport football" `
    -WorkingDirectory $Dossier

$declencheur = New-ScheduledTaskTrigger -AtStartup

$reglages = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 2) -RestartCount 999 `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $Tache `
    -Action $action -Trigger $declencheur -Settings $reglages `
    -User "SYSTEM" -RunLevel Highest `
    -Description "NADOEDGE - surveillance continue des bookmakers" | Out-Null

Ok "tâche « $Tache » enregistrée (démarrage machine, relance auto)"

Start-ScheduledTask -TaskName $Tache
Ok "scanner démarré"

# ── 7. Pare-feu ───────────────────────────────────────────────────────
# Le tableau de bord n'a AUCUNE authentification : publié sur internet, il
# donnerait vos surebets à qui trouve l'adresse IP. On bloque le port.
Etape "Pare-feu"
if (Get-NetFirewallRule -DisplayName "NADOEDGE dashboard bloque" -ErrorAction SilentlyContinue) {
    Ok "règle déjà en place"
} else {
    New-NetFirewallRule -DisplayName "NADOEDGE dashboard bloque" `
        -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Block | Out-Null
    Ok "port 8000 fermé de l'extérieur"
}

# ── 8. Sauvegarde quotidienne de la base ──────────────────────────────
Etape "Sauvegardes"
$sauvegardes = Join-Path $Dossier "sauvegardes"
New-Item -ItemType Directory -Force $sauvegardes | Out-Null

$scriptSauv = Join-Path $Dossier "sauvegarder_base.ps1"
@"
# Copie datée de la base du scanner, 14 jours conservés.
`$src  = "$Dossier\surebet.db"
`$dest = "$sauvegardes\surebet-`$(Get-Date -Format 'yyyy-MM-dd-HHmm').db"
if (Test-Path `$src) { Copy-Item `$src `$dest }
Get-ChildItem "$sauvegardes\surebet-*.db" |
  Where-Object { `$_.LastWriteTime -lt (Get-Date).AddDays(-14) } |
  Remove-Item -Force
"@ | Set-Content -Path $scriptSauv -Encoding UTF8

$tacheSauv = "NADOEDGE-Sauvegarde"
if (Get-ScheduledTask -TaskName $tacheSauv -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $tacheSauv -Confirm:$false
}
Register-ScheduledTask -TaskName $tacheSauv `
    -Action (New-ScheduledTaskAction -Execute "powershell.exe" `
             -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptSauv`"") `
    -Trigger (New-ScheduledTaskTrigger -Daily -At 4am) `
    -User "SYSTEM" -RunLevel Highest `
    -Description "NADOEDGE - copie quotidienne de la base du scanner" | Out-Null
Ok "sauvegarde quotidienne à 4 h, 14 jours conservés"

# ── Fin ───────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== Terminé ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "  État du scanner :"
Write-Host "    Get-ScheduledTask -TaskName $Tache | Get-ScheduledTaskInfo" -ForegroundColor Gray
Write-Host ""
Write-Host "  Contrôle de santé :"
Write-Host "    cd $Dossier ; .\Controle.bat" -ForegroundColor Gray
Write-Host ""
Write-Host "  Arrêter / relancer :"
Write-Host "    Stop-ScheduledTask  -TaskName $Tache" -ForegroundColor Gray
Write-Host "    Start-ScheduledTask -TaskName $Tache" -ForegroundColor Gray
Write-Host ""
Alerte "N'oubliez pas de FERMER Surveillance.bat sur votre PC,"
Write-Host "     sinon vous recevrez chaque alerte en double."
Write-Host ""
