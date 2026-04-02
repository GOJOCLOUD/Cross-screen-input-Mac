# KPSR 跨屏输入工具 (Windows版)

手机控制电脑的剪贴板、快捷键和鼠标操作。

## 功能特性

- 📱 **手机控制电脑**：通过手机浏览器控制电脑
- 📋 **剪贴板同步**：手机输入文本直接复制到电脑剪贴板
- ⌨️ **快捷键执行**：手机触发电脑快捷键
- 🖱️ **鼠标操作**：手机控制电脑鼠标点击
- 🔄 **自动端口管理**：智能选择可用端口，无需手动配置

## 技术栈

- **后端**：Python + FastAPI + PyInstaller
- **前端**：HTML + CSS + JavaScript
- **桌面壳**：Electron

## 项目结构

```
KPSR_副本2/
├── backend/          # Python 后端
│   ├── main.py      # FastAPI 主应用
│   ├── routes/      # API 路由
│   ├── utils/       # 工具函数
│   └── data/        # 配置文件
├── electron/         # Electron 桌面应用
│   ├── main.js      # 主进程
│   ├── preload.js   # 预加载脚本
│   └── loading.html # 加载页面
└── frontend/         # 前端页面
    ├── desktop.html # 电脑端界面
    └── phone.html   # 手机端界面
```

## 开发环境搭建

### 后端

```bash
cd backend
pip install -r requirements.txt
```

### 前端

```bash
cd electron
npm install
```

## 打包

### Windows

```powershell
# 1. 打包后端
cd backend
pip install pyinstaller
pip install -r requirements.txt
pyinstaller kpsr-backend.spec --clean

# 2. 打包 Electron
cd ../electron
npm install
npm run build:win
```

打包文件位于：`electron/dist/KPSR跨屏输入-1.0.0-x64.exe`

## 使用说明

### 日常使用

1. 启动应用后，会自动显示二维码和访问地址
2. 手机连接到电脑的热点网络（10.x.x.x）
3. 在手机浏览器中访问显示的地址
4. 开始使用跨屏输入功能

## 开发模式

### 后端开发

```bash
cd backend
python main.py
```

### Electron 开发

```bash
cd electron
npm start
```

## 激活状态与打包测试（重要）

- **激活信息不在安装包里**。Electron 桌面版：后端使用与 Electron 相同的用户目录（环境变量 `KPSR_USER_DATA`，一般为 `%APPDATA%\kpsr-desktop`，激活文件在其中的 `data\activation.json`），与 **卸载时删除应用数据** 一致。**旧版或单独运行 `kpsr-backend.exe`** 仍可能使用 `%APPDATA%\KPSR`。
- 因此：**同一台电脑**上先激活过，再装新包，打开仍可能是「已激活」——这是**沿用了旧数据**，不是安装包带了激活。
- **要测试「首次打开 = 未激活」**：先退出程序，删除整个文件夹 `%APPDATA%\KPSR`（或只删其中的 `data\activation.json`），再启动。**不必**为了未激活而重新打包。
- 在**从未运行过本软件的电脑 / 新 Windows 用户 / 虚拟机**上安装，默认即为未激活（无上述文件时由程序生成未激活状态）。
- **安装版（NSIS）卸载**：已配置卸载时删除 `%APPDATA%\KPSR`（含激活与本地配置），与软件一并清理。**便携版（portable .exe）** 无卸载程序，需自行删除该文件夹。

## 注意事项

- 应用会自动选择可用端口（默认 19653）
- 首次启动可能需要几秒钟解压依赖
- 确保手机和电脑在同一网络（建议使用电脑热点）

## 许可证

MIT
