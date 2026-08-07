# ╔══════════════════════════════════════════════════════════════════════╗
# ║  NADOEDGE · Raccourcis sur le Bureau                                  ║
# ║                                                                       ║
# ║  À exécuter une fois, sur le VPS comme sur votre PC :                 ║
# ║      powershell -ExecutionPolicy Bypass -File .\Creer-Raccourcis.ps1  ║
# ║                                                                       ║
# ║  Crée trois raccourcis : piloter le scanner, contrôler la santé,      ║
# ║  tenir le carnet de bord. Relancer le script les remplace.            ║
# ╚══════════════════════════════════════════════════════════════════════╝
$ErrorActionPreference = "Stop"

$racine  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$bureau  = [Environment]::GetFolderPath("Desktop")
$shell   = New-Object -ComObject WScript.Shell

# Nom du raccourci, fichier cible, icône (index dans shell32.dll)
$raccourcis = @(
    @{ Nom = "NADOEDGE - Scanner";  Cible = "Scanner.bat";  Icone = 137 }  # engrenage
    @{ Nom = "NADOEDGE - Controle"; Cible = "Controle.bat"; Icone = 23  }  # coche
    @{ Nom = "NADOEDGE - Carnet";   Cible = "Carnet.bat";   Icone = 70  }  # carnet
)

foreach ($r in $raccourcis) {
    $cible = Join-Path $racine $r.Cible
    if (-not (Test-Path $cible)) {
        Write-Host "  [!!] $($r.Cible) introuvable, raccourci ignore" -ForegroundColor Yellow
        continue
    }
    $lien = Join-Path $bureau "$($r.Nom).lnk"
    $s = $shell.CreateShortcut($lien)
    $s.TargetPath       = $cible
    $s.WorkingDirectory = $racine
    $s.IconLocation     = "shell32.dll,$($r.Icone)"
    $s.Description      = "NADOEDGE"
    $s.Save()
    Write-Host "  [ok] $($r.Nom)" -ForegroundColor Green
}

Write-Host ""
Write-Host "Raccourcis crees sur le Bureau : $bureau"
Write-Host ""
Write-Host "  Scanner  : demarrer, arreter, voir l'etat"
Write-Host "  Controle : verifier que tout fonctionne"
Write-Host "  Carnet   : pointer les detections, voir le bilan"
Write-Host ""
