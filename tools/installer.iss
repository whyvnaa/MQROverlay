; Inno Setup script for the MQ Overlay installer: installs the PyInstaller folder (dist/mq-overlay) per user, no
; administrator needed, with a Start menu entry, an optional desktop icon and an uninstaller.
; Built by tools/build_exe.py --installer (ISCC.exe; GitHub's Windows runners have Inno Setup 6).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\mq-overlay"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef IconFile
  #define IconFile "..\build\icon.ico"
#endif

[Setup]
AppId={{3127B957-C01B-46DD-8258-EEBBF7186A2B}
AppName=MQ Overlay
AppVersion={#AppVersion}
AppPublisher=whyvnaa
AppPublisherURL=https://github.com/whyvnaa/MQROverlay
DefaultDirName={localappdata}\Programs\MQ Overlay
DefaultGroupName=MQ Overlay
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=mq-overlay-{#AppVersion}-setup
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\mq-overlay.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\MQ Overlay"; Filename: "{app}\mq-overlay.exe"
Name: "{group}\Uninstall MQ Overlay"; Filename: "{uninstallexe}"
Name: "{autodesktop}\MQ Overlay"; Filename: "{app}\mq-overlay.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\mq-overlay.exe"; Description: "Start MQ Overlay"; Flags: nowait postinstall skipifsilent
