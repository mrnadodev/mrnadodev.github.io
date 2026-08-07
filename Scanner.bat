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
echo     1 = Demarrer le scanner (football)
echo     2 = Arreter le scanner (football)
echo     3 = Etat (tourne-t-il ?)
echo     4 = Scan manuel (Ctrl+C pour sortir)
echo     5 = Controle de sante complet
echo     6 = Sauvegarder la base maintenant
echo.
echo     7 = Demarrer le BASKETBALL
echo     8 = Arreter le basketball
echo     0 = Quitter
echo.
set /p CHOIX="   Votre choix : "
echo.

if "%CHOIX%"=="1" goto demarrer
if "%CHOIX%"=="2" goto arreter
if "%CHOIX%"=="3" goto etat
if "%CHOIX%"=="4" goto journal
if "%CHOIX%"=="5" goto sante
if "%CHOIX%"=="6" goto sauver
if "%CHOIX%"=="7" goto basketon
if "%CHOIX%"=="8" goto basketoff
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
  "'Football        : ' + $t.State;" ^
  "'Derniere execution : ' + $i.LastRunTime;" ^
  "'Dernier resultat   : ' + $i.LastTaskResult + '  (0 = normal)';" ^
  "$b = Get-ScheduledTask -TaskName '%TACHE%-Basket' -ErrorAction SilentlyContinue;" ^
  "if ($b) { 'Basketball      : ' + $b.State } else { 'Basketball      : tache absente' };" ^
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

:sauver
python outils\sauvegarder_scanner.py
echo.
pause
goto menu

:basketon
echo   Le basketball a sa propre tache : run_collector_loop ne traite
echo   qu'un sport a la fois. Un second Chromium double la memoire
echo   consommee : surveillez l'etat ensuite (choix 3).
echo.
powershell -NoProfile -Command ^
  "Enable-ScheduledTask -TaskName '%TACHE%-Basket' | Out-Null; Start-ScheduledTask -TaskName '%TACHE%-Basket'; Start-Sleep 2; 'Basket : ' + (Get-ScheduledTask -TaskName '%TACHE%-Basket').State"
echo.
pause
goto menu

:basketoff
powershell -NoProfile -Command ^
  "Stop-ScheduledTask -TaskName '%TACHE%-Basket' -ErrorAction SilentlyContinue; Disable-ScheduledTask -TaskName '%TACHE%-Basket' | Out-Null; 'Basket : desactive'"
echo.
pause
goto menu
