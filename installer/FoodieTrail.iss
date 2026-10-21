; Foodie Trail · 美食地图 — Inno Setup 安装脚本
;
; 用法（在仓库根目录，先跑过 pyinstaller FoodieTrail.spec）：
;     iscc installer\FoodieTrail.iss /DMyAppVersion=1.0.0
;
; 产物：installer\Output\FoodieTrail-<版本>-windows-x64-setup.exe
; CI 里由 .github/workflows/release.yml 自动调用，本地手动打包也一样。

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "Foodie Trail"
#define MyAppNameFull "Foodie Trail 美食地图"
#define MyAppExeName "FoodieTrail.exe"
#define MyAppPublisher "perry466"
#define MyAppUrl "https://github.com/perry466/foodie-trail"

[Setup]
; AppId 一经发布就不要再改，否则升级会变成「装了两个」
AppId={{7C3F1E42-9A6B-4D5A-BE31-6F2D4C8A9E10}
AppName={#MyAppNameFull}
AppVersion={#MyAppVersion}
AppVerName={#MyAppNameFull} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppUrl}
AppSupportURL={#MyAppUrl}
DefaultDirName={localappdata}\FoodieTrail
DefaultGroupName={#MyAppNameFull}
DisableProgramGroupPage=yes
; 装到当前用户目录，不需要管理员权限
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=FoodieTrail-{#MyAppVersion}-windows-x64-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
; 与 launcher.py 里的互斥量同名：升级时提示关闭正在运行的实例
AppMutex=FoodieTrail.SingleInstance
CloseApplications=yes
RestartApplications=no

[Languages]
; 简体中文语言包随仓库放在 installer\ChineseSimplified.isl。
; 不用 compiler:Languages\ChineseSimplified.isl：那个目录里有没有中文取决于
; Inno Setup 的安装来源（6.4 及更早的安装包并不带），本地和 CI 都会直接编译失败。
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; 整个 dist\FoodieTrail 目录；data\ 不在这里（用户数据不进安装包）
Source: "..\dist\FoodieTrail\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\packaging\快速开始.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppNameFull}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppNameFull}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppNameFull}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppNameFull}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 故意「不」删除 {app}\data：卸载后数据还在，重装即可继续用。
; 想彻底清空请手动删除安装目录。
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\{#MyAppExeName}"
Type: files; Name: "{app}\快速开始.txt"
