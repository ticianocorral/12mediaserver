@echo off
rem 12:00 Media Server - instalador visual para Windows (duplo clique).
rem Abre um assistente no navegador; so precisa do Python 3 (python.org).
rem Ao instalar o Python, marque "Add python.exe to PATH".
cd /d "%~dp0"
chcp 65001 >nul

where python >nul 2>&1 && (
    python instalador\instalador.py %*
    goto :fim
)
where py >nul 2>&1 && (
    py -3 instalador\instalador.py %*
    goto :fim
)

echo.
echo  Nao encontrei o Python 3 (necessario para o assistente).
echo  Instale em https://www.python.org/downloads/ marcando "Add python.exe to PATH"
echo  e abra este arquivo de novo.
echo.
echo  Alternativa: Instalador-Media-Server-Windows.bat
echo.

:fim
pause
