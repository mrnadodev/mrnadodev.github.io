@echo off
REM ====================================================================
REM  NADOEDGE - Carnet de bord du scanner
REM  Double-cliquer ce fichier chaque jour, pendant la semaine d'essai.
REM
REM  Sans argument  : pointer les detections une par une.
REM  Avec "bilan"   : afficher le bilan de la semaine.
REM ====================================================================
title NADOEDGE - carnet du scanner
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

echo.
echo   ================================================================
echo     1 = pointer les detections du jour  (2 minutes)
echo     2 = voir le bilan de la semaine
echo   ================================================================
echo.
set /p CHOIX="   Votre choix (1 ou 2) : "

echo.
if "%CHOIX%"=="2" (
    python outils\journal_scanner.py --rapport --jours 7
) else (
    python outils\journal_scanner.py
)

echo.
pause
