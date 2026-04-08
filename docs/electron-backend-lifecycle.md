# Electron 与后端生命周期说明

本文固定桌面端主进程与 Python 后端的启动、恢复、退出时序，作为后续修改的约束基线。

## 目标

- 保证后端状态与主进程认知一致，避免“后端假活”。
- 窗口恢复和二次打开时，必须先校验后端可达再加载 UI。
- 主进程出现未捕获异常时，执行统一退出链路，避免残留子进程。

## 核心流程

1. `app.whenReady`
   - 读取端口配置并校验是否为 Chromium 禁用端口。
   - 生成实例令牌 `launchInstanceToken`。
   - 启动后端进程，并绑定 `exit/error` 生命周期回调。
   - 等待 `/health` 返回且 `instance_token` 匹配后再加载主界面。

2. 窗口恢复（`app.activate`）
   - 若没有窗口，先创建窗口。
   - 调用 `ensureBackendReadyForReopen()`：
     - 先快速探测后端是否可达；
     - 不可达时先 `stopBackend()` 清残留，再拉起新后端；
     - 成功后才 `loadMainUiInWindow()`。

3. 二次启动（`second-instance`）
   - 若窗口不存在，走与 `activate` 相同的恢复逻辑。
   - 若窗口存在，只做恢复/聚焦，不重复创建。

4. 退出链路
   - `window-all-closed`、`before-quit` 统一走 `shutdownAppWithBackend()`。
   - 先停后端，再 `app.exit()`。

5. 兜底异常处理
   - `process.on('uncaughtException')`
   - `process.on('unhandledRejection')`
   - 两者都进入 `shutdownAppWithBackend(1)`。

## 不变量（后续改动必须保持）

- 不得在“后端未确认可达”时直接加载主界面 URL。
- 后端不可达时，恢复逻辑必须先回收旧后端句柄/进程后再启动。
- 后端进程对象必须绑定 `exit/error`，并在回调中清理全局引用。
- 退出时先停后端再退主进程，不允许反序。

## 回归清单

- 首次启动：后端正常拉起，主界面可打开。
- 强杀后端后恢复窗口：可自动重启后端并恢复。
- 快速连击打开应用：不会卡在“假活不可恢复”状态。
- 主进程异常注入：进程能完整退出，不残留后端。
