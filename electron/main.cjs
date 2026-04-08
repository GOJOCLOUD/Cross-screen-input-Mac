/**
 * Electron 主进程：启动内嵌 Python 后端（打包后 resources/backend/kpsr-backend[.exe]），再打开本机 Web UI。
 */
/**
 * 某些环境（如 Cursor/IDE/CI）可能注入 ELECTRON_RUN_AS_NODE=1，
 * 会导致 require('electron') 退化为可执行路径字符串，app/ipcMain 等 API 不可用并直接退出。
 * 在主进程入口清理该变量，保证“安装后双击启动”不受外部环境污染。
 */
delete process.env.ELECTRON_RUN_AS_NODE;

/**
 * 早期启动诊断日志（写入 /tmp，便于定位“一闪退/无窗口”问题）。
 * 生产环境可保留，文件很小；不包含用户隐私数据。
 */
const _bootFs = require('fs');
function _bootLog(line) {
  try {
    const ts = new Date().toISOString();
    _bootFs.appendFileSync('/tmp/kpsr-electron-boot.log', `[${ts}] ${line}\n`, 'utf8');
  } catch (_) {}
}
_bootLog('main.cjs start');
process.on('exit', (code) => _bootLog(`process exit code=${code}`));
process.on('uncaughtException', (err) => _bootLog(`uncaughtException: ${String(err && err.stack ? err.stack : err)}`));
process.on('unhandledRejection', (reason) => _bootLog(`unhandledRejection: ${String(reason)}`));

const { app, BrowserWindow, dialog, shell, ipcMain } = require('electron');
const path = require('path');
const fs = require('fs');
const http = require('http');
const { spawn } = require('child_process');
const treeKill = require('tree-kill');

/** 默认端口；可被环境变量 KPSR_PORT、用户目录 settings.json 的 http_port 覆盖（与 Python 后端 config 一致） */
const DEFAULT_BACKEND_PORT = 2345;
/** 与 hotspot/backend/config.py 中 CHROMIUM_FORBIDDEN_WEB_PORTS 保持同步（Chromium 禁止用于 http 导航） */
const CHROMIUM_FORBIDDEN_WEB_PORTS = new Set([
  1, 7, 9, 11, 13, 15, 17, 19, 20, 21, 22, 23, 25, 37, 42, 43, 53, 69, 77, 79, 87, 95,
  101, 102, 103, 104, 109, 110, 111, 113, 115, 117, 119, 123, 135, 139, 143, 161, 179, 389, 465,
  512, 513, 514, 515, 526, 530, 531, 532, 540, 543, 544, 548, 556, 563, 587, 601, 636, 989, 990,
  993, 995, 1719, 1720, 1723, 2049, 3659, 4045, 5060, 5061, 6000, 6568, 6665, 6666, 6667, 6668, 6669,
  6697, 10080,
]);
let backendPort = DEFAULT_BACKEND_PORT;

let mainWindow = null;
let backendProcess = null;
let launchInstanceToken = '';
let isEnsuringBackend = false;
let stoppingBackendPromise = null;
let isShutdownInProgress = false;
let isAppForceExiting = false;
let backendLastExit = null;

_bootLog(`electron required ok; isPackaged=${app.isPackaged}`);

ipcMain.handle('kpsr-quit', () => {
  void shutdownAppWithBackend();
});

/**
 * 解析后端监听端口（须在 app.ready 后调用，以便读取 userData/settings.json）
 */
function readConfiguredPort() {
  const env = process.env.KPSR_PORT || process.env.PORT;
  if (env) {
    const p = parseInt(String(env).trim(), 10);
    if (Number.isFinite(p) && p >= 1024 && p <= 65535) return p;
    return DEFAULT_BACKEND_PORT;
  }
  try {
    const userData = app.getPath('userData');
    const settingsPath = path.join(userData, 'settings.json');
    if (fs.existsSync(settingsPath)) {
      const j = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
      const p = parseInt(j.http_port, 10);
      if (Number.isFinite(p) && p >= 1024 && p <= 65535) return p;
    }
  } catch (e) {
    console.warn('[KPSR] 读取 settings.json 端口失败:', e);
  }
  return DEFAULT_BACKEND_PORT;
}

