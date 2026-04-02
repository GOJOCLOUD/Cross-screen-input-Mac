/**
 * 在部分环境（如 IDE/CI）会注入 ELECTRON_RUN_AS_NODE=1，导致主进程里 require('electron')
 * 仅为可执行路径字符串，ipcMain/app 等 API 不可用。启动前清除该变量即可。
 */
delete process.env.ELECTRON_RUN_AS_NODE;

const { spawn } = require('child_process');
const electronPath = require('electron');

const child = spawn(electronPath, ['.'], {
  stdio: 'inherit',
  env: process.env,
});

child.on('exit', (code, signal) => {
  if (signal) process.exit(1);
  process.exit(code == null ? 0 : code);
});
