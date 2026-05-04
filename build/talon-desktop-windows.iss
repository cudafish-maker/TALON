#ifndef ArtifactRole
#define ArtifactRole "client"
#endif

#ifndef AppVersion
#define AppVersion "0.1.0"
#endif

#if ArtifactRole == "server"
#define RoleTitle "Server"
#define OppositeRole "client"
#define AppIdValue "TALONDesktopServer"
#define OutputRole "server"
#else
#define RoleTitle "Client"
#define OppositeRole "server"
#define AppIdValue "TALONDesktopClient"
#define OutputRole "client"
#endif

[Setup]
AppId={#AppIdValue}
AppName=T.A.L.O.N. {#RoleTitle}
AppVersion={#AppVersion}
AppPublisher=TALON
AppPublisherURL=https://github.com/
DefaultDirName={autopf}\TALON\Desktop {#RoleTitle}
DefaultGroupName=T.A.L.O.N. {#RoleTitle}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=talon-desktop-{#OutputRole}-windows-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
UsePreviousAppDir=yes
UninstallDisplayIcon={app}\talon-desktop.exe
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\talon-desktop-windows\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\windows-runtime\i2pd\*"; DestDir: "{app}\runtime\i2pd"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\windows-runtime\installers\yggdrasil.msi"; DestDir: "{app}\runtime\installers"; Flags: ignoreversion
Source: "windows\talon-runtime.ps1"; DestDir: "{app}\tools"; Flags: ignoreversion
Source: "..\README-install.md"; DestDir: "{app}"; DestName: "README-install.md"; Flags: ignoreversion

[Icons]
Name: "{group}\T.A.L.O.N. {#RoleTitle}"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; WorkingDir: "{app}"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\tools\talon-runtime.ps1"" -Role {#ArtifactRole} -DataRoot ""{code:GetDataRoot}"" -Launch ""{app}\talon-desktop.exe"""
Name: "{commondesktop}\T.A.L.O.N. {#RoleTitle}"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; WorkingDir: "{app}"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\tools\talon-runtime.ps1"" -Role {#ArtifactRole} -DataRoot ""{code:GetDataRoot}"" -Launch ""{app}\talon-desktop.exe"""; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "msiexec.exe"; Parameters: "/i ""{app}\runtime\installers\yggdrasil.msi"" /qn /norestart"; StatusMsg: "Installing bundled Yggdrasil..."; Flags: runhidden waituntilterminated; Check: ShouldInstallYggdrasil
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\tools\talon-runtime.ps1"" -Role {#ArtifactRole} -DataRoot ""{code:GetDataRoot}"" -Initialize"; StatusMsg: "Creating or updating TALON local configuration..."; Flags: runhidden waituntilterminated

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\tools\talon-runtime.ps1"" -Role {#ArtifactRole} -DataRoot ""{code:GetDataRoot}"" -Stop"; Flags: runhidden waituntilterminated

[Code]
const
  SameRole = '{#ArtifactRole}';
  OppositeRole = '{#OppositeRole}';

function AddPath(Path, Child: string): string;
begin
  Result := AddBackslash(Path) + Child;
end;

function CommandLineContains(Value: string): Boolean;
begin
  Result := Pos(Uppercase(Value), Uppercase(GetCmdTail)) > 0;
end;

function UninstallKeyFor(Role: string): string;
begin
  if Role = 'server' then
    Result := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\TALONDesktopServer_is1'
  else
    Result := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\TALONDesktopClient_is1';
end;

function RoleInstallExists(Role: string): Boolean;
var
  Key: string;
begin
  Key := UninstallKeyFor(Role);
  Result :=
    RegKeyExists(HKCU, Key) or
    RegKeyExists(HKLM, Key) or
    RegKeyExists(HKLM64, Key);
end;

function NewDataRootFor(Role: string): string;
begin
  Result := ExpandConstant('{localappdata}\TALON\desktop-' + Role);
end;

function LegacyDataRootFor(Role: string): string;
begin
  if Role = 'server' then
    Result := AddPath(GetEnv('USERPROFILE'), '.talon-server')
  else
    Result := AddPath(GetEnv('USERPROFILE'), '.talon');
end;

function HasTalonProfile(Path: string): Boolean;
begin
  Result :=
    DirExists(Path) and (
      FileExists(AddPath(Path, 'talon.ini')) or
      FileExists(AddPath(Path, 'talon.db')) or
      DirExists(AddPath(Path, 'reticulum')) or
      DirExists(AddPath(Path, 'documents'))
    );
end;

function ConfigRole(Path: string): string;
var
  ConfigPath: string;
begin
  Result := '';
  ConfigPath := AddPath(Path, 'talon.ini');
  if FileExists(ConfigPath) then
    Result := Lowercase(GetIniString('talon', 'mode', '', ConfigPath));
end;

function ProfileMatchesRole(Path, Role: string): Boolean;
var
  ExistingRole: string;
begin
  if not HasTalonProfile(Path) then begin
    Result := False;
    Exit;
  end;

  ExistingRole := ConfigRole(Path);
  Result := (ExistingRole = '') or (ExistingRole = Role);
end;

function OppositeRoleDetected: Boolean;
begin
  Result :=
    RoleInstallExists(OppositeRole) or
    ProfileMatchesRole(NewDataRootFor(OppositeRole), OppositeRole) or
    ProfileMatchesRole(LegacyDataRootFor(OppositeRole), OppositeRole);
end;

function SameRoleDetected: Boolean;
begin
  Result :=
    RoleInstallExists(SameRole) or
    ProfileMatchesRole(NewDataRootFor(SameRole), SameRole) or
    ProfileMatchesRole(LegacyDataRootFor(SameRole), SameRole);
end;

function FindSameRoleDataRoot: string;
var
  NewRoot: string;
  LegacyRoot: string;
begin
  NewRoot := NewDataRootFor(SameRole);
  LegacyRoot := LegacyDataRootFor(SameRole);

  if ProfileMatchesRole(NewRoot, SameRole) then
    Result := NewRoot
  else if ProfileMatchesRole(LegacyRoot, SameRole) then
    Result := LegacyRoot
  else
    Result := NewRoot;
end;

function GetDataRoot(Param: string): string;
begin
  Result := FindSameRoleDataRoot;
end;

function ShouldInstallYggdrasil: Boolean;
begin
  Result := not CommandLineContains('/SKIPYGGDRASIL');
end;

function InitializeSetup: Boolean;
var
  DataRoot: string;
begin
  Result := True;
  if OppositeRoleDetected then begin
    MsgBox(
      'A TALON ' + OppositeRole + ' install or profile was found. ' +
      'Client and server roles must not be overwritten in place because they ' +
      'contain separate databases, documents, and Reticulum identity material. ' +
      'Uninstall or archive the opposite role before installing this package.',
      mbCriticalError,
      MB_OK
    );
    Result := False;
    Exit;
  end;

  if SameRoleDetected then begin
    DataRoot := FindSameRoleDataRoot;
    Log('TALON same-role upgrade detected. Preserving data root: ' + DataRoot);
  end;
end;
