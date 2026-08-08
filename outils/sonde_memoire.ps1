# ╔══════════════════════════════════════════════════════════════════════╗
# ║  NADOEDGE · Sonde mémoire                                             ║
# ║                                                                       ║
# ║  Note toutes les 5 minutes la mémoire validée du serveur et les cinq  ║
# ║  processus qui en consomment le plus.                                 ║
# ║                                                                       ║
# ║  Pourquoi : le 8 août 2026, la mémoire validée est passée de 2,5 Go   ║
# ║  à 53,4 Go, le collecteur est mort avec le code 255, et PowerShell    ║
# ║  lui-même ne démarrait plus. Au moment du constat, plus aucun         ║
# ║  processus ne détenait cette mémoire : l'instantané ne dit rien, il   ║
# ║  faut la COURBE. Cette sonde la produit.                              ║
# ║                                                                       ║
# ║  Ce qu'elle permet de trancher :                                      ║
# ║   · montée corrélée au collecteur → la fuite est dans notre code ;    ║
# ║   · montée sans processus identifiable → l'hôte VMware reprend de la  ║
# ║     mémoire (« ballooning »), et c'est à l'hébergeur d'agir.          ║
# ╚══════════════════════════════════════════════════════════════════════╝

$dossier = Join-Path $PSScriptRoot "..\logs"
if (-not (Test-Path $dossier)) { New-Item -ItemType Directory -Force $dossier | Out-Null }
$journal = Join-Path $dossier "memoire.csv"

$os      = Get-CimInstance Win32_OperatingSystem
$valide  = [math]::Round(($os.TotalVirtualMemorySize - $os.FreeVirtualMemory) / 1MB, 2)
$limite  = [math]::Round($os.TotalVirtualMemorySize / 1MB, 2)
$ramLib  = [math]::Round($os.FreePhysicalMemory / 1MB, 2)

# Les cinq plus gros consommateurs de mémoire validée, agrégés par nom :
# Chromium se répartit sur des dizaines de processus, les compter un par un
# masquerait le total.
$top = Get-Process -ErrorAction SilentlyContinue |
       Group-Object ProcessName |
       ForEach-Object {
         [pscustomobject]@{
           nom = $_.Name
           go  = [math]::Round((($_.Group | Measure-Object PagedMemorySize64 -Sum).Sum) / 1GB, 2)
           n   = $_.Count
         }
       } |
       Sort-Object go -Descending | Select-Object -First 5

$detail = ($top | ForEach-Object { "$($_.nom)x$($_.n)=$($_.go)Go" }) -join " "

if (-not (Test-Path $journal)) {
  "horodatage;validee_go;limite_go;ram_libre_go;principaux" | Out-File $journal -Encoding utf8
}
"{0};{1};{2};{3};{4}" -f (Get-Date -Format "yyyy-MM-dd HH:mm"), $valide, $limite, $ramLib, $detail |
  Out-File $journal -Append -Encoding utf8

# Rotation : un fichier de mesures ne doit jamais devenir un problème de
# disque à son tour. Au-delà de 5 Mo on ne garde que les 3000 dernières
# lignes, soit une dizaine de jours à raison d'une mesure toutes les 5 min.
if ((Get-Item $journal).Length -gt 5MB) {
  $lignes = Get-Content $journal
  $lignes[0], ($lignes | Select-Object -Last 3000) | Set-Content $journal -Encoding utf8
}
