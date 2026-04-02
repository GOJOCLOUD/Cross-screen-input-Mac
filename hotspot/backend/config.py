#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置文件
管理项目路径和其他配置
Mac专用版本
"""

import os
import sys
import json
import shutil


def is_packaged():
    """检测是否在打包环境中运行（PyInstaller）"""
    # PyInstaller 打包后会设置 frozen 属性
    if getattr(sys, 'frozen', False):
        return True
    return False


def get_base_path():
    """获取基础路径（资源文件位置）"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后，_MEIPASS 是临时解压目录
        return sys._MEIPASS
    else:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_executable_dir():
    """获取可执行文件所在目录（用于找到 frontend 等资源）"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后，可执行文件所在目录
        exe_dir = os.path.dirname(sys.executable)
        return exe_dir
    else:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_user_data_dir():
    """
    获取用户数据目录（按平台）。
    若设置环境变量 KPSR_USER_DATA（Electron 主进程应设为 app.getPath('userData')），
    则激活/配置与桌面壳在同一目录，卸载软件时可被 deleteAppDataOnUninstall 一并删除。
    未设置时（单独运行 kpsr-backend.exe）：Windows 默认为 %APPDATA%\\KPSR。
    """
    override = (os.environ.get("KPSR_USER_DATA") or os.environ.get("KPSR_DATA_HOME") or "").strip()
    if override:
        return os.path.normpath(override)
    if sys.platform == 'win32':
        # Windows 独立运行后端：%APPDATA%\KPSR
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return os.path.join(base, "KPSR")
    if sys.platform == 'darwin':
        return os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'KPSR')
    # Linux
    return os.path.join(os.path.expanduser('~'), '.config', 'KPSR')


# 判断运行环境
IS_PACKAGED = is_packaged()

# 获取项目根目录（源码位置 / 可执行文件旁目录，用于用户数据等）
if IS_PACKAGED:
    PROJECT_ROOT = get_executable_dir()
else:
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 获取前端目录路径
# PyInstaller --onefile：静态资源在临时解压目录 sys._MEIPASS/frontend，不在 exe 同目录
if IS_PACKAGED:
    _bundled_frontend = os.path.join(get_base_path(), "frontend")
    if os.path.isdir(_bundled_frontend):
        FRONTEND_DIR = _bundled_frontend
    else:
        FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")
else:
    FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

# 如果前端目录不存在，检查是否在 hotspot 文件夹中（兼容旧目录名）
if not os.path.exists(FRONTEND_DIR) or not os.path.isdir(FRONTEND_DIR):
    # 检查热点文件夹
    HOTSPOT_DIR = os.path.dirname(PROJECT_ROOT)
    if os.path.basename(HOTSPOT_DIR) in ("热点", "hotspot"):
        FRONTEND_DIR = os.path.join(HOTSPOT_DIR, "frontend")
    else:
        # 检查父目录
        PARENT_DIR = os.path.dirname(PROJECT_ROOT)
        FRONTEND_DIR = os.path.join(PARENT_DIR, "frontend")

# 确保前端目录存在
if not os.path.exists(FRONTEND_DIR):
    print(f"[WARNING] 前端目录不存在: {FRONTEND_DIR}")
    # 尝试使用相对路径
    FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "frontend")
    print(f"[INFO] 尝试使用相对路径: {FRONTEND_DIR}")

if IS_PACKAGED:
    # 打包环境：使用用户数据目录
    USER_DATA_DIR = get_user_data_dir()
    DATA_DIR = os.path.join(USER_DATA_DIR, "data")
    LOGS_DIR = os.path.join(USER_DATA_DIR, "logs")
    
    # 内嵌的默认数据目录（PyInstaller 打包时会解压到 _MEIPASS）
    BASE_PATH = get_base_path()
    BUNDLED_DATA_DIR = os.path.join(BASE_PATH, "data")
else:
    # 开发环境：使用项目目录；用户级配置（端口等）放在 hotspot/.kpsr_user
    USER_DATA_DIR = os.path.join(PROJECT_ROOT, ".kpsr_user")
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
    BUNDLED_DATA_DIR = None
    BASE_PATH = PROJECT_ROOT

# 确保目录存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(USER_DATA_DIR, exist_ok=True)


def _parse_port_int(value, default=2345):
    try:
        p = int(value)
        if 1024 <= p <= 65535:
            return p
    except (TypeError, ValueError):
        pass
    return default


# Chromium / Electron 对 http(s) 导航禁止使用的端口（与 net/base/port_util.cc 中受限列表一致的核心子集）
# 典型误用：6666 等 —— 后端可监听，但 BrowserWindow.loadURL 会拒绝，表现为「程序起不来」
CHROMIUM_FORBIDDEN_WEB_PORTS = frozenset(
    {
        1,
        7,
        9,
        11,
        13,
        15,
        17,
        19,
        20,
        21,
        22,
        23,
        25,
        37,
        42,
        43,
        53,
        69,
        77,
        79,
        87,
        95,
        101,
        102,
        103,
        104,
        109,
        110,
        111,
        113,
        115,
        117,
        119,
        123,
        135,
        139,
        143,
        161,
        179,
        389,
        465,
        512,
        513,
        514,
        515,
        526,
        530,
        531,
        532,
        540,
        543,
        544,
        548,
        556,
        563,
        587,
        601,
        636,
        989,
        990,
        993,
        995,
        1719,
        1720,
        1723,
        2049,
        3659,
        4045,
        5060,
        5061,
        6000,
        6568,
        6665,
        6666,
        6667,
        6668,
        6669,
        6697,
        10080,
    }
)


def is_chromium_forbidden_web_port(port: int) -> bool:
    """若为 True，Electron/Chromium 无法加载 http://127.0.0.1:端口/ 本地页。"""
    try:
        return int(port) in CHROMIUM_FORBIDDEN_WEB_PORTS
    except (TypeError, ValueError):
        return True


