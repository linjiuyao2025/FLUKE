#ifndef AppVersion
  #define AppVersion "0.1.2"
#endif

[Setup]
AppId=FLUKE-Desktop-Native-SideBySide
AppName=FLUKE
AppVersion={#AppVersion}
AppVerName=FLUKE {#AppVersion}
AppPublisher=FLUKE
DefaultDirName=D:\FLUKE-Native
DefaultGroupName=FLUKE
UsePreviousAppDir=no
AppendDefaultDirName=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
Uninstallable=yes
CloseApplications=yes
RestartApplications=no
MinVersion=10.0
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern light hidebevels includetitlebar
WizardBackColor=#EBE9E2
WizardSizePercent=125
WizardImageFile=fluke-wizard.png
WizardImageBackColor=#EBE9E2
WizardImageOpacity=255
WizardKeepAspectRatio=yes
WizardSmallImageFile=fluke-small.png
WizardSmallImageBackColor=none
OutputDir=..\release
OutputBaseFilename=FLUKE-{#AppVersion}-Setup
UninstallDisplayName=FLUKE
UninstallDisplayIcon={app}\FLUKE.exe
VersionInfoDescription=FLUKE Windows Desktop Installer
VersionInfoProductName=FLUKE
SetupLogging=no
DirExistsWarning=yes
DisableWelcomePage=no
DisableReadyPage=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "lang\ChineseSimplified.isl"

[LangOptions]
chinesesimp.DialogFontName=Microsoft YaHei UI
chinesesimp.DialogFontSize=9
chinesesimp.WelcomeFontName=Microsoft YaHei UI

[Messages]
WelcomeLabel1=欢迎安装 FLUKE
WelcomeLabel2=FLUKE 是你的本机桌面工作台。%n%n默认安装到 D:\FLUKE-Native；旧版 D:\FLUKE 不会被覆盖。
SelectDirDesc=选择 FLUKE 的安装位置
SelectDirLabel3=FLUKE 将安装到以下文件夹：
SelectDirBrowseLabel=默认位置为 D:\FLUKE-Native。你可以保留此位置，或点击“浏览”选择其他位置。
ReadyLabel1=FLUKE 已准备好安装到你的电脑。
ReadyLabel2a=点击“安装”继续。若要修改设置，请点击“上一步”。
ReadyLabel2b=点击“安装”开始安装 FLUKE。
ReadyMemoDir=安装位置：
FinishedHeadingLabel=FLUKE 已准备就绪
FinishedLabel=安装完成。选择“完成”即可关闭安装程序，也可以立即启动 FLUKE。
ConfirmUninstall=确认卸载 FLUKE？%n%n将移除程序文件与本安装创建的快捷方式。本机数据库、设置、迁移记录、个人备份和旧版数据会保留。若要清除本机数据，请在应用的数据管理中另行操作。
UninstallStatusLabel=正在移除 FLUKE 程序文件与快捷方式；本机数据将保留。
UninstallAppFullTitle=%1 卸载程序

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "..\dist\FLUKE\*"; DestDir: "{app}\versions\{#AppVersion}"; Excludes: "FLUKE-launcher.exe"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\dist\FLUKE\FLUKE-launcher.exe"; DestDir: "{app}"; DestName: "FLUKE.exe"; Flags: ignoreversion onlyifdoesntexist

[Icons]
Name: "{userprograms}\FLUKE"; Filename: "{app}\FLUKE.exe"; WorkingDir: "{app}"; Comment: "FLUKE 本机桌面工作台"
Name: "{userdesktop}\FLUKE"; Filename: "{app}\FLUKE.exe"; WorkingDir: "{app}"; Tasks: desktopicon; Comment: "FLUKE 本机桌面工作台"

[Run]
Filename: "{app}\FLUKE.exe"; Parameters: "--activate {#AppVersion}"; Description: "启动 FLUKE"; Flags: nowait postinstall

[Code]
procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpSelectTasks then
    WizardForm.NextButton.Caption := SetupMessage(msgButtonInstall)
  else if CurPageID = wpFinished then
    WizardForm.NextButton.Caption := SetupMessage(msgButtonFinish)
  else
    WizardForm.NextButton.Caption := SetupMessage(msgButtonNext);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  MarkerPath: String;
begin
  if CurStep = ssPostInstall then begin
    MarkerPath := ExpandConstant('{app}\versions\{#AppVersion}\.install-complete.json');
    SaveStringToFile(MarkerPath, '{"version":"{#AppVersion}"}', False);
  end;
end;
