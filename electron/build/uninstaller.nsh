; NSIS 卸载时由 electron-builder 引入
; 旧版后端使用 %APPDATA%\KPSR；新版由 Electron 传入 KPSR_USER_DATA，数据在 %APPDATA%\kpsr-desktop（由 deleteAppDataOnUninstall 处理）
; 此处仅清理旧路径，避免残留激活信息

!macro customUnInstall
  RMDir /r "$APPDATA\KPSR"
!macroend
