@echo off
REM ====================================================================
REM  NADOEDGE - Poste de surveillance local
REM
REM  Double-cliquer ce fichier, ou son raccourci sur le Bureau.
REM  Aucun droit administrateur requis : contrairement a la version VPS,
REM  ce lanceur ne pilote pas de taches planifiees. Une surveillance =
REM  une fenetre. Fermer la fenetre arrete la surveillance.
REM
REM  Pourquoi en local : depuis aout 2026, l'API de Paryaj Lakay refuse
REM  les adresses de centres de donnees. Depuis une connexion haitienne,
REM  les QUATRE bookmakers repondent. Ce poste voit donc tout le marche.
REM ====================================================================
title NADOEDGE - surveillance
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo   [ERREUR] Python est introuvable.
    echo   Installez Python 3.11+ depuis https://www.python.org/downloads/
    echo   en cochant "Add Python to PATH", puis relancez ce fichier.
    echo.
    pause
    exit /b 1
)

:menu
cls
echo.
echo   ================================================================
echo     NADOEDGE - surveillance locale        4 bookmakers
echo   ================================================================
echo.
echo     SURVEILLANCE CONTINUE       (s'ouvre dans une fenetre a part)
echo       1 = Football
echo       2 = Basketball
echo       3 = Les deux
echo.
echo     VERIFIER MAINTENANT         (un seul passage, puis rend la main)
echo       4 = Scan football
echo       5 = Scan basketball
echo.
echo     SUIVI
echo       6 = Controle de sante
echo       7 = Carnet - detections et bilan
echo       8 = Sauvegarder la base
echo       9 = Tableau de bord visuel
echo.
echo       0 = Quitter
echo.
set /p CHOIX="   Votre choix : "
echo.

if "%CHOIX%"=="1" goto foot
if "%CHOIX%"=="2" goto basket
if "%CHOIX%"=="3" goto deux
if "%CHOIX%"=="4" goto scanfoot
if "%CHOIX%"=="5" goto scanbasket
if "%CHOIX%"=="6" goto sante
if "%CHOIX%"=="7" goto carnet
if "%CHOIX%"=="8" goto sauver
if "%CHOIX%"=="9" goto tableau
if "%CHOIX%"=="0" exit /b
goto menu

REM --- Surveillance continue ------------------------------------------
REM  BROWSER_PROFILE_DIR distinct par sport : Playwright VERROUILLE le
REM  dossier de profil qu'il ouvre. Sans cette separation, lancer les deux
REM  sports fait echouer le second a demarrer ses navigateurs — en silence,
REM  le collecteur continuant de tourner sans jamais recuperer de cotes.

REM  set "VAR=valeur" et non set VAR=valeur : sans les guillemets, cmd
REM  inclut dans la valeur l'espace qui precede le &. Le profil devenait
REM  « .browser-profiles\football  » avec une espace finale, et Windows
REM  refuse de creer un dossier dont le nom se termine par une espace.
REM  Paryaj Lakay echouait donc au demarrage de sa session navigateur.

:foot
echo   Football : surveillance continue dans une nouvelle fenetre.
echo   Fermez cette fenetre-la pour arreter. Ctrl+C fonctionne aussi.
echo.
start "NADOEDGE - football" cmd /k "chcp 65001 >nul & set "PYTHONIOENCODING=utf-8" & set "BROWSER_PROFILE_DIR=./.browser-profiles/football" & python -m surebet.main --collector --sport football"
timeout /t 2 /nobreak >nul
goto menu

:basket
echo   Basketball : surveillance continue dans une nouvelle fenetre.
echo.
start "NADOEDGE - basketball" cmd /k "chcp 65001 >nul & set "PYTHONIOENCODING=utf-8" & set "BROWSER_PROFILE_DIR=./.browser-profiles/basketball" & python -m surebet.main --collector --sport basketball"
timeout /t 2 /nobreak >nul
goto menu

:deux
echo   Les deux sports, dans deux fenetres separees.
echo.
echo   A savoir : chaque sport ouvre son propre jeu de navigateurs.
echo   Comptez environ 1 Go de memoire par sport. Si la machine peine,
echo   n'en gardez qu'un.
echo.
start "NADOEDGE - football" cmd /k "chcp 65001 >nul & set "PYTHONIOENCODING=utf-8" & set "BROWSER_PROFILE_DIR=./.browser-profiles/football" & python -m surebet.main --collector --sport football"
timeout /t 3 /nobreak >nul
start "NADOEDGE - basketball" cmd /k "chcp 65001 >nul & set "PYTHONIOENCODING=utf-8" & set "BROWSER_PROFILE_DIR=./.browser-profiles/basketball" & python -m surebet.main --collector --sport basketball"
timeout /t 2 /nobreak >nul
goto menu

REM --- Passage unique --------------------------------------------------
:scanfoot
echo   Scan football. Les cotes de chaque bookmaker s'affichent ci-dessous.
echo.
python -m surebet.main --scan --sport football
echo.
pause
goto menu

:scanbasket
echo   Scan basketball.
echo.
python -m surebet.main --scan --sport basketball
echo.
pause
goto menu

REM --- Suivi ------------------------------------------------------------
:sante
python outils\controle_sante.py
echo.
echo   ----------------------------------------------------------------
echo   [ ALERTE] = quelque chose a corriger.  [  OK  ] = rien a faire.
echo   ----------------------------------------------------------------
echo.
pause
goto menu

:carnet
echo     1 = pointer les detections du jour
echo     2 = bilan football        3 = bilan basketball
echo     4 = les deux melanges     5 = poids de chaque bookmaker
echo.
set /p C2="   Votre choix : "
echo.
if "%C2%"=="2" ( python outils\journal_scanner.py --rapport --jours 7 --sport football
) else if "%C2%"=="3" ( python outils\journal_scanner.py --rapport --jours 7 --sport basketball
) else if "%C2%"=="4" ( python outils\journal_scanner.py --rapport --jours 7
) else if "%C2%"=="5" ( python outils\valeur_bookmaker.py --jours 30
) else ( python outils\journal_scanner.py )
echo.
pause
goto menu

:sauver
python outils\sauvegarder_scanner.py
echo.
pause
goto menu

:tableau
REM Le tableau de bord n'a AUCUNE authentification : il n'ecoute que sur
REM 127.0.0.1. En local c'est sans risque — la machine est la votre.
REM Il fait son PROPRE scan a chaque chargement de page : ouvrez-le a la
REM demande, ne le laissez pas tourner en permanence.
echo   Tableau de bord sur http://127.0.0.1:8000
echo   Fermez sa fenetre pour l'arreter.
echo.
start "NADOEDGE - tableau de bord" cmd /c "python -m uvicorn surebet.dashboard.app:app --host 127.0.0.1 --port 8000 --log-level warning"
timeout /t 4 /nobreak >nul
start "" "http://127.0.0.1:8000"
echo.
pause
goto menu
