; ===========================================================================
; V-Scanner 3.0 Windows installer (Stage 14 — ARCHITECTURE_DECISIONS T-05).
;
; Compile via packaging_windows/build_windows.py ONLY, which supplies:
;   /DVSCANNER_VERSION=<pyproject version, verbatim (prerelease suffix kept)>
;   /DVSCANNER_RESOURCE_VERSION=<numeric derivation from the pyproject version>
;   /DVSCANNER_STAGE_DIR=<validated Nuitka standalone distribution directory>
;   /DVSCANNER_OUT_DIR=<directory that receives the compiled installer>
;   /DVSCANNER_REPO_ROOT=<repository root (icon asset path)>
; Define names carry the VSCANNER_ prefix on purpose: /DPRODUCT_VERSION was
; root-caused during Stage 14 to collide with an ISPP-built-in name (the
; expansion silently rendered "ProductVersion", which ISCC then rejected as
; an invalid VersionInfoVersion value) — plain VSCANNER_* names verify clean.
;
; Version strings are never edited here: pyproject.toml is the single
; version source; this script refuses to compile without the defines.
;
; Semantics implemented here:
;   * per-user install, no administrator rights (PrivilegesRequired=lowest);
;   * Start-menu shortcut always, desktop shortcut as an optional task;
;   * standard non-destructive upgrade keyed to the stable AppId;
;   * uninstall removes the application files and shortcuts but RETAINS
;     user data by default; deleting user data is a separate explicit
;     question (default = keep, per stage brief §8);
;   * never launches device operations, never modifies the registry beyond
;     uninstall metadata, downloads nothing, embeds nothing machine-local.
; ===========================================================================

#ifndef VSCANNER_VERSION
  #error "VSCANNER_VERSION not defined: compile through packaging_windows/build_windows.py (/DVSCANNER_VERSION=...)"
#endif
#ifndef VSCANNER_RESOURCE_VERSION
  #error "VSCANNER_RESOURCE_VERSION not defined: compile through packaging_windows/build_windows.py (/DVSCANNER_RESOURCE_VERSION=...)"
#endif
#ifndef VSCANNER_STAGE_DIR
  #error "VSCANNER_STAGE_DIR not defined: compile through packaging_windows/build_windows.py (/DVSCANNER_STAGE_DIR=...)"
#endif
#ifndef VSCANNER_OUT_DIR
  #error "VSCANNER_OUT_DIR not defined: compile through packaging_windows/build_windows.py (/DVSCANNER_OUT_DIR=...)"
#endif
#ifndef VSCANNER_REPO_ROOT
  #error "VSCANNER_REPO_ROOT not defined: compile through packaging_windows/build_windows.py (/DVSCANNER_REPO_ROOT=...)"
#endif

[Setup]
AppId={{1AB0A622-DB19-4B71-88B9-1988011A281A}
AppName=V-Scanner
AppVersion={#VSCANNER_VERSION}
AppVerName=V-Scanner {#VSCANNER_VERSION}
VersionInfoVersion={#VSCANNER_RESOURCE_VERSION}
VersionInfoProductName=V-Scanner
VersionInfoProductVersion={#VSCANNER_RESOURCE_VERSION}
AppPublisher=ToTheBlankWorld
AppPublisherURL=https://github.com/ToTheBlankWorld/V-Scanner
AppSupportURL=https://github.com/ToTheBlankWorld/V-Scanner
AppUpdatesURL=https://github.com/ToTheBlankWorld/V-Scanner
DefaultDirName={localappdata}\Programs\V-Scanner
DefaultGroupName=V-Scanner
DisableProgramGroupPage=yes
UninstallDisplayName=V-Scanner
UninstallDisplayIcon={app}\V-Scanner.exe
PrivilegesRequired=lowest
OutputDir={#VSCANNER_OUT_DIR}
OutputBaseFilename=V-Scanner-{#VSCANNER_VERSION}-Setup
SetupIconFile={#VSCANNER_REPO_ROOT}\packaging_windows\assets\vscanner.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ChangesEnvironment=no
ChangesAssociations=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#VSCANNER_STAGE_DIR}\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\V-Scanner"; Filename: "{app}\V-Scanner.exe"; \
    WorkingDir: "{app}"
Name: "{group}\Uninstall V-Scanner"; Filename: "{uninstallexe}"
Name: "{autodesktop}\V-Scanner"; Filename: "{app}\V-Scanner.exe"; \
    WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\V-Scanner.exe"; \
    Description: "Launch V-Scanner"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Intentionally empty: the uninstaller removes only {app} and shortcuts.
; User data lives under %LOCALAPPDATA%\vscanner (A-07) and is retained.

[Code]
{ ----------------------------------------------------------------------
  Optional, explicit user-data cleanup at uninstall — default RETAIN.
  Only the %LOCALAPPDATA%\vscanner tree is considered (settings, logs,
  history, cached tool components). Reports live wherever the user chose
  (default Documents\vScanner\reports) and are NEVER touched by install
  or uninstall logic.
  ---------------------------------------------------------------------- }

const
  UninstallDataPrompt =
    'Also delete your V-Scanner user data (settings, logs, history and ' +
    'cached tool components) from the folder used for application data?' + #13#10 + #13#10 +
    'Your scan reports stay wherever you saved them and are not affected.' + #13#10 + #13#10 +
    'Default: keep user data. Choose "No" to retain it.';

{ Runtime support function documented at
  https://jrsoftware.org/ishelp/index.php?topic=isfunc_uninstallsilent —
  also asserted by the ISS contract tests. }

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: string;
begin
  if CurUninstallStep <> usUninstall then
    Exit;
  { Inno shows [Code] MsgBox dialogs even in silent uninstall runs; without
    this guard a /VERYSILENT /UNINSTALL smoke hangs on the hidden prompt.
    Silent uninstalls therefore take the safe default and RETAIN data. }
  if UninstallSilent() then
  begin
    Log('Silent uninstall: user-data question skipped, user data retained.');
    Exit;
  end;
  DataDir := ExpandConstant('{localappdata}\vscanner');
  if not DirExists(DataDir) then
    Exit;
  if MsgBox(UninstallDataPrompt, mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
  begin
    if DelTree(DataDir, True, True, True) then
      Log('User data deleted: ' + DataDir)
    else
      Log('Could not fully delete user data: ' + DataDir);
  end;
end;
