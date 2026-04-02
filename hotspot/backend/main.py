#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI主应用
统一管理所有后端功能，包括剪贴板操作和页面跳转
"""

# 标准库
import os
import subprocess
import re
import json
from contextlib import asynccontextmanager

# 第三方库
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, Response, JSONResponse
from pydantic import BaseModel

# Lifespan 上下文管理器
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    from config import ensure_http_port_allowed_or_exit

    ensure_http_port_allowed_or_exit()
    # 启动事件
    print("\n[INFO] 正在启动鼠标按键监听器...")
    try:
        from routes.mouse_listener import start_listener
        result = start_listener()
        if result.get('success'):
            print("[SUCCESS] 鼠标按键监听器已启动")
        else:
            print(f"[WARNING] 鼠标监听器启动失败: {result.get('message', '未知错误')}")
    except Exception as e:
        print(f"[WARNING] 鼠标监听器启动失败: {e}")
    
    yield
    
    # 关闭事件
    try:
        from routes.mouse_listener import stop_listener
        stop_listener()
        print("[INFO] 鼠标监听器已停止")
    except Exception as e:
        print(f"[WARNING] 停止监听器失败: {e}")

# 创建FastAPI应用实例
app = FastAPI(
    title="跨屏输入API",
    description="统一管理剪贴板操作和页面跳转的后端API",
    version="1.0.0",
    lifespan=lifespan
)

# 配置CORS
# 注意：由于是本地网络应用（热点网络），允许所有来源是合理的
# 但可以通过环境变量控制（如果需要更严格的限制）
cors_origins = os.environ.get("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if cors_origins != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 从 config.py 导入路径配置与 HTTP 端口（可由环境变量 / settings.json 配置）
from config import PROJECT_ROOT, FRONTEND_DIR, HTTP_PORT

# 挂载前端静态文件
if os.path.exists(FRONTEND_DIR):
    app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")

# 导入路由模块
from routes import (
    clipboard,
    shortcut,
    button_config,
    logs,
    monitor,
    mouse,
    mouse_config,
    mouse_listener,
    desktop_api,
    activation,
    interceptor,
    lan_relay,
)

# 注册路由
app.include_router(clipboard.router, prefix="/api/clipboard", tags=["clipboard"])
app.include_router(shortcut.router, prefix="/api/shortcut", tags=["shortcut"])
app.include_router(button_config.router, prefix="/api/button-config", tags=["button-config"])
app.include_router(logs.router, prefix="/api/logs", tags=["logs"])
app.include_router(monitor.router, prefix="/api/monitor", tags=["monitor"])
app.include_router(mouse.router, prefix="/api/mouse", tags=["mouse"])
app.include_router(mouse_config.router, prefix="/api/mouse-config", tags=["mouse-config"])
app.include_router(mouse_listener.router, prefix="/api/mouse-listener", tags=["mouse-listener"])
app.include_router(desktop_api.router, prefix="/api/desktop", tags=["desktop"])
app.include_router(activation.router, prefix="/api/activation", tags=["activation"])
app.include_router(interceptor.router, prefix="/api/interceptor", tags=["interceptor"])
app.include_router(lan_relay.router, prefix="/lan", tags=["lan-relay"])

# 根路径返回desktop.html（仅限本机访问）
@app.get("/", response_class=HTMLResponse)
async def root(request: Request) -> HTMLResponse:
    """返回电脑端主页面（仅限127.0.0.1访问）"""
    client_ip = request.client.host
    
    # 电脑端界面只能本机访问（含 IPv6 localhost）
    if client_ip not in ("127.0.0.1", "::1"):
        return HTMLResponse(
            content="<h1>403 Forbidden</h1><p>电脑端控制台仅限本机访问，请使用 /phone 访问手机界面</p>",
            status_code=403
        )
    
    print(f"[DEBUG] FRONTEND_DIR: {FRONTEND_DIR}")
    desktop_html_path = os.path.join(FRONTEND_DIR, "desktop.html")
    print(f"[DEBUG] desktop_html_path: {desktop_html_path}")
    print(f"[DEBUG] os.path.exists(desktop_html_path): {os.path.exists(desktop_html_path)}")
    print(f"[DEBUG] os.path.isfile(desktop_html_path): {os.path.isfile(desktop_html_path)}")
    
    if os.path.exists(desktop_html_path):
        try:
            with open(desktop_html_path, "r", encoding="utf-8") as f:
                content = f.read()
            print(f"[DEBUG] 成功读取 desktop.html，长度: {len(content)}")
            return HTMLResponse(content=content)
        except Exception as e:
            print(f"[ERROR] 读取 desktop.html 失败: {str(e)}")
            return HTMLResponse(content=f"<h1>跨屏输入</h1><p>读取前端文件失败: {str(e)}</p>")
    return HTMLResponse(content="<h1>跨屏输入</h1><p>前端文件未找到</p>")


def _forbid_phone_surface_if_unactivated(request: Request):
    """未激活时，非本机不得获取手机页（避免拼链接访问）。不区分网段，私有网络场景一律同策略。"""
    client_ip = request.client.host
    if client_ip in ("127.0.0.1", "::1"):
        return None
    try:
        from routes.activation import load_activation_status as _load_act_file

        if _load_act_file().get("activated"):
            return None
    except Exception:
        return None
    return HTMLResponse(
        status_code=403,
        content=(
            "<!DOCTYPE html><html><head><meta charset='utf-8'><title>需要激活</title></head>"
            "<body style='font-family:system-ui;padding:24px;text-align:center'>"
            "<h2>当前不可用</h2><p>请激活后使用手机端。</p></body></html>"
        ),
        media_type="text/html; charset=utf-8",
    )


# phone路径返回phone.html
@app.get("/phone", response_class=HTMLResponse)
async def phone(request: Request) -> HTMLResponse:
    """返回手机端主页面"""
    blocked = _forbid_phone_surface_if_unactivated(request)
    if blocked is not None:
        return blocked
    phone_html_path = os.path.join(FRONTEND_DIR, "phone.html")
    if os.path.exists(phone_html_path):
        with open(phone_html_path, "r", encoding="utf-8") as f:
            content = f.read()
        return HTMLResponse(content=content)
    return HTMLResponse(content="<h1>跨屏输入</h1><p>前端文件未找到</p>")


# send路径返回phone.html（GET请求）
@app.get("/send", response_class=HTMLResponse)
async def send(request: Request) -> HTMLResponse:
    """返回手机端主页面（兼容旧路径）"""
    return await phone(request)

# 定义请求模型
class SendRequest(BaseModel):
    """发送请求的数据模型"""
    msg: str


# send路径处理POST请求，实现复制到剪贴板功能
@app.post("/send")
async def send_post(request: Request) -> dict:
    """处理POST请求，复制文本到剪贴板"""
    from routes.clipboard import copy_to_clipboard
    
    try:
        body = await request.json()
        copy_data = SendRequest(**body)
        
        # 调用剪贴板功能
        result = await copy_to_clipboard(request, copy_data)
        # 转换为字典
        return result.dict() if hasattr(result, 'dict') else result
    except Exception as e:
        return {
            "status": "error",
            "message": f"处理请求失败: {str(e)}"
        }

# 拦截器中间件
@app.middleware("http")
async def request_interceptor_middleware(request: Request, call_next) -> Response:
    """请求拦截器中间件（对桌面/激活接口放行，并在异常时不阻塞请求）"""
    from utils.interceptor import interceptor

    path = request.url.path
    method = request.method

    # 对桌面控制台与激活相关接口完全放行，避免这里出问题影响基础功能
    if path.startswith("/api/desktop/") or path.startswith("/api/activation/"):
        return await call_next(request)

    # 获取客户端信息
    client_ip = request.client.host

    # 读取请求体（仅对写操作）；读完后必须重新注入 Request，否则路由里 request.json() 读不到 body
    body = None
    body_raw = None
    try:
        if method in ["POST", "PUT", "PATCH"]:
            body_raw = await request.body()
            body = body_raw.decode("utf-8") if body_raw else ""
    except Exception:
        body = None

    request_info = {
        "client_ip": client_ip,
        "path": path,
        "method": method,
        "body": body,
    }

    try:
        blocked, reason = interceptor.should_block(request_info)
        interceptor.log_request(request_info, blocked, reason)
    except Exception as e:
        # 拦截器自身异常时，只记录错误，不拦截请求，避免导致前端 Failed to fetch
        try:
            from utils.logger import app_logger

            app_logger.error(f"拦截器执行异常: {e}", "interceptor_middleware")
        except Exception:
            pass
        blocked = False
        reason = "interceptor_error"

    if blocked:
        return JSONResponse(
            status_code=403,
            content={
                "detail": "Forbidden: Request blocked by interceptor",
                "reason": reason,
                "path": path,
                "method": method,
            },
        )

    # 若已消费过 body，替换为可再次读取的 Request，否则 /send 等路由的 request.json() 会拿到空
    if body_raw is not None:
        async def _receive():
            return {"type": "http.request", "body": body_raw}

        request = Request(request.scope, _receive)

    return await call_next(request)

# 全局访问控制中间件（由当前中转站决定是否放行）
@app.middleware("http")
async def private_network_only(request: Request, call_next) -> Response:
    """只允许当前中转站策略允许的访问"""
    from utils.relay_station import get_current_station

    client_ip = request.client.host
    if not get_current_station().is_request_allowed(client_ip):
        return JSONResponse(
            status_code=403,
            content={
                "detail": "Forbidden: Only private network and local access allowed",
                "message": "请确保您的设备连接到私有网络",
                "allowed_networks": ["10.x.x.x", "172.16.x.x-172.31.x.x", "192.168.x.x", "localhost"],
            },
        )
    response = await call_next(request)
    return response


@app.middleware("http")
async def hotspot_block_static_phone_html(request: Request, call_next):
    """禁止绕过 /phone 直接访问 /frontend/phone.html（未激活且非本机时）。"""
    if request.method not in ("GET", "HEAD"):
        return await call_next(request)
    path = request.url.path.replace("\\", "/")
    if path.rstrip("/") != "/frontend/phone.html":
        return await call_next(request)
    blocked = _forbid_phone_surface_if_unactivated(request)
    if blocked is not None:
        return blocked
    return await call_next(request)


# 健康检查端点
@app.get("/health")
async def health_check() -> dict:
    """返回服务健康状态"""
    from utils.relay_station import get_current_station

    return {
        "status": "healthy",
        "message": "服务运行正常",
        "local_ip": get_current_station().get_local_ip(),
    }

if __name__ == "__main__":
    import uvicorn
    import sys

    from config import ensure_http_port_allowed_or_exit
    from utils.relay_station import init_relay_station

    ensure_http_port_allowed_or_exit()

    # 检测是否在打包环境中运行
    is_frozen = getattr(sys, "frozen", False)

    # 端口由 KPSR_PORT / settings.json 决定，启动前自动清理占用该端口的进程
    port = HTTP_PORT

    # 初始化当前中转站（默认自动根据网络选择）
    init_relay_station(mode="auto", port=port)

    # 清理占用端口的进程
    try:
        from utils.port_manager import kill_process_on_port

        if not kill_process_on_port(port):
            print(f"[WARNING] 清理端口 {port} 失败，可能无法启动服务")
        else:
            import time

            time.sleep(0.5)  # 等待进程完全退出
    except Exception as e:
        print(f"[WARNING] 清理端口时出错: {e}")

    from utils.relay_station import get_current_station

    local_ip = get_current_station().get_local_ip()
    
    # 显示localhost和私有网络地址
    print("=" * 60)
    print("FastAPI服务器启动信息")
    print("=" * 60)
    print(f"服务端口: {port}")
    print("服务地址:")
    print(f"  - http://localhost:{port}")
    
    # 获取所有网络接口的私有IP地址（按平台）
    try:
        import platform as _plat
        out = ""
        if _plat.system() == "Windows":
            result = subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=5)
            out = result.stdout or ""
            private_ips = re.findall(r"IPv4[^\d]*(10\.\d+\.\d+\.\d+)", out)
            private_ips.extend(re.findall(r"IPv4[^\d]*(172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)", out))
            private_ips.extend(re.findall(r"IPv4[^\d]*(192\.168\.\d+\.\d+)", out))
        else:
            result = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5)
            out = result.stdout or ""
            private_ips = re.findall(r"inet (10\.\d+\.\d+\.\d+)", out)
            private_ips.extend(re.findall(r"inet (172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)", out))
            private_ips.extend(re.findall(r"inet (192\.168\.\d+\.\d+)", out))
        unique_private_ips = list(set(private_ips))
        for ip in unique_private_ips:
            print(f"  - http://{ip}:{port}")
    except Exception as e:
        print(f"[WARNING] 获取私有IP地址失败: {e}")
    
    print("")
    print("重要说明:")
    print("  - 本服务只允许电脑本机访问和私有网络访问")
    print("  - 请将您的手机连接到与电脑相同的私有网络")
    print("  - 然后在手机浏览器中使用私有网络地址访问")
    print(f"  - 私有网络地址格式: 10.x.x.x:{port}, 172.16.x.x-{port}, 192.168.x.x:{port}")
    print(f"  - 当前 HTTP 端口: {port}")
    print("")
    print("可用端点:")
    print("  - GET /              : 跨屏输入主页面")
    print("  - GET /send          : 跨屏输入主页面")
    print("  - POST /send         : 复制文本到剪贴板（核心功能）")
    print("  - GET /frontend/*    : 前端静态文件")
    print("  - POST /api/clipboard/copy : 复制文本到剪贴板")
    print("  - POST /api/shortcut/execute : 执行键盘快捷键")
    print("  - POST /api/mouse/execute : 执行鼠标操作")
    print("  - GET /api/mouse/buttons : 获取支持的鼠标按键列表")
    print("  - GET /api/mouse/platform : 获取平台信息和建议")
    print("  - GET /api/mouse-config/list : 获取鼠标按钮列表")
    print("  - POST /api/mouse-config/add : 添加新鼠标按钮")
    print("  - PUT /api/mouse-config/update/{id} : 更新鼠标按钮")
    print("  - DELETE /api/mouse-config/delete/{id} : 删除鼠标按钮")
    print("  - GET /api/mouse-config/get/{id} : 获取单个鼠标按钮")
    print("  - GET /api/button-config/list : 获取按钮列表")
    print("  - POST /api/button-config/add : 添加新按钮")
    print("  - PUT /api/button-config/update/{id} : 更新按钮")
    print("  - DELETE /api/button-config/delete/{id} : 删除按钮")
    print("  - GET /api/button-config/get/{id} : 获取单个按钮")
    print("  - GET /health        : 健康检查")
    print("=" * 60)
    
    # 启动服务器
    # 禁用 reload 模式以避免鼠标监听器线程问题
    uvicorn.run(app, host="0.0.0.0", port=port, loop="asyncio", log_level="info")
