; Inno Setup script: turns the built app folder into Arckad-D-Setup-<version>.exe
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Arckad-D"
#define AppExe "Arckad-D.exe"

[Setup]
AppId={{4C66898C-A3FB-47DB-8F8A-04F54DD27755}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Arckad-D
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\installer-output
OutputBaseFilename=Arckad-D-Setup-{#AppVersion}
SetupIconFile=arckad-d.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force

[InstallDelete]
; clear the previous version's program files first, so old and new Python files never mix
Type: filesandordirs; Name: "{app}\_internal"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Arckad-D\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; after a silent update started from inside Arckad-D, open it again (not during the automatic build test)
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: ShouldRelaunch

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden; RunOnceId: "StopArckadD"
Filename: "{sys}\reg.exe"; Parameters: "delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v ""Arckad-D AutoSort"" /f"; Flags: runhidden; RunOnceId: "RemoveAutoSort"

[Code]
var
  InstallFinished: Boolean;

function HasParam(const Name: String): Boolean;
var
  i: Integer;
begin
  Result := False;
  for i := 1 to ParamCount do
    if CompareText(ParamStr(i), Name) = 0 then
      Result := True;
end;

function ShouldRelaunch(): Boolean;
begin
  Result := WizardSilent and not HasParam('/NOLAUNCH');
end;

{ An update started from inside Arckad-D: wait (up to 60 s) until that Arckad-D has fully closed,
  so none of its files are still in use. Arckad-D holds this named mutex while it runs. }
function InitializeSetup(): Boolean;
var
  waited: Integer;
begin
  waited := 0;
  while CheckForMutexes('ArckadD-Running') and (waited < 240) do
  begin
    Sleep(250);
    waited := waited + 1;
  end;
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssDone then
    InstallFinished := True;
end;

{ If a silent update didn't finish, reopen the installed Arckad-D so it can say what happened. }
procedure DeinitializeSetup();
var
  code: Integer;
  exe: String;
begin
  if WizardSilent and (not InstallFinished) and (not HasParam('/NOLAUNCH')) then
  begin
    exe := ExpandConstant('{autopf}') + '\Arckad-D\Arckad-D.exe';
    if not FileExists(exe) then
      exe := ExpandConstant('{localappdata}') + '\Programs\Arckad-D\Arckad-D.exe';
    if FileExists(exe) then
      Exec(exe, '--update-failed 4', '', SW_SHOWNORMAL, ewNoWait, code);
  end;
end;
