; v2p2 Windows 安装包脚本（Inno Setup 6，per-user 安装，免管理员权限）
; CI 编译: ISCC.exe /DAppVersion=x.y.z packaging\v2p2.iss

#ifndef AppVersion
#define AppVersion "0.0.0"
#endif

[Setup]
AppName=v2p2
AppVersion={#AppVersion}
AppPublisher=luolin1024
DefaultDirName={autopf}\v2p2
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=v2p2-windows-x64-setup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayName=v2p2

[Languages]
; Inno Setup 6.5+ 官方自带简中；镜像若未内置则回退英文
#if FileExists(CompilerPath + "\Languages\ChineseSimplified.isl")
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\v2p2\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\v2p2"; Filename: "{app}\v2p2.exe"
Name: "{autodesktop}\v2p2"; Filename: "{app}\v2p2.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\v2p2.exe"; Description: "{cm:LaunchProgram,v2p2}"; Flags: nowait postinstall skipifsilent
