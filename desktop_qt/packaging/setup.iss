; Blastgate desktop installer. Built by build_setup.py:  ISCC /DAppVersion=2.2.0 packaging\setup.iss
;
; Installs for the current user only (no administrator rights), so the app can
; update itself: it downloads the next installer and runs it with /SILENT.
; Settings and logs live in %APPDATA%\Blastgate and are never touched here.
#ifndef AppVersion
  #error AppVersion is not defined (pass /DAppVersion=x.y.z)
#endif

[Setup]
AppId={{6E0B3C52-8F1D-4C6A-9B7E-2A54D1F0C3B8}
AppName=Blastgate
AppVersion={#AppVersion}
AppPublisher=Blastgate
PrivilegesRequired=lowest
DefaultDirName={autopf}\Blastgate
DefaultGroupName=Blastgate
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir=..\dist\installer
OutputBaseFilename=Blastgate-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
MinVersion=10.0.17763
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=blastgate.ico
UninstallDisplayIcon={app}\Blastgate.exe
; The running app is closed before its files are replaced (it also exits by itself)
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Prečica na radnoj površini"; GroupDescription: "Prečice:"

[InstallDelete]
; Files of the previous version that the new one no longer has must not stay behind
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Blastgate\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Blastgate"; Filename: "{app}\Blastgate.exe"
Name: "{autodesktop}\Blastgate"; Filename: "{app}\Blastgate.exe"; Tasks: desktopicon

[Run]
; Normal install: offer to start the app on the last page
Filename: "{app}\Blastgate.exe"; Description: "Pokreni Blastgate"; Flags: nowait postinstall skipifsilent
; Update started by the app itself (/SILENT): start the new version again
Filename: "{app}\Blastgate.exe"; Flags: nowait; Check: WizardSilent
