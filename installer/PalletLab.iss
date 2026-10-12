#define AppName "PalletLab"
#define AppVersion GetEnv("APP_VERSION")
#define AppDist GetEnv("APP_DIST")
#define UpdaterDist GetEnv("UPDATER_DIST")

[Setup]
AppId={{E7F2A5C4-9C2B-4D3D-A4A5-1D1B5D824511}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\PalletLab
DefaultGroupName={#AppName}
OutputDir=.
OutputBaseFilename=PalletLab-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayName={#AppName}

[Files]
Source: "{#AppDist}\*"; DestDir: "{app}\App"; Flags: recursesubdirs ignoreversion
Source: "{#UpdaterDist}\*"; DestDir: "{app}\Updater"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\PalletLab"; Filename: "{app}\App\PalletLab.exe"
Name: "{autodesktop}\PalletLab"; Filename: "{app}\App\PalletLab.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; Flags: unchecked

[Run]
Filename: "{app}\App\PalletLab.exe"; Description: "Запустить PalletLab"; Flags: nowait postinstall skipifsilent
