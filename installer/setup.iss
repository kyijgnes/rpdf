; PDF 앱 설치 프로그램(Inno Setup 6). **make_setup.py 로 만든다**(GitHub Actions 가 부름).
; 이름·버전·경로는 make_setup.py 가 옆에 적는 defs.iss 에서 온다(이름은 app/appinfo.py 한 곳이라 여기에 박지 않는다).
; 바꾸지 않는 열쇠(AppGuid)와 이름들(ProgId·RegKey·AppMutex, 옛 이름 Old*·LegacyId)은 make_setup.py 머리에 있다.
;
; 하는 일: %LOCALAPPDATA%\Programs\<APP_ID> 에 관리자 권한 없이 설치, 시작 메뉴·바탕화면 바로 가기,
; .pdf 「연결 프로그램」 등록(기본 앱은 사람이 윈도우 설정에서 고른다), 설정 > 앱 의 제거.
; 같은 AppGuid 라 새 setup 을 덮어 설치하면 업그레이드가 되고, 설정(%APPDATA%)은 건드리지 않는다.
; 앱 안 업데이트는 /VERYSILENT /RELAUNCH 로 띄운다: 앱이 꺼지길 기다렸다 덮어쓰고 --after-update 로 다시 켠다.

#include "defs.iss"

#define AppExe AppIdName + ".exe"
#define UninstKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\{" + AppGuid + "}_is1"

