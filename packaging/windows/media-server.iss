; Instalador do Windows (Inno Setup). Por usuario: nao pede administrador.
; Compilar: iscc /DVersao=1.26.0 /DOrigem=<pasta dist\media-server> /DIcone=<app.ico> media-server.iss
#ifndef Versao
  #define Versao "0.0.0"
#endif
#ifndef Origem
  #define Origem "..\..\dist\media-server"
#endif
#ifndef Icone
  #define Icone "..\..\build\icones\app.ico"
#endif

[Setup]
AppId={{6B1E0C6A-12AA-4C0D-9F6B-120000000001}
AppName=12:00 Media Server
AppVersion={#Versao}
AppPublisher=12:00 Media Server
DefaultDirName={localappdata}\Programs\Media Server
DefaultGroupName=12:00 Media Server
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=Instalador-12-00-Media-Server-{#Versao}-Windows
SetupIconFile={#Icone}
UninstallDisplayIcon={app}\media-server.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "iniciar"; Description: "Iniciar o servidor junto com o Windows"; GroupDescription: "Opções:"
Name: "atalho"; Description: "Criar um atalho na Área de Trabalho"; GroupDescription: "Opções:"

[Files]
Source: "{#Origem}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\12:00 Media Server"; Filename: "{app}\media-server.exe"
Name: "{autodesktop}\12:00 Media Server"; Filename: "{app}\media-server.exe"; Tasks: atalho
; Inicio automatico: o servidor sobe escondido ao entrar no Windows.
Name: "{userstartup}\12:00 Media Server (servidor)"; Filename: "{app}\media-server.exe"; Parameters: "--servidor"; Tasks: iniciar

[Run]
Filename: "{app}\media-server.exe"; Description: "Abrir o 12:00 Media Server agora"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM media-server.exe"; Flags: runhidden; RunOnceId: "ParaServidor"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM rclone.exe"; Flags: runhidden; RunOnceId: "ParaRclone"