def get_http_port():
    """
    HTTP 服务端口。优先级：环境变量 KPSR_PORT > USER_DATA_DIR/settings.json 中的 http_port > 默认 2345。
    公司网等场景可为不同电脑配置不同端口，避免同网段多人共用同一端口。
    若配置为 Chromium 禁止端口，仍按配置值解析（不自动改回默认、不写回 settings.json）；
    启动时由 ensure_http_port_allowed_or_exit() 拦截并提示。
    """
    default = 2345
    settings_path = os.path.join(USER_DATA_DIR, "settings.json")

    raw = os.environ.get("KPSR_PORT") or os.environ.get("PORT")
    if raw:
        return _parse_port_int(str(raw).strip(), default)

    try:
        if os.path.isfile(settings_path):
            with open(settings_path, "r", encoding="utf-8") as f:
                j = json.load(f)
            return _parse_port_int(j.get("http_port", default), default)
    except Exception:
        pass
    return default


def ensure_http_port_allowed_or_exit():
    """
    若当前 HTTP_PORT 为 Chromium 禁止端口：向 stderr 输出红色提示并退出。
    不修改 settings.json、不自动回退到其它端口。
    """
    import sys

    p = HTTP_PORT
    if not is_chromium_forbidden_web_port(p):
        return

    msg_lines = [
        "",
        f"[KPSR] 错误：当前 HTTP 端口 {p} 被 Chromium/Electron 禁止用于本地网页，无法启动本服务/内置界面。",
        "[KPSR] 请手动修改环境变量 KPSR_PORT 或用户目录 settings.json 中的 http_port（程序不会自动改回默认端口）。",
        "[KPSR] 可改用例如 2345、8080、9000 等未被禁止的端口。",
        "",
    ]
    for line in msg_lines:
        if getattr(sys.stderr, "isatty", lambda: False)():
            try:
                print(f"\033[31m{line}\033[0m", file=sys.stderr)
            except Exception:
                print(line, file=sys.stderr)
        else:
            print(line, file=sys.stderr)
    sys.exit(1)


def save_http_port(port: int) -> bool:
    """写入 settings.json；需重启后端进程后生效。"""
    if not (1024 <= port <= 65535):
        return False
    if is_chromium_forbidden_web_port(port):
        return False
    try:
        settings_path = os.path.join(USER_DATA_DIR, "settings.json")
        data = {}
        if os.path.isfile(settings_path):
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        data["http_port"] = port
        os.makedirs(USER_DATA_DIR, exist_ok=True)
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


# 进程启动时解析一次；改端口需重启进程
HTTP_PORT = get_http_port()


def init_default_data():
    """
    初始化默认配置文件
    打包后首次运行时，将内嵌的默认配置复制到用户数据目录
    """
    if not IS_PACKAGED or not BUNDLED_DATA_DIR:
        return
    
    if not os.path.exists(BUNDLED_DATA_DIR):
        return
    
    # 首次运行标记文件（使用版本号）
    APP_VERSION = "1.0.1"
    first_run_marker = os.path.join(DATA_DIR, f'.kpsr_initialized_v{APP_VERSION}')
    
    # 检查是否是首次运行
    is_first_run = not os.path.exists(first_run_marker)
    
    if is_first_run:
        print("[KPSR] ========================================")
        print("[KPSR] 检测到首次运行，初始化默认配置...")
        print(f"[KPSR] 数据目录: {DATA_DIR}")
        print(f"[KPSR] 首次运行标记: {first_run_marker}")
        
        # 确保目录存在
        os.makedirs(DATA_DIR, exist_ok=True)
        
        # 创建首次运行标记文件
        try:
            with open(first_run_marker, 'w', encoding='utf-8') as f:
                f.write('initialized')
            print("[KPSR] ✅ 已创建首次运行标记")
        except Exception as e:
            print(f"[KPSR] ⚠️ 创建首次运行标记失败: {e}")
        
        print("[KPSR] ========================================")
    
    # 排除：激活状态仅由运行时生成，绝不从安装包内「种」进用户目录（避免误提交 activated:true 或本机测试状态被复制）
    excluded_files = ["activation.json"]
    
    # 复制默认配置文件（如果目标不存在）
    for filename in os.listdir(BUNDLED_DATA_DIR):
        # 跳过排除的文件
        if filename in excluded_files:
            continue
            
        src = os.path.join(BUNDLED_DATA_DIR, filename)
        dst = os.path.join(DATA_DIR, filename)
        
        # 只在目标文件不存在时复制（保护用户已有配置）
        if os.path.isfile(src) and not os.path.exists(dst):
            try:
                shutil.copy2(src, dst)
                print(f"[KPSR] 已初始化默认配置: {filename}")
            except Exception as e:
                print(f"[KPSR] 复制配置失败 {filename}: {e}")


# 初始化默认数据
init_default_data()

print(f"[KPSR] 运行模式: {'打包环境' if IS_PACKAGED else '开发环境'}")
print(f"[KPSR] 数据目录: {DATA_DIR}")
print(f"[KPSR] 日志目录: {LOGS_DIR}")
print(f"[KPSR] HTTP 端口: {HTTP_PORT}")

__all__ = [
    "PROJECT_ROOT",
    "FRONTEND_DIR",
    "DATA_DIR",
    "LOGS_DIR",
    "IS_PACKAGED",
    "USER_DATA_DIR",
    "HTTP_PORT",
    "get_http_port",
    "save_http_port",
    "CHROMIUM_FORBIDDEN_WEB_PORTS",
    "is_chromium_forbidden_web_port",
    "ensure_http_port_allowed_or_exit",
]