[Setup]
AppId={{{#AppGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#Org}
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} 설치
DefaultDirName={autopf}\{#AppIdName}
UsePreviousAppDir=no
PrivilegesRequired=lowest
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableWelcomePage=yes
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBase}
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=4
WizardStyle=modern
#ifdef AppIcon
SetupIconFile={#AppIcon}
#endif
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
CloseApplications=no
RestartApplications=no
ChangesAssociations=yes
ShowLanguageDialog=no
SetupMutex={#AppMutex}.Setup
; %TEMP%\Setup Log <날짜> #<번호>.txt (앱 안 업데이트는 %LOCALAPPDATA%\Temp\<AppIdName>-update\setup.log)
SetupLogging=yes

[Languages]
Name: "ko"; MessagesFile: "compiler:Languages\Korean.isl"

[InstallDelete]
; 옛 버전 찌꺼기(빠진 라이브러리)가 남지 않게 통째로 갈아 끼운다
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Check: WantDesktopIcon

[Registry]
; .pdf 「연결 프로그램」. 기본 앱(UserChoice)은 윈도우가 막아 두어 사람이 설정 > 기본 앱 에서 고른다
Root: HKCU; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; ValueName: ""; ValueData: "PDF 문서"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "PDF 문서 ({#AppName})"
Root: HKCU; Subkey: "Software\Classes\{#ProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"",0"
Root: HKCU; Subkey: "Software\Classes\{#ProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
; 탐색기 「연결 프로그램」 목록이 이 ProgID 에 붙일 이름·아이콘(없으면 exe 버전 정보를 찾다 못 찾아 목록에서 빠진다, 10-20)
Root: HKCU; Subkey: "Software\Classes\{#ProgId}\Application"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"
Root: HKCU; Subkey: "Software\Classes\{#ProgId}\Application"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: """{app}\{#AppExe}"",0"
Root: HKCU; Subkey: "Software\Classes\{#ProgId}\Application"; ValueType: string; ValueName: "ApplicationCompany"; ValueData: "{#Org}"
Root: HKCU; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "{#ProgId}"; ValueData: ""; Flags: uninsdeletevalue
; 옛 이름 ProgID 는 지우지 않고 새 exe 를 가리키게 둔다. 사람이 고른 기본 앱(UserChoice·UserChoiceLatest)이 옛 이름을 붙들고 있어
; 지우면 두 번 눌러도 안 열리고 앱 선택 창만 되풀이된다(10-29 이 PC). 연결 목록(OpenWithProgids)에는 안 넣어 두 줄로 뜨지 않게
Root: HKCU; Subkey: "Software\Classes\{#OldProgId}"; ValueType: string; ValueName: ""; ValueData: "PDF 문서"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\{#OldProgId}"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "PDF 문서 ({#AppName})"
Root: HKCU; Subkey: "Software\Classes\{#OldProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"",0"
Root: HKCU; Subkey: "Software\Classes\{#OldProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\{#OldProgId}\Application"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"
Root: HKCU; Subkey: "Software\Classes\{#OldProgId}\Application"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: """{app}\{#AppExe}"",0"
Root: HKCU; Subkey: "Software\Classes\{#OldProgId}\Application"; ValueType: string; ValueName: "ApplicationCompany"; ValueData: "{#Org}"
Root: HKCU; Subkey: "Software\Classes\{#Old2ProgId}"; ValueType: string; ValueName: ""; ValueData: "PDF 문서"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\{#Old2ProgId}"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "PDF 문서 ({#AppName})"
Root: HKCU; Subkey: "Software\Classes\{#Old2ProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"",0"
Root: HKCU; Subkey: "Software\Classes\{#Old2ProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\{#Old2ProgId}\Application"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"
Root: HKCU; Subkey: "Software\Classes\{#Old2ProgId}\Application"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: """{app}\{#AppExe}"",0"
Root: HKCU; Subkey: "Software\Classes\{#Old2ProgId}\Application"; ValueType: string; ValueName: "ApplicationCompany"; ValueData: "{#Org}"
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
; 설정 > 기본 앱 목록에 이름이 뜨게
Root: HKCU; Subkey: "{#RegKey}\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "{#RegKey}\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "PDF 보기·편집·변환"
Root: HKCU; Subkey: "{#RegKey}\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "{#ProgId}"
Root: HKCU; Subkey: "{#RegKey}"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "{#RegKeyParent}"; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#RegAppName}"; ValueData: "{#RegKey}\Capabilities"; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "{#AppName} 실행"; Flags: nowait postinstall skipifsilent
; 앱 안 업데이트(/RELAUNCH)면 끝나고 다시 켠다. 앱이 그 전에 열려 있던 문서를 다시 연다
Filename: "{app}\{#AppExe}"; Parameters: "--after-update"; Flags: nowait; Check: Relaunch

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
var
  PrevDir: String;       // 이미 깔린 자리(없으면 빈 글자)
  WantDesktop: Boolean;  // 바탕화면 바로 가기를 (다시) 만들까

function HasParam(const Name: String): Boolean;
var
  i: Integer;
begin
  Result := False;
  for i := 1 to ParamCount do
    if CompareText(ParamStr(i), Name) = 0 then
    begin
      Result := True;
      Exit;
    end;
end;

function Relaunch(): Boolean;
begin
  Result := HasParam('/RELAUNCH');
end;

function WantDesktopIcon(): Boolean;
begin
  Result := WantDesktop;
end;

function NextNum(var S: String): Integer;
var
  P: Integer;
begin
  P := Pos('.', S);
  if P = 0 then
  begin
    Result := StrToIntDef(S, 0);
    S := '';
  end
  else
  begin
    Result := StrToIntDef(Copy(S, 1, P - 1), 0);
    Delete(S, 1, P);
  end;
end;

// 버전 대조: A 가 크면 1, 같으면 0, 작으면 -1 (세 자리)
function CompareVer(A, B: String): Integer;
var
  i, X, Y: Integer;
begin
  Result := 0;
  for i := 1 to 3 do
  begin
    X := NextNum(A);
    Y := NextNum(B);
    if X > Y then
    begin
      Result := 1;
      Exit;
    end;
    if X < Y then
    begin
      Result := -1;
      Exit;
    end;
  end;
end;

// 앱이 켜져 있으면 닫으라고 한다. 업데이트로 띄워졌으면 앱이 막 꺼지는 중이니 먼저 20초까지 기다린다
function AppClosed(Waiting: Boolean): Boolean;
var
  i: Integer;
begin
  if Waiting then
    for i := 1 to 40 do
    begin
      if not CheckForMutexes('{#AppMutex},{#OldMutex}') then
        Break;
      Sleep(500);
    end;
  while CheckForMutexes('{#AppMutex},{#OldMutex}') do
    if MsgBox('{#AppName} 창이 켜져 있습니다.' + #13#10 + '문서를 저장하고 창을 모두 닫은 뒤 [다시 시도]를 누르세요.',
              mbError, MB_RETRYCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
  Result := True;
end;

function InitializeSetup(): Boolean;
var
  Prev: String;
begin
  Result := False;
  if RegQueryStringValue(HKCU, '{#UninstKey}', 'InstallLocation', PrevDir) then
    PrevDir := RemoveBackslash(PrevDir)
  else
    PrevDir := '';
  if RegQueryStringValue(HKCU, '{#UninstKey}', 'DisplayVersion', Prev) and (CompareVer(Prev, '{#AppVersion}') > 0) then
  begin
    // 조용한 설치(앱 안 업데이트)는 옛 버전으로 내려가지 않는다
    if WizardSilent then
      Exit;
    if MsgBox('지금 설치된 버전: ' + Prev + #13#10 + '이 설치 파일: {#AppVersion} (옛 버전)' + #13#10#13#10 + '옛 버전으로 바꿀까요?',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then
      Exit;
  end;
  Result := AppClosed(Relaunch() or WizardSilent);
end;

function InitializeUninstall(): Boolean;
begin
  Result := AppClosed(False);
end;

function LinkTarget(const Lnk: String): String;
var
  Shell, Sc: Variant;
begin
  Result := '';
  try
    Shell := CreateOleObject('WScript.Shell');
    Sc := Shell.CreateShortcut(Lnk);
    Result := Sc.TargetPath;
  except
    Result := '';
  end;
end;

// 옛 바로 가기 지우기: 지난 설치 자리를 가리키는 것(이름이 바뀌었을 수 있다)과
// 10-19 손 설치가 만든 것(dist\{#LegacyId}\{#LegacyId}.exe). 지운 것이 있으면 True
function CleanLinks(const Dir: String): Boolean;
var
  F: TFindRec;
  Lnk, T: String;
begin
  Result := False;
  if FindFirst(Dir + '\*.lnk', F) then
  try
    repeat
      Lnk := Dir + '\' + F.Name;
      T := Lowercase(LinkTarget(Lnk));
      if (T <> '') and (((PrevDir <> '') and (CompareText(ExtractFileDir(T), PrevDir) = 0)) or
         (Pos(Lowercase('\dist\{#LegacyId}\{#LegacyId}.exe'), T) > 0)) then
        if DeleteFile(Lnk) then
          Result := True;
    until not FindNext(F);
  finally
    FindClose(F);
  end;
end;

// 이름이 바뀌어 설치 자리가 옮겨졌으면 옛 자리를 지운다(같은 Programs 폴더 안이고 제거 프로그램이 있을 때만)
procedure DropOldDir();
var
  F: TFindRec;
  App: String;
begin
  App := ExpandConstant('{app}');
  if (PrevDir = '') or (CompareText(PrevDir, App) = 0) or (not FileExists(PrevDir + '\unins000.exe')) or
     (CompareText(ExtractFileDir(PrevDir), ExtractFileDir(App)) <> 0) then
    Exit;
  if FindFirst(PrevDir + '\*.exe', F) then
  try
    repeat
      if (CompareText(F.Name, 'unins000.exe') <> 0) and (CompareText(F.Name, '{#AppExe}') <> 0) then
        RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Classes\Applications\' + F.Name);
    until not FindNext(F);
  finally
    FindClose(F);
  end;
  DelTree(PrevDir, True, True, True);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  V: String;
begin
  if CurStep = ssInstall then
  begin
    // 처음 설치거나 바탕화면 바로 가기가 있었으면 만든다. 사람이 지웠으면 업데이트 때 되살리지 않는다
    WantDesktop := (PrevDir = '') or FileExists(ExpandConstant('{autodesktop}\{#AppName}.lnk'));
    if CleanLinks(ExpandConstant('{autodesktop}')) then
      WantDesktop := True;
    CleanLinks(ExpandConstant('{autoprograms}'));
  end;
  if CurStep = ssPostInstall then
  begin
    // 10-19 손 설치는 HKCU .pdf 기본값을 이 ProgID 로 바꿔 두었다. 연결 목록(OpenWithProgids)으로 충분하니 걷는다
    if RegQueryStringValue(HKCU, 'Software\Classes\.pdf', '', V) and (CompareText(V, '{#ProgId}') = 0) then
      RegDeleteValue(HKCU, 'Software\Classes\.pdf', '');
    // 손 설치가 쓰던 기본 앱 목록 자리(Software\{#LegacyId}). 이제는 {#RegKey}
    if RegQueryStringValue(HKCU, 'Software\RegisteredApplications', '{#LegacyId}', V) and
       (CompareText(V, 'Software\{#LegacyId}\Capabilities') = 0) then
    begin
      RegDeleteValue(HKCU, 'Software\RegisteredApplications', '{#LegacyId}');
      RegDeleteKeyIncludingSubkeys(HKCU, 'Software\{#LegacyId}\Capabilities');
      RegDeleteKeyIfEmpty(HKCU, 'Software\{#LegacyId}');
    end;
    // 바로 앞 이름(0.2.1 까지 RPDF…)으로 등록한 것. 10-29 에 PDFmetry… 로 바꿈(make_setup.py 의 OLD_*)
    if RegQueryStringValue(HKCU, 'Software\Classes\.pdf', '', V) and (CompareText(V, '{#OldProgId}') = 0) then
      RegDeleteValue(HKCU, 'Software\Classes\.pdf', '');
    // ProgID 열쇠 자체는 [Registry] 가 새 exe 로 다시 적은 것이라 지우지 않는다(위 「옛 이름 ProgID」)
    RegDeleteValue(HKCU, 'Software\Classes\.pdf\OpenWithProgids', '{#OldProgId}');
    RegDeleteValue(HKCU, 'Software\RegisteredApplications', '{#OldRegApp}');
    RegDeleteKeyIncludingSubkeys(HKCU, '{#OldRegKey}');
    // 그 전 이름(0.1.3 까지 PDFEditor…)
    if RegQueryStringValue(HKCU, 'Software\Classes\.pdf', '', V) and (CompareText(V, '{#Old2ProgId}') = 0) then
      RegDeleteValue(HKCU, 'Software\Classes\.pdf', '');
    RegDeleteValue(HKCU, 'Software\Classes\.pdf\OpenWithProgids', '{#Old2ProgId}');
    RegDeleteValue(HKCU, 'Software\RegisteredApplications', '{#Old2RegApp}');
    RegDeleteKeyIncludingSubkeys(HKCU, '{#Old2RegKey}');
    DropOldDir();
  end;
end;
