# KPSR 跨屏输入 · Electron 桌面端

内置启动 **Python 后端**（打包后为 `kpsr-backend.exe`），窗口加载 `http://127.0.0.1:<端口>/`（默认 **2345**；可通过环境变量 `KPSR_PORT` 或用户数据目录 `settings.json` 中的 `http_port` 修改，需重启生效）。

## 本地开发

1. 安装依赖：`npm install`
2. 任选其一：
   - **推荐**：先按仓库根目录说明用 PyInstaller 打出 `hotspot/backend/dist/kpsr-backend.exe`，再执行 `npm start`；
   - 或在 `hotspot/backend` 配置好 Python 依赖后，直接 `npm start`（将自动 `python main.py`）。

## 发布构建（Windows）

由 CI 完成：先构建 `kpsr-backend.exe` 复制到 `resources/backend/`，再执行 `npm run dist:win`。

产物一般在 `electron/dist/`：

- **NSIS 安装包**：`KPSR跨屏输入 Setup x.y.z.exe`
- **便携版**：`KPSR跨屏输入 x.y.z.exe`（portable）

### Windows 安装被拦截 / 提示「智能应用控制」

多为 **未签名安装包** 被 Windows 11 **智能应用控制** 或 **SmartScreen** 拦截，与某次版本业务改动无必然关系。用户操作说明与开发者签名方案见：**[WINDOWS安装被拦截说明.md](./WINDOWS安装被拦截说明.md)**。

### GitHub 上「main 的构建」和「v1.0.0 Release」下载为什么不一样？

| 来源 | 说明 |
|------|------|
| **正式版** `v1.0.0` 等 | 打 `v*` **tag** 后，工作流会创建 **GitHub Release**，Assets 直链可分享、**未登录也常能下**。 |
| **main 最新代码** | 以前只有 **Actions → Artifacts**：通常要 **登录 GitHub**、入口深，分享链接还容易失效，看起来像「不能下载」。 |

**现已调整**：每次推 **main**（及手动 `workflow_dispatch`）会在 Releases 里维护 **`dev-latest` 预发布**（预发布 / 非 Latest），固定附件 **`KPSR跨屏输入-Electron-dev.zip`**，下载方式与正式版一致。请优先让用户从 **Releases → 开发版（dev-latest）** 下，而不是从 Actions 里点 Artifact。

### 为什么第一次打开要等很久 / 像卡住？

1. **内置 `kpsr-backend.exe`** 第一次运行常被 **Defender / 杀毒** 做可执行扫描，几十秒到一两分钟都常见。  
2. Electron 会先显示 **「正在启动本地服务…」** 再进主界面，请勿重复双击多开。  
3. 若长期很慢，可将安装目录或用户数据目录加入杀毒 **排除项**（自行权衡安全）。

## 图标（可选）

将 `icon.ico` 放在 `electron/build/` 下，electron-builder 会自动用作 Windows 图标。CI 会在存在仓库根目录 `app_icon.ico` 时复制到此处。
