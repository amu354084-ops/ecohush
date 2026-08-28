[Setup]
AppName=ERP Offline System
AppVersion=1.0.0
DefaultDirName={pf}\ERP_Offline
DisableProgramGroupPage=yes
Uninstallable=yes
CreateAppDir=yes
OutputDir=dist
OutputBaseFilename=ERP_Setup_v1.0
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\erp_offline.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "app\static\*"; DestDir: "{app}\static"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "erp_local.db"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\ERP Offline"; Filename: "{app}\erp_offline.exe"
Name: "{commondesktop}\ERP Offline"; Filename: "{app}\erp_offline.exe"

[Run]
Filename: "{cmd}"; Parameters: "/C netsh advfirewall firewall add rule name=\"ERP Offline\" dir=in action=allow program=\"{app}\erp_offline.exe\" enable=yes profile=any"; Flags: runhidden
Filename: "{app}\erp_offline.exe"; Description: "Start ERP Offline Server"; Flags: shellexec postinstall skipifsilent
