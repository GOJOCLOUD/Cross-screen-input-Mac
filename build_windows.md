## Windows 打包说明（一次性买断版，含热点 + 局域网）

本说明假设你在本机有 Python 3.10+ 和 Node.js 环境，并在根目录执行命令。

### 1. 安装依赖

```bash
cd hotspot/backend
pip install -r requirements.txt
pip install pyinstaller
```

> 可选：为保证可重复构建，建议在虚拟环境中执行上述命令。

### 2. 准备图标（ICO，多尺寸）

项目根目录下添加一张高分辨率 PNG 图标（例如 `icon_source.png`，512×512 或 1024×1024）。

运行图标生成脚本：

```bash
cd .
python generate_ico.py
```

生成结果：

- `app_icon.ico`：包含常见尺寸（16/32/48/64/128/256），可直接给 PyInstaller / 安装器使用。

### 3. 打包后端（供 Electron 内嵌，单文件 `kpsr-backend.exe`）

**完整 PyInstaller 参数（含 `--add-data` 前端与 hidden-import）与 CI 一致**，请直接对照仓库内 `.github/workflows/build-and-release.yml` 的步骤 **Build backend EXE**。

本地快速要点：

- 在 `hotspot/backend` 下执行，`--name kpsr-backend`，`--onefile`，并把 `..\frontend`、`data`、`routes`、`utils`、`config.py` 打进包（与 CI 相同）。
- 生成文件：`hotspot/backend/dist/kpsr-backend.exe`（Electron 会复制为 `electron/resources/backend/kpsr-backend.exe`）。

> 调试期建议保留控制台；若只要单独运行后端、不要 Electron，可直接运行该 exe。

### 4. Electron 桌面软件（推荐 · Windows）

工程目录：`electron/`。逻辑：启动 `kpsr-backend.exe`（或开发时用 `python main.py`），窗口加载 `http://127.0.0.1:2345/`。

```bash
cd electron
npm install
# 请先完成第 3 步，生成 hotspot/backend/dist/kpsr-backend.exe（PyInstaller 产物名为 kpsr-backend）
npm run dist:win
```

产物在 `electron/dist/`：NSIS 安装包 + 便携版 exe。CI 见 `.github/workflows/build-and-release.yml`。

### 5. 其他安装器（可选）

也可自行将 `hotspot/frontend` 与后端 exe 组合进其它安装器；启动方式与 Electron 相同：先起后端，再打开 `http://localhost:2345`。

### 6. 局域网模式说明（内置中转站）

- 不再需要单独启动 `lan/relay_server.py` 或占用 9000 端口。
- 电脑端在「连接模式」选择 **局域网模式** 时：
  - PC 端会通过 `ws://127.0.0.1:2345/lan/ws` 注册为 `pc_xxx`；
  - 电脑端页面生成手机访问链接，形如：
    - `http://<局域网IP>:2345/phone?mode=lan&relay_ws=ws://<局域网IP>:2345/lan/ws&pc_id=pc_xxx`
  - 手机端 `phone.html` 里的 `lan_mode.js` 会自动解析这些参数，通过中转站转发指令。

### 7. 激活与安全（防止打包后被轻易破解）

激活相关有两部分：

1. **内部逻辑（应用本身用）**
   - 位于 `hotspot/backend` 的代码中（如 `routes/activation.py`、`utils/platform_utils.py` 等）。
   - 这些逻辑会随主程序一起打包，这是正常的。

> 建议：发布构建时，只上传 / 分发 **Electron 安装包 / 便携 exe**（或单独的 `kpsr-backend.exe`），避免附带任何“外部生成器”类工具文件。

### 8. 本地测试流程（发布前必做）

1. 手动启动后端（开发模式）：

```bash
cd hotspot/backend
python main.py
```

2. 在浏览器验证：

- 电脑端：`http://localhost:2345`
- 手机端：
  - 热点模式：按页面提示连手机热点并扫码；
  - 局域网模式：切换为 “局域网”，在同一局域网手机浏览器访问二维码/链接。

3. 使用 `hotspot/backend/dist/kpsr-backend.exe`（或安装后的 Electron）启动，重复上述验证，确保行为一致。

