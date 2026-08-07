@echo off
REM ====================================================================
REM  NADOEDGE - Pilotage du scanner
REM  Double-cliquer ce fichier (ou son raccourci sur le Bureau).
REM  Demande les droits administrateur : la tache planifiee en a besoin.
REM ====================================================================
title NADOEDGE - scanner

REM --- Elevation automatique -------------------------------------------
net session >nul 2>&1
if errorlevel 1 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set TACHE=NADOEDGE-Scanner

:menu
cls
echo.
echo   ================================================================
echo     NADOEDGE - scanner
echo   ================================================================
echo.
echo     1 = Demarrer le scanner
echo     2 = Arreter le scanner
echo     3 = Etat (tourne-t-il ?)
echo     4 = Journal en direct (Ctrl+C pour sortir)
echo     5 = Controle de sante complet
echo     0 = Quitter
echo.
set /p CHOIX="   Votre choix : "
echo.

if "%CHOIX%"=="1" goto demarrer
if "%CHOIX%"=="2" goto arreter
if "%CHOIX%"=="3" goto etat
if "%CHOIX%"=="4" goto journal
if "%CHOIX%"=="5" goto sante
if "%CHOIX%"=="0" exit /b
goto menu

:demarrer
powershell -NoProfile -Command ^
  "Enable-ScheduledTask -TaskName '%TACHE%' -ErrorAction SilentlyContinue | Out-Null; Start-ScheduledTask -TaskName '%TACHE%'; Start-Sleep 2; (Get-ScheduledTask -TaskName '%TACHE%').State"
echo.
echo   Running = le scanner tourne. Les alertes arrivent sur Telegram.
pause
goto menu

:arreter
powershell -NoProfile -Command ^
  "Stop-ScheduledTask -TaskName '%TACHE%'; Start-Sleep 2; (Get-ScheduledTask -TaskName '%TACHE%').State"
echo.
echo   Ready = arrete. Il repartira au prochain demarrage de la machine.
pause
goto menu

:etat
powershell -NoProfile -Command ^
  "$t = Get-ScheduledTask -TaskName '%TACHE%' -ErrorAction SilentlyContinue;" ^
  "if (-not $t) { 'Tache absente : relancez installer_vps_windows.ps1'; exit }" ^
  "$i = $t | Get-ScheduledTaskInfo;" ^
  "'Etat            : ' + $t.State;" ^
  "'Derniere execution : ' + $i.LastRunTime;" ^
  "'Dernier resultat   : ' + $i.LastTaskResult + '  (0 = normal)';" ^
  "$c = Get-Process chrome*,chromium* -ErrorAction SilentlyContinue;" ^
  "if ($c) { 'Chromium        : ' + $c.Count + ' processus, ' + [math]::Round(($c | Measure-Object WorkingSet64 -Sum).Sum/1GB,1) + ' Go' } else { 'Chromium        : aucun processus' }"
echo.
pause
goto menu

:journal
echo   Journal du scanner. Ctrl+C pour revenir au menu.
echo.
python -m surebet.main --scan --sport football
echo.
pause
goto menu

:sante
python outils\controle_sante.py
echo.
pause
goto menu
