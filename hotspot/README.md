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

- **激活信息不在安装包里**。Electron 桌面版会把关键离线状态写入更耐卸载的本地安全存储/密文镜像中，避免用户仅靠卸载重装就重置试用。旧版留下的 `activation.json` 仍会被兼容读取并迁移，但新版本不再继续把完整状态写回明文 JSON。**旧版或单独运行 `kpsr-backend.exe`** 仍可能使用 `%APPDATA%\KPSR`。
- 因此：**同一台电脑**上先激活过，再装新包，打开仍可能是「已激活」——这是**沿用了旧数据**，不是安装包带了激活。
- **要测试「首次打开 = 未激活」**：开发环境下建议使用 `scripts/reset_trial_state.sh`；打包版除了用户目录缓存外，还会保留耐卸载状态，单删普通配置目录已不足以重置试用。
- 在**从未运行过本软件的电脑 / 新 Windows 用户 / 虚拟机**上安装，默认即为未激活（无上述文件时由程序生成未激活状态）。
- **安装版（NSIS）卸载**：会清理普通用户配置目录，但会保留独立的耐卸载离线状态，避免卸载重装重置试用。**便携版（portable .exe）** 无卸载程序，普通配置仍需自行清理。

## 注意事项

- 应用会自动选择可用端口（默认 19653）
- 首次启动可能需要几秒钟解压依赖
- 确保手机和电脑在同一网络（建议使用电脑热点）

## 许可证

MIT
