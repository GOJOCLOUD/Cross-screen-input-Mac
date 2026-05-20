; NSIS 卸载时由 electron-builder 引入
; 清理普通用户数据。耐卸载的试用/激活状态镜像保留在独立位置，避免卸载重装重置试用。

!macro customUnInstall
  RMDir /r "$APPDATA\KPSR"
  RMDir /r "$APPDATA\kpsr-desktop"
!macroend
