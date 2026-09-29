#ifndef QARoot
  #define QARoot AddBackslash(SourcePath) + "..\qa-sandbox"
#endif
#ifndef AppSourceDir
  #define AppSourceDir "..\dist\FLUKE"
#endif
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId=FLUKE-Desktop-Native-QA
AppName=FLUKE QA
AppVersion={#AppVersion}
AppVerName=FLUKE QA {#AppVersion}
AppPublisher=FLUKE
DefaultDirName={#QARoot}\program
DefaultGroupName=FLUKE QA
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
OutputDir={#QARoot}\installer-output
OutputBaseFilename=FLUKE-QA-{#AppVersion}-Setup
UninstallDisplayName=FLUKE QA
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
WelcomeLabel2=FLUKE QA 是独立测试版本。%n%n默认安装到 {#QARoot}\program；请勿把 QA 测试配置与正式版数据混用。
SelectDirDesc=选择 FLUKE 的安装位置
SelectDirLabel3=FLUKE 将安装到以下文件夹：
SelectDirBrowseLabel=默认位置为 {#QARoot}\program。测试数据应使用单独的测试配置目录。
ReadyLabel1=FLUKE 已准备好安装到你的电脑。
ReadyLabel2a=点击“安装”继续。若要修改设置，请点击“上一步”。
ReadyLabel2b=点击“安装”开始安装 FLUKE。
ReadyMemoDir=安装位置：
FinishedHeadingLabel=FLUKE 已准备就绪
FinishedLabel=安装完成。选择“完成”即可关闭安装程序，也可以立即启动 FLUKE。
ConfirmUninstall=QA：确认卸载 FLUKE 测试版本？%n%n将删除本次安装以及 QA 根目录中登记的测试配置和快捷方式。请仅在独立 QA 配置下运行测试版。
UninstallStatusLabel=QA：正在清理 FLUKE 测试程序与隔离测试配置，请稍候。
UninstallAppFullTitle=FLUKE QA 卸载程序

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{#QARoot}\shortcuts\start-menu\FLUKE-QA"; Filename: "{app}\FLUKE.exe"; WorkingDir: "{app}"; Comment: "FLUKE 本机桌面工作台"
Name: "{#QARoot}\shortcuts\desktop\FLUKE-QA"; Filename: "{app}\FLUKE.exe"; WorkingDir: "{app}"; Tasks: desktopicon; Comment: "FLUKE 本机桌面工作台"

[UninstallDelete]
Type: filesandordirs; Name: "{#QARoot}\profile\roaming\FLUKE"
Type: filesandordirs; Name: "{#QARoot}\profile\local\FLUKE"
Type: filesandordirs; Name: "{#QARoot}\profile\roaming\Wanxiang Life Workspace Native"
Type: filesandordirs; Name: "{#QARoot}\profile\local\Wanxiang Life Workspace Native"
Type: filesandordirs; Name: "{#QARoot}\temp\wanxiang-backup-*"
Type: filesandordirs; Name: "{#QARoot}\temp\wanxiang-backup-preview-*"
Type: filesandordirs; Name: "{#QARoot}\temp\wanxiang-legacy-restore-*"
Type: filesandordirs; Name: "{#QARoot}\temp\fluke-backup-*"
Type: filesandordirs; Name: "{#QARoot}\temp\fluke-backup-preview-*"
Type: filesandordirs; Name: "{#QARoot}\temp\fluke-legacy-restore-*"
Type: files; Name: "{#QARoot}\shortcuts\desktop\FLUKE-QA.lnk"
Type: dirifempty; Name: "{#QARoot}\shortcuts\start-menu\FLUKE-QA"

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
