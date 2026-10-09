; Chalkpress Windows 安装包脚本（Inno Setup 6，per-user 安装，免管理员权限）
; CI 编译: ISCC.exe /DAppVersion=x.y.z packaging\chalkpress.iss

#ifndef AppVersion
#define AppVersion "0.0.0"
#endif

[Setup]
AppName=Chalkpress
AppVersion={#AppVersion}
AppPublisher=luolin1024
DefaultDirName={autopf}\Chalkpress
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=chalkpress-windows-x64-setup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayName=Chalkpress

[Languages]
; Inno Setup 6.5+ 官方自带简中；镜像若未内置则回退英文
#if FileExists(CompilerPath + "\Languages\ChineseSimplified.isl")
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\chalkpress\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Chalkpress"; Filename: "{app}\chalkpress.exe"
Name: "{autodesktop}\Chalkpress"; Filename: "{app}\chalkpress.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\chalkpress.exe"; Description: "{cm:LaunchProgram,Chalkpress}"; Flags: nowait postinstall skipifsilent
