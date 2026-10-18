# ============================================================
#  TicianoFlix — Instalador visual para Windows
#
#  Assistente gráfico (WinForms) que verifica pré-requisitos,
#  instala o app e deixa ele rodando. Não precisa de PowerShell
#  7 nem de nada além do que já vem no Windows.
#
#  Para executar: duplo clique no "Instalador-TicianoFlix-Windows.bat"
#  (ou botão direito no .ps1 > Executar com PowerShell).
# ============================================================
#requires -version 5.1

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$Script:REPO = 'ticianocorral/TicianoFlix'
$Script:REF = 'main'
$Script:PORTA = 9187
# Pasta do instalador: se server.py estiver ao lado, é um clone/baixado —
# usa esses arquivos; senão baixa o projeto do GitHub.
$Script:PastaScript = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script:DirInstalacao = $Script:PastaScript
$Script:TemProjetoLocal = Test-Path (Join-Path $Script:PastaScript 'server.py')
$Script:QueroAutostart = $true
$Script:QueroAbrir = $true

# ── Helpers ──────────────────────────────────────────────────

function Write-Log {
    param([string]$Texto, [string]$Cor = 'LightGray')
    $txtLog.SelectionStart = $txtLog.TextLength
    $txtLog.SelectionColor = [System.Drawing.Color]::FromName($Cor)
    $txtLog.AppendText("$Texto`r`n")
    $txtLog.SelectionColor = [System.Drawing.Color]::LightGray
    $txtLog.ScrollToCaret()
    $form.Refresh()
    [System.Windows.Forms.Application]::DoEvents()
}

function Find-Python {
    foreach ($cmd in @('python', 'py')) {
        try {
            $v = & $cmd --version 2>$null
            if ($v -match 'Python 3\.(\d+)') {
                if ([int]$Matches[1] -ge 9) { return $cmd }
            }
        } catch { }
    }
    return $null
}

function Find-Rclone {
    try {
        $v = & rclone version 2>$null
        if ($v -match '^rclone') { return $true }
    } catch { }
    return $false
}

# ── Passos de instalação ─────────────────────────────────────

function Install-Python {
    Write-Log 'Python 3.9+ não encontrado. Instalando...' 'Khaki'
    $instalou = $false
    try {
        winget --version 2>$null | Out-Null
        Write-Log '  via winget (Python.Python.3.12)...'
        winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements | Out-Null
        $instalou = $true
    } catch {
        Write-Log '  winget indisponível — baixando o instalador oficial...' 'Khaki'
        $url = 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe'
        $exe = Join-Path $env:TEMP 'python-installer.exe'
        Invoke-WebRequest -Uri $url -OutFile $exe -UseBasicParsing
        Start-Process -FilePath $exe -ArgumentList '/quiet InstallAllUsers=0 PrependPath=1' -Wait
        $instalou = $true
    }
    # PATH desta sessão precisa ser recarregado após a instalação
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not (Find-Python)) { throw 'Python não ficou disponível após a instalação.' }
}

function Install-Rclone {
    Write-Log 'rclone não encontrado. Instalando...' 'Khaki'
    try {
        winget --version 2>$null | Out-Null
        winget install -e --id Rclone.Rclone --accept-source-agreements --accept-package-agreements | Out-Null
    } catch {
        Write-Log '  baixando o rclone oficial...' 'Khaki'
        $zip = Join-Path $env:TEMP 'rclone.zip'
        Invoke-WebRequest -Uri 'https://downloads.rclone.org/rclone-current-windows-amd64.zip' -OutFile $zip -UseBasicParsing
        $dest = Join-Path $env:LOCALAPPDATA 'rclone'
        Expand-Archive -Force $zip $dest
        $dir = Get-ChildItem $dest -Directory | Where-Object Name -like 'rclone-*' | Select-Object -First 1
        setx PATH "$env:Path;$($dir.FullName)" | Out-Null
        $env:Path = "$env:Path;$($dir.FullName)"
    }
    if (-not (Find-Rclone)) { throw 'rclone não ficou disponível após a instalação.' }
}

function Get-Projeto {
    if ($Script:TemProjetoLocal) {
        Write-Log "Usando os arquivos locais: $Script:PastaScript"
        return
    }
    $dest = Join-Path $env:USERPROFILE 'TicianoFlix'
    Write-Log "Baixando o TicianoFlix ($($Script:REPO)@$($Script:REF)) para $dest..."
    $zip = Join-Path $env:TEMP 'ticianoflix.zip'
    Invoke-WebRequest -Uri "https://github.com/$($Script:REPO)/archive/refs/heads/$($Script:REF).zip" -OutFile $zip -UseBasicParsing
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Expand-Archive -Force $zip $env:TEMP
    $extraido = Get-ChildItem $env:TEMP -Directory | Where-Object Name -like 'TicianoFlix-*' |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    Move-Item $extraido.FullName $dest
    $Script:DirInstalacao = $dest
}

