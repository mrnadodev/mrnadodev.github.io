@echo off
REM ====================================================================
REM  NADOEDGE - Controle de sante
REM  Double-cliquer ce fichier (ou son raccourci sur le Bureau).
REM  Verifie : Supabase, horloge, migrations, Telegram, tests.
REM ====================================================================
title NADOEDGE - controle de sante
cd /d "%~dp0"

REM La console Windows est en cp1252 par defaut : les accents deviennent
REM des points d'interrogation. On passe en UTF-8 pour la duree du script.
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
python outils\controle_sante.py
echo.
echo   ----------------------------------------------------------------
echo   Une ligne [ ALERTE] = quelque chose a corriger.
echo   Tout en [  OK  ] = rien a faire.
echo   ----------------------------------------------------------------
echo.
pause
