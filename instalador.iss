; Compilar com Inno Setup 6:  ISCC.exe instalador.iss   (depois de gerar dist\SniperOferta com o PyInstaller)
#define Nome "Sniper Oferta"
#define Versao "1.0.1"

[Setup]
AppId={{B7E3A1D2-5C4F-4E8A-9B61-2F0D7A93C511}
AppName={#Nome}
AppVersion={#Versao}
AppPublisher=Sniper Oferta
DefaultDirName={autopf}\{#Nome}
DefaultGroupName={#Nome}
OutputDir=Instalador
OutputBaseFilename=SniperOferta-Setup-{#Versao}
SetupIconFile=assets\icone.ico
UninstallDisplayIcon={app}\SniperOferta.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktop"; Description: "Criar atalho na área de trabalho"; Flags: unchecked

[Files]
Source: "dist\SniperOferta\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "LEIA-ME-CLIENTE.txt"; DestDir: "{app}"; Flags: isreadme

[Icons]
Name: "{group}\{#Nome}"; Filename: "{app}\SniperOferta.exe"
Name: "{group}\Desinstalar {#Nome}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#Nome}"; Filename: "{app}\SniperOferta.exe"; Tasks: desktop

[Run]
Filename: "{app}\SniperOferta.exe"; Description: "Abrir o {#Nome}"; Flags: nowait postinstall skipifsilent

; Os dados do cliente (config, banco, log) ficam em %APPDATA%\SniperOferta e NÃO são apagados ao desinstalar.
