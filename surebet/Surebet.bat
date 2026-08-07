@echo off
REM ====================================================================
REM  Surebet Haiti - lanceur quotidien
REM  Double-cliquer ce fichier (ou son raccourci sur le Bureau).
REM  Scanne les 4 bookmakers, affiche les opportunites, ouvre le tableau
REM  de bord dans le navigateur.
REM ====================================================================
title Surebet Haiti - scan du jour
cd /d "%~dp0\.."

echo.
echo   Demarrage du scan Surebet...
echo.

REM --- Verifier que Python est disponible -------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo   [ERREUR] Python est introuvable.
    echo   Installez Python 3.11+ depuis https://www.python.org/downloads/
    echo   en cochant "Add Python to PATH", puis relancez ce fichier.
    echo.
    pause
    exit /b 1
)

REM --- Verifier les dependances (installe au premier lancement) ----------
python -c "import httpx, websockets, curl_cffi, rapidfuzz, sqlalchemy, fastapi" >nul 2>&1
if errorlevel 1 (
    echo   Premiere utilisation : installation des dependances...
    echo   ^(cela peut prendre 2-3 minutes^)
    echo.
    python -m pip install --quiet -r "surebet\requirements.txt"
    if errorlevel 1 (
        echo   [ERREUR] L'installation des dependances a echoue.
        pause
        exit /b 1
    )
)

REM Toujours s'assurer que le navigateur Playwright est present (idempotent).
python -m playwright install chromium >nul 2>&1

REM --- Lancer le scan + le tableau de bord -------------------------------
python -m surebet.main --scan --dashboard --sport football

echo.
pause
