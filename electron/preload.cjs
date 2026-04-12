/**
 * 预加载脚本：向渲染进程暴露安全 API（用户协议「不同意」退出等）。
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('kpsrDesktop', {
  version: '1.0.0',
  /** 退出整个应用（Electron 主进程） */
  quitApp: () => ipcRenderer.invoke('kpsr-quit'),
  /** 读取/设置「登录系统后自动启动」（仅打包安装版生效） */
  getLaunchAtLogin: () => ipcRenderer.invoke('kpsr-get-launch-at-login'),
  setLaunchAtLogin: (openAtLogin) => ipcRenderer.invoke('kpsr-set-launch-at-login', openAtLogin),
});