function getHealthUrl() {
  return `http://127.0.0.1:${backendPort}/health`;
}

function getAppUrl() {
  return `http://127.0.0.1:${backendPort}/`;
}

function getBackendExecutable() {
  const exeName = process.platform === 'win32' ? 'kpsr-backend.exe' : 'kpsr-backend';
  if (app.isPackaged) {
    // 兼容两种打包形态：
    // 1) PyInstaller onedir（推荐）：resources/backend/kpsr-backend
    // 2) 旧 onefile：resources/backend/kpsr-backend
    return path.join(process.resourcesPath, 'backend', exeName);
  }
  const distDir = path.join(__dirname, '..', 'hotspot', 'backend', 'dist');
  const onedirExe = path.join(distDir, exeName, exeName);
  if (fs.existsSync(onedirExe)) return onedirExe;
  return path.join(distDir, exeName);
}

/** 与 Electron 用户数据目录一致，激活文件随卸载删除（见 package.json deleteAppDataOnUninstall） */
function getBackendEnv() {
  return {
    ...process.env,
    KPSR_USER_DATA: app.getPath('userData'),
    KPSR_PORT: String(backendPort),
    KPSR_INSTANCE_TOKEN: launchInstanceToken,
  };
}

function startBackend() {
  const env = getBackendEnv();
  const attachLifecycle = (proc) => {
    if (!proc) return proc;
    proc.once('exit', (code, signal) => {
      backendLastExit = {
        at: Date.now(),
        code: Number.isFinite(code) ? code : null,
        signal: signal || null,
      };
      if (backendProcess === proc) {
        backendProcess = null;
      }
    });
    proc.once('error', () => {
      if (backendProcess === proc) {
        backendProcess = null;
      }
    });
    return proc;
  };

  if (app.isPackaged) {
    const exe = getBackendExecutable();
    if (!fs.existsSync(exe)) {
      throw new Error(`未找到后端程序：\n${exe}`);
    }
    backendProcess = attachLifecycle(spawn(exe, [], {
      cwd: path.dirname(exe),
      windowsHide: true,
      stdio: 'ignore',
      env,
    }));
    return;
  }

  // 开发模式：优先使用已打包后端二进制；否则用 python 启动 main.py
  const devExe = getBackendExecutable();
  if (fs.existsSync(devExe)) {
    backendProcess = attachLifecycle(spawn(devExe, [], {
      cwd: path.dirname(devExe),
      windowsHide: true,
      stdio: 'inherit',
      env,
    }));
    return;
  }

  const backendDir = path.join(__dirname, '..', 'hotspot', 'backend');
  const py = process.platform === 'win32' ? 'python' : 'python3';
  backendProcess = attachLifecycle(spawn(py, ['main.py'], {
    cwd: backendDir,
    shell: true,
    windowsHide: false,
    stdio: 'inherit',
    env,
  }));
}

