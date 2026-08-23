#ifndef SourceDir
  #define SourceDir "releases\\_installer-stage"
#endif
#ifndef OutputDir
  #define OutputDir "releases"
#endif
#ifndef OutputBaseName
  #define OutputBaseName "myknow-Setup"
#endif

#define MyAppName "myknow"
#define MyAppVersion "0.1.1"
#define MyAppPublisher "myknow"
#define MyAppExeName "myknow.exe"

[Setup]
AppId={{B8D5B950-1F0B-4E04-9E52-7F5DB7E9AE61}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\myknow
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=no
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
; Keep the installer icon in the source tree so compilation does not depend on
; Inno Setup's working-directory resolution for the temporary staging folder.
SetupIconFile=..\packaging\assets\myknow.ico
SetupLogging=yes

[Files]
Source: "{#SourceDir}\myknow\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceDir}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\INSTALL_BROWSER_EXTENSION.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\myknow"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0
Name: "{autodesktop}\myknow"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; IconIndex: 0
