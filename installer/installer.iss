; installer.iss -- PhoneSpeaker (PC) single-file Windows installer (todo010-1).
;
; Bundles the PyInstaller onedir output (pc\dist\PhoneSpeaker\) plus a
; redistributed copy of adb (installer\resources\adb\, Apache-2.0, see
; THIRD_PARTY_NOTICES.md) into one setup.exe. One UAC prompt installs
; everything; no separate driver install (WiFi/U1/U2 need no drivers --
; U3/WinUSB was dropped, see SPEC3 §17).
;
; Build order: run pc\build.bat first (produces pc\dist\PhoneSpeaker\),
; make sure installer\resources\adb\ has adb.exe + the two DLLs (copy from
; your local Android SDK platform-tools -- see THIRD_PARTY_NOTICES.md),
; then compile this script with Inno Setup (ISCC.exe installer.iss or open
; in the Inno Setup IDE and press Compile). Output goes to installer\Output\.
;
; NOTE: keep this file ASCII-only -- see pc\build.bat for why (cmd.exe /
; installer tooling can mis-tokenize non-ASCII text in some codepages).

#define MyAppName "PhoneSpeaker"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "PhoneSpeaker (open source)"
#define MyAppURL "https://github.com/"
#define MyAppExeName "PhoneSpeaker.exe"
#define MyTcpPort "58482"

[Setup]
AppId={{B6C9C6C0-6E6A-4E7A-9C1E-6B6E6F6E6473}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=Output
OutputBaseFilename=PhoneSpeaker-Setup-v{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Not code-signed: this is a self-use / open-source project, see SPEC3 §11
; and §15 (decided against paying for EV/standard code signing certs).
; README documents the expected Windows SmartScreen prompt and how to
; proceed past it.
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Whole onedir payload (exe + _internal\ dependencies) from PyInstaller.
Source: "..\pc\dist\PhoneSpeaker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Bundled adb (Apache-2.0, redistribution allowed -- see THIRD_PARTY_NOTICES.md).
; usb_adb.py's _find_adb_executable() looks for exactly <app dir>\adb\adb.exe
; first, falling back to PATH if this folder is absent (dev-mode behaviour).
Source: "resources\adb\*"; DestDir: "{app}\adb"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
; Pre-approve the TCP port used for WiFi/U1/U2 streaming so users aren't
; interrupted by a Windows Firewall prompt on first run. Best-effort: if
; this fails for any reason, Windows will just show its normal first-run
; firewall prompt instead (documented in README as a fallback).
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""PhoneSpeaker (TCP {#MyTcpPort})"" dir=in action=allow protocol=TCP localport={#MyTcpPort} program=""{app}\{#MyAppExeName}"""; Flags: runhidden; StatusMsg: "Configuring Windows Firewall..."
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""PhoneSpeaker (TCP {#MyTcpPort})"""; Flags: runhidden; RunOnceId: "RemoveFirewallRule"