function waitForBackend(timeoutMs = 180000) {
  const start = Date.now();
  return new Promise((resolve) => {
    const tryOnce = () => {
      if (Date.now() - start > timeoutMs) {
        resolve(false);
        return;
      }
      const req = http.get(getHealthUrl(), { timeout: 2500 }, (res) => {
        let body = '';
        res.setEncoding('utf8');
        res.on('data', (chunk) => {
          body += chunk;
        });
        res.on('end', () => {
          if (res.statusCode !== 200) {
            setTimeout(tryOnce, 400);
            return;
          }
          try {
            const j = JSON.parse(body || '{}');
            // 只认本次启动实例，避免误连旧版本/旧安装包占用同端口导致状态跳变
            if (j.instance_token && j.instance_token === launchInstanceToken) {
              resolve(true);
              return;
            }
          } catch (_) {}
          setTimeout(tryOnce, 400);
        });
      });
      req.on('error', () => {
        setTimeout(tryOnce, 400);
      });
      req.on('timeout', () => {
        req.destroy();
        setTimeout(tryOnce, 400);
      });
    };
    tryOnce();
  });
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isProcessAlive(pid) {
  if (!Number.isFinite(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (_) {
    return false;
  }
}

async function waitForPidExit(pid, timeoutMs = 2000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (!isProcessAlive(pid)) return true;
    await delay(120);
  }
  return !isProcessAlive(pid);
}

async function stopBackend(timeoutMs = 4500) {
  if (stoppingBackendPromise) return stoppingBackendPromise;

  stoppingBackendPromise = (async () => {
    if (!backendProcess || !backendProcess.pid) {
      backendProcess = null;
      return true;
    }

    const pid = backendProcess.pid;
    const termBudget = Math.min(1600, Math.max(600, Math.floor(timeoutMs * 0.4)));
    const killBudget = Math.max(400, timeoutMs - termBudget);

    try {
      await new Promise((resolve) => {
        try {
          treeKill(pid, 'SIGTERM', () => resolve());
        } catch (_) {
          resolve();
        }
      });
      const exitedByTerm = await waitForPidExit(pid, termBudget);
      if (!exitedByTerm && isProcessAlive(pid)) {
        await new Promise((resolve) => {
          try {
            treeKill(pid, 'SIGKILL', () => resolve());
          } catch (_) {
            resolve();
          }
        });
        await waitForPidExit(pid, killBudget);
      }
    } catch (_) {
      // 忽略杀进程过程异常，退出链路继续推进
    } finally {
      backendProcess = null;
    }
    return true;
  })();

  try {
    return await stoppingBackendPromise;
  } finally {
    stoppingBackendPromise = null;
  }
}

async function shutdownAppWithBackend(exitCode = 0) {
  if (isAppForceExiting || isShutdownInProgress) return;
  isShutdownInProgress = true;
  try {
    await stopBackend();
  } finally {
    isAppForceExiting = true;
    app.exit(exitCode);
  }
}

function isBackendProcessAlive() {
  if (!backendProcess || !backendProcess.pid) return false;
  try {
    process.kill(backendProcess.pid, 0);
    return true;
  } catch (_) {
    return false;
  }
}

async function ensureBackendReadyForReopen() {
  if (isEnsuringBackend) return false;
  isEnsuringBackend = true;
  try {
    // 后端可达则直接复用
    if (await waitForBackend(1500)) return true;

    // 后端不可达时，不论是否仍有残留 pid，统一先做一次回收再重启，避免“假活进程”阻断恢复
    await stopBackend(3500);
    try {
      launchInstanceToken = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
      startBackend();
    } catch (e) {
      console.warn('[KPSR] 二次启动时重启后端失败:', e);
      return false;
    }
    return await waitForBackend(20000);
  } finally {
    isEnsuringBackend = false;
  }
}

const LOADING_PAGE_HTML = `<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>启动中</title>
<style>
  *{box-sizing:border-box;margin:0}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  display:flex;align-items:center;justify-content:center;min-height:100vh;background:#f5f5f5;color:#333;}
  .box{text-align:center;padding:24px;max-width:360px;}
  .spin{width:44px;height:44px;margin:0 auto 20px;border:3px solid #e5e5e5;border-top-color:#1a1a1a;border-radius:50%;
  animation:kpsrspin .85s linear infinite;}
  @keyframes kpsrspin{to{transform:rotate(360deg)}}
  p{font-size:15px;line-height:1.5;margin-bottom:8px;}
  .sub{font-size:13px;color:#888;}
</style></head><body><div class="box"><div class="spin"></div>
<p>正在启动本地服务…</p>
<p class="sub">首次安装后杀毒软件可能扫描程序，需数十秒属正常现象，请稍候勿重复点击。</p>
</div></body></html>`;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 900,
    minHeight: 600,
    show: true,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.loadURL(
    'data:text/html;charset=utf-8,' + encodeURIComponent(LOADING_PAGE_HTML),
  );

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

/** 本地服务就绪后加载主界面 */
function loadMainUiInWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.loadURL(getAppUrl());
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', async () => {
    if (isShutdownInProgress || isAppForceExiting) return;
    // 某些场景下旧实例仍在退出中，但主窗口已被销毁；
    // 这时再次双击应用会命中 single-instance 分支，若不重建窗口会表现为“无法再次启动”。
    if (!mainWindow || mainWindow.isDestroyed()) {
      createWindow();
      const ok = await ensureBackendReadyForReopen();
      if (!ok) {
        await dialog.showMessageBox({
          type: 'error',
          title: 'KPSR 跨屏输入',
          message: '后端未就绪，无法恢复主界面',
          detail: `请稍后重试；若持续失败，请先完全退出程序后再启动。\n当前端口：${backendPort}`,
        });
        return;
      }
      loadMainUiInWindow();
      return;
    }
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });

  app.whenReady().then(async () => {
    backendPort = readConfiguredPort();
    launchInstanceToken = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    if (CHROMIUM_FORBIDDEN_WEB_PORTS.has(backendPort)) {
      await dialog.showMessageBox({
        type: 'error',
        title: 'KPSR 跨屏输入',
        message: '当前 HTTP 端口无法在 Electron 内使用',
        detail:
          `端口 ${backendPort} 被 Chromium 内核禁止使用，无法加载本地网页。\n\n` +
          '请手动编辑用户数据目录下的 settings.json，将 http_port 改为其它端口（例如 2345、8080）。\n' +
          '程序不会自动修改您的配置。',
      });
      app.quit();
      return;
    }
    try {
      startBackend();
    } catch (e) {
      await dialog.showMessageBox({
        type: 'error',
        title: 'KPSR 跨屏输入',
        message: '无法启动后端服务',
        detail: String(e && e.message ? e.message : e),
      });
      app.quit();
      return;
    }

    createWindow();

    const ok = await waitForBackend();
    if (!ok) {
      await stopBackend();
      await dialog.showMessageBox({
        type: 'error',
        title: 'KPSR 跨屏输入',
        message: '后端服务启动超时',
        detail: `请检查端口 ${backendPort} 是否被占用，或防火墙是否拦截。\n也可尝试先单独运行后端程序（kpsr-backend）排查。\n可在用户数据目录 settings.json 中修改 http_port 后重启。`,
      });
      app.quit();
      return;
    }

    loadMainUiInWindow();

    app.on('activate', async () => {
      if (BrowserWindow.getAllWindows().length === 0) {
        createWindow();
        const ok = await ensureBackendReadyForReopen();
        if (!ok) {
          await dialog.showMessageBox({
            type: 'error',
            title: 'KPSR 跨屏输入',
            message: '后端未就绪，无法恢复主界面',
            detail:
              `请稍后重试；若持续失败，请先完全退出程序后再启动。\n当前端口：${backendPort}` +
              (backendLastExit
                ? `\n最近后端退出信息：code=${backendLastExit.code}, signal=${backendLastExit.signal}`
                : ''),
          });
          return;
        }
        loadMainUiInWindow();
      }
    });
  });

  app.on('window-all-closed', (event) => {
    event.preventDefault();
    void shutdownAppWithBackend();
  });

  app.on('before-quit', (event) => {
    if (isAppForceExiting) return;
    event.preventDefault();
    void shutdownAppWithBackend();
  });

  process.on('uncaughtException', async (err) => {
    console.error('[KPSR] 主进程未捕获异常:', err);
    await shutdownAppWithBackend(1);
  });
  process.on('unhandledRejection', async (reason) => {
    console.error('[KPSR] 主进程未处理 Promise 拒绝:', reason);
    await shutdownAppWithBackend(1);
  });
}
