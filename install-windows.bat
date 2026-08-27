@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title TicianoFlix - Instalador Windows

echo.
echo  ================================================
echo   TicianoFlix - Instalador (Windows)
echo   Netflix-style player para Google Drive
echo  ================================================
echo.

set "DIR=%~dp0"
if not exist "%DIR%server.py" (
    echo  [ERRO] server.py nao encontrado em %DIR%
    echo  Execute este instalador dentro da pasta do TicianoFlix.
    pause
    exit /b 1
)
echo  [OK] Diretorio do projeto: %DIR%

REM ─── 1. Python 3.10+ ───────────────────────────────────
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
    echo  [ERRO] Python 3.10+ nao encontrado.
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

REM ─── 3. Remote gdrive: ─────────────────────────────────
echo.
echo  Verificando remote gdrive:...
rclone listremotes 2>nul | findstr /b "gdrive:" >nul
if errorlevel 1 (
    echo  [AVISO] Remote 'gdrive:' nao configurado.
    echo  Configure depois pelo botao [rclone] dentro do TicianoFlix
    echo  (ou rode 'rclone config' no terminal).
) else (
    echo  [OK] Remote gdrive: ja configurado
    call :checar_acesso_drive
)

REM ─── 4. Diretórios de cache ────────────────────────────
if not exist "%USERPROFILE%\.cache\ticianoflix\images" mkdir "%USERPROFILE%\.cache\ticianoflix\images"
if not exist "%USERPROFILE%\.cache\ticianoflix\subs" mkdir "%USERPROFILE%\.cache\ticianoflix\subs"
if not exist "%USERPROFILE%\.cache\rclone" mkdir "%USERPROFILE%\.cache\rclone"
echo.
echo  [OK] Diretorios de cache prontos (%USERPROFILE%\.cache\ticianoflix)

REM ─── 5. Script de execução ─────────────────────────────
(
echo @echo off
echo chcp 65001 ^>nul
echo cd /d "%DIR%"
echo "%PYEXE%" server.py
echo pause
) > "%DIR%TicianoFlix.bat"
echo  [OK] Criado %DIR%TicianoFlix.bat
echo       (duplo clique nele para iniciar o servidor)

REM ─── 6. Iniciar junto com o Windows? (opcional) ────────
set /p AUTOSTART="  Iniciar o TicianoFlix junto com o Windows? (s/N): "
if /i "%AUTOSTART%"=="s" (
    schtasks /Create /F /TN "TicianoFlix" /SC ONLOGON /RL LIMITED /TR "\"%DIR%TicianoFlix.bat\""
    if errorlevel 1 (
        echo  [AVISO] Nao consegui criar a tarefa. Rode o instalador como administrador se quiser.
    ) else (
        echo  [OK] Tarefa agendada criada (inicia no login).
    )
)

REM ─── 7. Iniciar agora? ─────────────────────────────────
set /p INICIAR="  Iniciar o TicianoFlix agora? (s/N): "
if /i "%INICIAR%"=="s" (
    start "" cmd /c ""%DIR%TicianoFlix.bat""
)

echo.
echo  ================================================
echo   Instalacao concluida!
echo.
echo   Acesse:  http://localhost:8080
echo   Logs:    %USERPROFILE%\.cache\ticianoflix\
echo   Parar:   feche a janela do servidor
echo   Desativar autostart: schtasks /Delete /TN "TicianoFlix" /F
echo  ================================================
echo.
pause

REM ─── Acesso ao Drive (privilegio minimo) ───────────────
REM O setup-rclone-seguro.sh e um script bash; no Windows orientamos o
REM ajuste manual, que sao os mesmos dois comandos do rclone.
:checar_acesso_drive
set "TF_SCOPE="
for /f "tokens=1,* delims== " %%A in ('rclone config show gdrive 2^>nul ^| findstr /b "scope"') do set "TF_SCOPE=%%B"
set "TF_ROOT="
for /f "tokens=1,* delims== " %%A in ('rclone config show gdrive 2^>nul ^| findstr /b "root_folder_id"') do set "TF_ROOT=%%B"
if /i "%TF_SCOPE%"=="drive.readonly" if not "%TF_ROOT%"=="" (
    echo  [OK] Acesso ao Drive ja esta no minimo
    goto :eof
)
echo.
echo  [AVISO] O remote 'gdrive:' alcanca MAIS do que o TicianoFlix precisa.
echo          Escopo atual: %TF_SCOPE%
echo          Isso permite ler e apagar arquivos em todo o seu Google Drive.
echo.
echo  Para reduzir ao minimo, rode no terminal:
echo.
echo    rclone config update gdrive scope drive.readonly --non-interactive
echo    rclone config reconnect gdrive:
echo.
echo  O segundo comando abre o navegador para reautorizar.
echo  Detalhes na secao "Acesso ao Google Drive" do README.
echo.
goto :eof