function Install-App {
    if (-not (Find-Python)) { Install-Python }
    else { Write-Log ('✓ Python encontrado: ' + (& (Find-Python) --version)) 'LightGreen' }
    if (-not (Find-Rclone)) { Install-Rclone }
    else { Write-Log '✓ rclone encontrado' 'LightGreen' }

    Get-Projeto
    $Script:TemProjetoLocal = $true

    # Diretórios de cache
    New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.cache\ticianoflix\images" | Out-Null
    New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.cache\ticianoflix\subs" | Out-Null
    New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.cache\rclone" | Out-Null
    Write-Log '✓ Diretórios de cache prontos' 'LightGreen'

    # Script de execução
    $bat = Join-Path $Script:DirInstalacao 'TicianoFlix.bat'
    "@echo off`r`nchcp 65001 >nul`r`ncd /d `"$($Script:DirInstalacao)`"`r`n`"$((Find-Python))`" server.py`r`npause" |
        Set-Content -Path $bat -Encoding UTF8
    Write-Log "✓ Criado $bat" 'LightGreen'

    # Autostart (opcional)
    if ($Script:QueroAutostart) {
        try {
            schtasks /Create /F /TN 'TicianoFlix' /SC ONLOGON /RL LIMITED /TR "`"$bat`"" | Out-Null
            Write-Log '✓ Tarefa agendada criada (inicia no login)' 'LightGreen'
        } catch {
            Write-Log '⚠ Não consegui criar a tarefa agendada (rode como administrador se quiser)' 'Khaki'
        }
    }
}

# ── Interface ────────────────────────────────────────────────

$form = New-Object System.Windows.Forms.Form
$form.Text = 'TicianoFlix — Instalador'
$form.Size = New-Object System.Drawing.Size(620, 480)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.BackColor = [System.Drawing.Color]::FromArgb(18, 18, 22)
$form.Font = New-Object System.Drawing.Font('Segoe UI', 9.5)

$lbTitulo = New-Object System.Windows.Forms.Label
$lbTitulo.Text = '🎬 TicianoFlix'
$lbTitulo.Font = New-Object System.Drawing.Font('Segoe UI', 22, [System.Drawing.FontStyle]::Bold)
$lbTitulo.ForeColor = [System.Drawing.Color]::FromArgb(229, 9, 20)
$lbTitulo.Location = New-Object System.Drawing.Point(24, 18)
$lbTitulo.Size = New-Object System.Drawing.Size(400, 44)
$form.Controls.Add($lbTitulo)

$lbSub = New-Object System.Windows.Forms.Label
$lbSub.Text = 'Seus filmes com cara de Netflix — self-hosted, leve, instantâneo.'
$lbSub.ForeColor = [System.Drawing.Color]::Gainsboro
$lbSub.Location = New-Object System.Drawing.Point(26, 62)
$lbSub.Size = New-Object System.Drawing.Size(540, 22)
$form.Controls.Add($lbSub)

# Painel 1: opções
$pnOpcoes = New-Object System.Windows.Forms.Panel
$pnOpcoes.Location = New-Object System.Drawing.Point(24, 100)
$pnOpcoes.Size = New-Object System.Drawing.Size(556, 250)
$form.Controls.Add($pnOpcoes)

$chkAutostart = New-Object System.Windows.Forms.CheckBox
$chkAutostart.Text = 'Iniciar o TicianoFlix junto com o Windows'
$chkAutostart.Checked = $true
$chkAutostart.ForeColor = [System.Drawing.Color]::Gainsboro
$chkAutostart.Location = New-Object System.Drawing.Point(4, 10)
$chkAutostart.Size = New-Object System.Drawing.Size(540, 24)
$pnOpcoes.Controls.Add($chkAutostart)

$chkAbrir = New-Object System.Windows.Forms.CheckBox
$chkAbrir.Text = 'Abrir o TicianoFlix no navegador ao terminar'
$chkAbrir.Checked = $true
$chkAbrir.ForeColor = [System.Drawing.Color]::Gainsboro
$chkAbrir.Location = New-Object System.Drawing.Point(4, 40)
$chkAbrir.Size = New-Object System.Drawing.Size(540, 24)
$pnOpcoes.Controls.Add($chkAbrir)

$lbDestino = New-Object System.Windows.Forms.Label
$lbDestino.Text = if ($Script:TemProjetoLocal) {
    "Instalando a partir de: $($Script:PastaScript)"
} else {
    "Será instalado em: $env:USERPROFILE\TicianoFlix"
}
$lbDestino.ForeColor = [System.Drawing.Color]::Silver
$lbDestino.Location = New-Object System.Drawing.Point(4, 80)
$lbDestino.Size = New-Object System.Drawing.Size(540, 40)
$pnOpcoes.Controls.Add($lbDestino)

$lbNota = New-Object System.Windows.Forms.Label
$lbNota.Text = "O assistente verifica e instala o Python e o rclone sozinho.`r`nNada é instalado fora do seu usuário sem avisar."
$lbNota.ForeColor = [System.Drawing.Color]::DarkGray
$lbNota.Location = New-Object System.Drawing.Point(4, 130)
$lbNota.Size = New-Object System.Drawing.Size(540, 60)
$pnOpcoes.Controls.Add($lbNota)

# Painel 2: progresso
$pnProgress = New-Object System.Windows.Forms.Panel
$pnProgress.Location = New-Object System.Drawing.Point(24, 100)
$pnProgress.Size = New-Object System.Drawing.Size(556, 250)
$pnProgress.Visible = $false
$form.Controls.Add($pnProgress)

$txtLog = New-Object System.Windows.Forms.TextBox
$txtLog.Multiline = $true
$txtLog.ReadOnly = $true
$txtLog.ScrollBars = 'Vertical'
$txtLog.BackColor = [System.Drawing.Color]::FromArgb(10, 10, 12)
$txtLog.ForeColor = [System.Drawing.Color]::LightGray
$txtLog.Font = New-Object System.Drawing.Font('Consolas', 9)
$txtLog.Location = New-Object System.Drawing.Point(4, 10)
$txtLog.Size = New-Object System.Drawing.Size(544, 230)
$pnProgress.Controls.Add($txtLog)

# Botões
$btnInstalar = New-Object System.Windows.Forms.Button
$btnInstalar.Text = 'Instalar'
$btnInstalar.BackColor = [System.Drawing.Color]::FromArgb(229, 9, 20)
$btnInstalar.ForeColor = [System.Drawing.Color]::White
$btnInstalar.FlatStyle = 'Flat'
$btnInstalar.Location = New-Object System.Drawing.Point(436, 385)
$btnInstalar.Size = New-Object System.Drawing.Size(144, 38)
$form.Controls.Add($btnInstalar)

$chkAutostart.Add_CheckedChanged({ $Script:QueroAutostart = $chkAutostart.Checked })
$chkAbrir.Add_CheckedChanged({ $Script:QueroAbrir = $chkAbrir.Checked })

$Script:Instalado = $false

$btnInstalar.Add_Click({
    # Um handler só, com dois papéis: antes da instalação ele instala;
    # depois, vira o botão de abrir o app.
    if ($Script:Instalado) {
        Start-Process (Join-Path $Script:DirInstalacao 'TicianoFlix.bat')
        if ($Script:QueroAbrir) {
            Start-Sleep -Seconds 3
            Start-Process "http://localhost:$($Script:PORTA)"
        }
        $form.Close()
        return
    }

    $btnInstalar.Enabled = $false
    $chkAutostart.Enabled = $false
    $chkAbrir.Enabled = $false
    $Script:QueroAutostart = $chkAutostart.Checked
    $Script:QueroAbrir = $chkAbrir.Checked
    $pnOpcoes.Visible = $false
    $pnProgress.Visible = $true
    $form.Refresh()
    try {
        Install-App
        Write-Log ''
        Write-Log '✅ Instalação concluída!' 'LightGreen'
        Write-Log 'Abra http://localhost:9187 — o código de instalação'
        Write-Log 'aparece na janela do servidor (TicianoFlix.bat).'
        $Script:Instalado = $true
        $btnInstalar.Text = 'Abrir TicianoFlix'
        $btnInstalar.Enabled = $true
    } catch {
        Write-Log ''
        Write-Log ("❌ Erro: " + $_.Exception.Message) 'Tomato'
        Write-Log 'Corrija e rode o instalador de novo.' 'Khaki'
        $btnInstalar.Text = 'Tentar de novo'
        $btnInstalar.Enabled = $true
    }
})

[void]$form.ShowDialog()
