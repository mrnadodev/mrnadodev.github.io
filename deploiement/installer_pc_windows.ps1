# ╔══════════════════════════════════════════════════════════════════════╗
# ║  NADOEDGE · Installation sur un PC Windows                            ║
# ║                                                                       ║
# ║      powershell -ExecutionPolicy Bypass -File deploiement\installer_pc_windows.ps1
# ║                                                                       ║
# ║  Pour une machine personnelle destinee a rester allumee — pas pour un ║
# ║  serveur. Aucune tache planifiee, aucun droit administrateur : une    ║
# ║  surveillance = une fenetre, qu'on ferme pour l'arreter.              ║
# ║                                                                       ║
# ║  Relancable sans risque : tout est verifie avant d'etre installe.     ║
# ╚══════════════════════════════════════════════════════════════════════╝
$ErrorActionPreference = "Stop"

function Titre($t) { Write-Host ""; Write-Host $t -ForegroundColor Cyan }
function Ok($t)    { Write-Host "  [ok] $t" -ForegroundColor Green }
function Info($t)  { Write-Host "  [--] $t" -ForegroundColor DarkGray }
function Souci($t) { Write-Host "  [!!] $t" -ForegroundColor Yellow }

$racine = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)
Set-Location $racine
Write-Host ""
Write-Host "NADOEDGE — installation dans $racine" -ForegroundColor White

# ── 1. Python ─────────────────────────────────────────────────────────
Titre "Python"
$py = Get-Command python -EA SilentlyContinue
if (-not $py) {
    Souci "Python est introuvable."
    Write-Host ""
    Write-Host "  Installez-le depuis https://www.python.org/downloads/"
    Write-Host "  en cochant « Add Python to PATH » sur le premier ecran,"
    Write-Host "  puis relancez ce script."
    Write-Host ""
    exit 1
}
$version = (python --version 2>&1) -replace 'Python\s*',''
$majeur, $mineur = ($version -split '\.')[0..1]
if ([int]$majeur -lt 3 -or ([int]$majeur -eq 3 -and [int]$mineur -lt 11)) {
    Souci "Python $version — la version 3.11 ou plus recente est requise."
    exit 1
}
Ok "Python $version"

# ── 2. Bibliotheques ──────────────────────────────────────────────────
Titre "Bibliotheques"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
Ok "dependances installees (versions figees par requirements.txt)"

# ── 3. Chromium ───────────────────────────────────────────────────────
# pip installe le PILOTE Playwright, jamais le navigateur : il faut un
# second appel, et c'est l'oubli le plus frequent. Sans lui, Paryaj Lakay
# et 1xBet echouent sans message clair.
Titre "Navigateur"
python -m playwright install chromium
Ok "Chromium installe"

# ── 4. Configuration ──────────────────────────────────────────────────
Titre "Configuration"
if (Test-Path "surebet\.env") {
    $lignes = Get-Content "surebet\.env"
    $manque = @()
    foreach ($c in 'TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID') {
        $l = $lignes | Where-Object { $_ -match "^\s*$c\s*=\s*\S" }
        if (-not $l) { $manque += $c }
    }
    if ($manque) {
        Souci "surebet\.env present, mais sans valeur pour : $($manque -join ', ')"
        Write-Host "       Le scanner detectera, mais n'alertera personne."
    } else {
        Ok "surebet\.env complet (les valeurs ne sont pas affichees)"
    }
} else {
    Souci "surebet\.env absent."
    Write-Host "       Copiez-le depuis l'archive d'export de l'ancienne machine,"
    Write-Host "       ou partez de surebet\.env.example."
}

if ((Test-Path "surebet.db") -and (Get-Item "surebet.db").Length -gt 0) {
    Ok ("historique repris : {0:N0} octets" -f (Get-Item "surebet.db").Length)
} else {
    Info "aucun historique : le carnet partira de zero"
}

# ── 5. Raccourcis ─────────────────────────────────────────────────────
Titre "Raccourcis sur le Bureau"
& (Join-Path $racine "Creer-Raccourcis.ps1")

# ── 6. Verification reelle ────────────────────────────────────────────
# On ne declare pas « installe » sans l'avoir prouve : la suite de tests
# touche le calcul d'arbitrage, la normalisation des marches et le
# stockage. Si elle passe, l'environnement est bon.
Titre "Verification"
$sortie = python -m pytest surebet -q 2>&1 | Select-Object -Last 3
$sortie | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
if ($LASTEXITCODE -eq 0) { Ok "tests du scanner : tout passe" }
else { Souci "des tests echouent — ne mettez pas cette machine en production avant de comprendre pourquoi" }

Write-Host ""
Write-Host "─────────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Termine. Trois raccourcis sont sur votre Bureau." -ForegroundColor White
Write-Host ""
Write-Host "  A faire dans l'ordre, avant de lancer la surveillance :"
Write-Host ""
Write-Host "    1. Mettre la machine a l'heure — le scanner filtre les matchs"
Write-Host "       par heure de coup d'envoi. En PowerShell administrateur :"
Write-Host "           w32tm /resync /force"
Write-Host ""
Write-Host "    2. « NADOEDGE - Controle » : tout doit etre au vert."
Write-Host ""
Write-Host "    3. « NADOEDGE - Scanner » choix 4 : un scan a blanc. Les quatre"
Write-Host "       bookmakers doivent rendre des cotes, Paryaj Lakay compris."
Write-Host ""
Write-Host "    4. « NADOEDGE - Scanner » choix 1 : la surveillance demarre."
Write-Host ""
Write-Host "  Et empechez la mise en veille : Parametres > Systeme >"
Write-Host "  Alimentation > Veille > Jamais. Une machine endormie ne"
Write-Host "  surveille rien, et rien ne vous en avertira." -ForegroundColor Yellow
Write-Host ""
