# ╔══════════════════════════════════════════════════════════════════════╗
# ║  NADOEDGE · Exporter vers une autre machine                           ║
# ║                                                                       ║
# ║      powershell -ExecutionPolicy Bypass -File outils\exporter_pour_autre_pc.ps1
# ║                                                                       ║
# ║  Fabrique une archive contenant ce que git ne transporte PAS :        ║
# ║  le fichier .env et la base d'historique. Le code, lui, s'obtient     ║
# ║  par « git clone » sur la machine d'arrivée.                          ║
# ║                                                                       ║
# ║  Ce qui est volontairement EXCLU :                                    ║
# ║   · .browser-profiles — 286 Mo, reconstruit tout seul, et contient    ║
# ║     des cookies de session qu'il vaut mieux ne pas promener ;         ║
# ║   · le code — il est public sur GitHub, le cloner est plus sûr que    ║
# ║     de copier un dossier qui peut avoir dérivé.                       ║
# ║                                                                       ║
# ║  ⚠ L'ARCHIVE CONTIENT VOTRE JETON TELEGRAM. Transportez-la par clé   ║
# ║  USB. Ni e-mail, ni WhatsApp, ni messagerie : ces canaux gardent une  ║
# ║  copie sur des serveurs que vous ne contrôlez pas. Effacez-la des     ║
# ║  deux machines une fois l'installation faite.                         ║
# ╚══════════════════════════════════════════════════════════════════════╝
$ErrorActionPreference = "Stop"

$racine = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)
Set-Location $racine

$horodatage = Get-Date -Format "yyyy-MM-dd-HHmm"
$temp    = Join-Path $env:TEMP "nadoedge-export-$horodatage"
$archive = Join-Path ([Environment]::GetFolderPath("Desktop")) "NADOEDGE-export-$horodatage.zip"

New-Item -ItemType Directory -Force $temp | Out-Null
New-Item -ItemType Directory -Force (Join-Path $temp "surebet") | Out-Null

Write-Host ""
Write-Host "Ce qui part dans l'archive" -ForegroundColor Cyan

# ── Le .env : seuils, jetons, identifiants de canal ───────────────────
if (Test-Path "surebet\.env") {
    Copy-Item "surebet\.env" (Join-Path $temp "surebet\.env")
    Write-Host ("  [ok] surebet\.env            {0,10:N0} octets" -f (Get-Item "surebet\.env").Length) -ForegroundColor Green
} else {
    Write-Host "  [!!] surebet\.env introuvable — la machine d'arrivee n'alertera pas" -ForegroundColor Yellow
}

# ── L'historique : ce qui alimente le carnet et les bilans ────────────
# VACUUM INTO plutot qu'une copie : un instantane coherent meme si le
# collecteur ecrit au meme moment. Une copie brute pendant une ecriture
# donne un fichier corrompu, et on ne s'en apercoit qu'au moment de s'en
# servir — c'est-a-dire trop tard.
if ((Test-Path "surebet.db") -and (Get-Item "surebet.db").Length -gt 0) {
    # La requete passe en ARGUMENT, pas dans le code : imbriquer des
    # guillemets dans un -c revient a melanger les regles d'echappement de
    # PowerShell et de Python, et le fichier ne se lit meme plus.
    # AUCUN guillemet dans le code : PowerShell 5.1 les mange en passant les
    # arguments a un executable, et Python recoit alors du code invalide.
    # Chemin et requete passent donc tous les deux en argument.
    $cible = (Join-Path $temp "surebet.db") -replace '\\', '/'
    $code = 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(sys.argv[2]); c.close()'
    python -c $code surebet.db "vacuum into '$cible'" 2>$null
    if (Test-Path (Join-Path $temp "surebet.db")) {
        Write-Host ("  [ok] surebet.db              {0,10:N0} octets" -f (Get-Item (Join-Path $temp "surebet.db")).Length) -ForegroundColor Green
    } else {
        Copy-Item "surebet.db" (Join-Path $temp "surebet.db")
        Write-Host "  [ok] surebet.db (copie simple, VACUUM indisponible)" -ForegroundColor Yellow
    }
} else {
    Write-Host "  [--] surebet.db vide ou absente — rien a transferer" -ForegroundColor DarkGray
}

# ── Les sauvegardes recentes, s'il y en a ────────────────────────────
if (Test-Path "sauvegardes") {
    $recentes = Get-ChildItem "sauvegardes\*.db" -EA 0 | Sort-Object LastWriteTime -Descending | Select-Object -First 3
    if ($recentes) {
        New-Item -ItemType Directory -Force (Join-Path $temp "sauvegardes") | Out-Null
        $recentes | Copy-Item -Destination (Join-Path $temp "sauvegardes")
        Write-Host "  [ok] $($recentes.Count) sauvegarde(s) recente(s)" -ForegroundColor Green
    }
}

# ── La marche a suivre, dans l'archive elle-meme ──────────────────────
@"
NADOEDGE — installation sur la nouvelle machine
Archive du $horodatage

1. Installez Python 3.11 ou plus recent depuis python.org,
   en cochant « Add Python to PATH ».

2. Installez Git depuis git-scm.com, puis dans PowerShell :

       cd C:\
       git clone https://github.com/mrnadodev/mrnadodev.github.io.git nadoedge
       cd nadoedge

3. Copiez le contenu de cette archive DANS C:\nadoedge, en ecrasant.
   Le fichier surebet\.env doit se retrouver a cet emplacement exact.

4. Lancez l'installation :

       powershell -ExecutionPolicy Bypass -File deploiement\installer_pc_windows.ps1

5. Verifiez :  double-cliquez « NADOEDGE - Controle » sur le Bureau.

6. EFFACEZ CETTE ARCHIVE des deux machines : elle contient votre jeton
   Telegram.
"@ | Out-File (Join-Path $temp "LISEZ-MOI.txt") -Encoding utf8

if (Test-Path $archive) { Remove-Item $archive -Force }
Compress-Archive -Path (Join-Path $temp "*") -DestinationPath $archive -Force
Remove-Item $temp -Recurse -Force

Write-Host ""
Write-Host "Archive : $archive" -ForegroundColor Green
Write-Host ("Taille  : {0:N0} octets" -f (Get-Item $archive).Length)
Write-Host ""
Write-Host "  Transportez-la par cle USB — elle contient votre jeton Telegram." -ForegroundColor Yellow
Write-Host "  Ni e-mail, ni WhatsApp : ces canaux en gardent une copie ailleurs." -ForegroundColor Yellow
Write-Host "  Effacez-la des deux machines une fois l'installation terminee." -ForegroundColor Yellow
Write-Host ""
