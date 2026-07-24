@echo off
REM ====================================================================
REM  Surebet Haiti - SURVEILLANCE CONTINUE
REM  Collecte les 4 bookmakers en boucle et envoie chaque surebet
REM  detecte sur Telegram (@NADOTOBET).
REM
REM  Double-cliquer ce fichier et laisser la fenetre ouverte.
REM  Le collector redemarre automatiquement s'il s'arrete.
REM  Fermer la fenetre (ou Ctrl+C) pour arreter la surveillance.
REM ====================================================================
title Surebet Haiti - surveillance continue
cd /d "%~dp0\.."

python --version >nul 2>&1
if errorlevel 1 (
    echo   [ERREUR] Python introuvable. Installez Python 3.11+ ^(Add Python to PATH^).
    pause
    exit /b 1
)

REM Installer les dependances au premier lancement
python -c "import httpx, websockets, curl_cffi, rapidfuzz, sqlalchemy, fastapi, playwright" >nul 2>&1
if errorlevel 1 (
    echo   Premiere utilisation : installation des dependances...
    python -m pip install --quiet -r "surebet\requirements.txt"
    python -m playwright install chromium
)

:loop
echo.
echo   [%date% %time%] Demarrage de la surveillance...
python -m surebet.main --collector --sport football
echo.
echo   [%date% %time%] La surveillance s'est arretee (code %errorlevel%).
echo   Redemarrage dans 15 secondes... (fermez la fenetre pour arreter)
timeout /t 15 /nobreak >nul
goto loop
