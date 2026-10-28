@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title 12:00 Media Server - Instalador Windows

echo.
echo  ================================================
echo   12:00 Media Server - Instalador (Windows)
echo   Netflix-style player para suas nuvens e HDs
echo  ================================================
echo.

set "DIR=%~dp0"
if not exist "%DIR%server.py" (
    echo  [ERRO] server.py nao encontrado em %DIR%
    echo  Execute este instalador dentro da pasta do 12:00 Media Server.
    pause
    exit /b 1
)
echo  [OK] Diretorio do projeto: %DIR%

REM ─── 1. Python 3.9+ ────────────────────────────────────
echo.
echo  Verificando Python...
set "PY="
py -3 --version >nul 2>&1
if %errorlevel%==0 set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1
    if %errorlevel%==0 set "PY=python"
)
if not defined PY (
    echo  [ERRO] Python 3.9+ nao encontrado.
    echo  Baixe em https://www.python.org/downloads/ e marque "Add to PATH".
    echo  Depois rode este instalador novamente.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('%PY% --version 2^>^&1') do set "PYVER=%%v"
echo  [OK] Python encontrado: !PYVER!

REM Resolve o caminho real do python.exe (evita "py -3" no serviço)
for /f "delims=" %%p in ('%PY% -c "import sys;print(sys.executable)"') do set "PYEXE=%%p"
if not exist "%PYEXE%" (
    echo  [ERRO] Nao consegui resolver o caminho do Python.
    pause
    exit /b 1
)
echo  [OK] Python: %PYEXE%

REM ─── 2. rclone ─────────────────────────────────────────
echo.
echo  Verificando rclone...
where rclone >nul 2>&1
if %errorlevel%==0 (
    for /f "delims=" %%r in ('rclone version 2^>nul ^| findstr /b "rclone"') do set "RCLONEVER=%%r"
    echo  [OK] rclone encontrado: !RCLONEVER!
) else (
    echo  [AVISO] rclone nao encontrado. Tentando instalar...
    winget --version >nul 2>&1
    if !errorlevel!==0 (
        echo  Instalando via winget (Rclone.Rclone)...
        winget install -e --id Rclone.Rclone --accept-source-agreements --accept-package-agreements
    ) else (
        echo  Baixando o rclone oficial...
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://downloads.rclone.org/rclone-current-windows-amd64.zip' -OutFile '%TEMP%\rclone.zip'"
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force '%TEMP%\rclone.zip' '%LOCALAPPDATA%\rclone'"
        set "RCLONE_DIR=%LOCALAPPDATA%\rclone"
        for /d %%d in ("%LOCALAPPDATA%\rclone\rclone-*") do set "RCLONE_DIR=%%d"
        if exist "%RCLONE_DIR%\rclone.exe" (
            setx PATH "%PATH%;%RCLONE_DIR%" >nul
            set "PATH=%PATH%;%RCLONE_DIR%"
            echo  [OK] rclone instalado em %RCLONE_DIR% (adicionei ao PATH do usuario)
        ) else (
            echo  [ERRO] Falha ao extrair o rclone.
            pause
            exit /b 1
        )
    )
)
rclone version >nul 2>&1
if errorlevel 1 (
    echo  [ERRO] rclone ainda nao disponivel. Abra um novo terminal e rode o instalador de novo,
    echo  ou baixe manualmente em https://rclone.org/downloads/ e adicione ao PATH.
    pause
    exit /b 1
)

REM ─── 3. Nuvem (qualquer remote do rclone) ───────────────
echo.
echo  Verificando conexao com a nuvem...
rclone listremotes 2>nul | findstr /r "^[a-zA-Z0-9]" >nul
if errorlevel 1 (
    echo  [AVISO] Nuvem ainda nao configurada.
    echo  Configure depois em Ajustes ^> Nuvem, dentro do 12:00 Media Server:
    echo  use um remote que ja exista no rclone ou crie um novo pelo assistente.
) else (
    echo  [OK] rclone pronto (conecte a nuvem em Ajustes ^> Nuvem)
)

REM ─── 4. Diretórios de cache ────────────────────────────
if exist "%DIR%TicianoFlix.bat" del "%DIR%TicianoFlix.bat"
schtasks /Delete /TN "TicianoFlix" /F >nul 2>&1
if not exist "%USERPROFILE%\.cache\media-server\images" mkdir "%USERPROFILE%\.cache\media-server\images"
if not exist "%USERPROFILE%\.cache\media-server\subs" mkdir "%USERPROFILE%\.cache\media-server\subs"
if not exist "%USERPROFILE%\.cache\rclone" mkdir "%USERPROFILE%\.cache\rclone"
echo.
echo  [OK] Diretorios de cache prontos (%USERPROFILE%\.cache\media-server)

REM ─── 5. Script de execução ─────────────────────────────
(
echo @echo off
echo chcp 65001 ^>nul
echo cd /d "%DIR%"
echo "%PYEXE%" server.py
echo pause
) > "%DIR%Media-Server.bat"
echo  [OK] Criado %DIR%Media-Server.bat
echo       (duplo clique nele para iniciar o servidor)

REM ─── 6. Iniciar junto com o Windows? (opcional) ────────
set /p AUTOSTART="  Iniciar o 12:00 Media Server junto com o Windows? (s/N): "
if /i "%AUTOSTART%"=="s" (
    schtasks /Create /F /TN "Media Server" /SC ONLOGON /RL LIMITED /TR "\"%DIR%Media-Server.bat\""
    if errorlevel 1 (
        echo  [AVISO] Nao consegui criar a tarefa. Rode o instalador como administrador se quiser.
    ) else (
        echo  [OK] Tarefa agendada criada (inicia no login).
    )
)

REM ─── 7. Iniciar agora? ─────────────────────────────────
set /p INICIAR="  Iniciar o 12:00 Media Server agora? (s/N): "
if /i "%INICIAR%"=="s" (
    start "" cmd /c ""%DIR%Media-Server.bat""
)

echo.
echo  ================================================
echo   Instalacao concluida!
echo.
echo   Acesse:  http://localhost:8080
echo   Logs:    %USERPROFILE%\.cache\media-server\
echo   Parar:   feche a janela do servidor
echo   Desativar autostart: schtasks /Delete /TN "Media Server" /F
echo  ================================================
echo.
pause

