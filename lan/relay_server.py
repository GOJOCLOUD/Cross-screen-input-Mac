#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KPSR 局域网中转服务器（独立进程）
负责在「电脑」与「手机」之间中转指令。

当前实现目标：
- 支持 PC / Phone 两类角色通过 WebSocket 连接
- 支持最简单的 1 对 1 配对与 command 消息转发
- 配对信息与连接信息只保存在内存，不落库
- 提供管理界面查看连接状态
- 心跳保活：服务端定期发 ping，避免 NAT/路由器/休眠导致空闲断连
"""

import asyncio
import uuid
from typing import Dict

# 心跳间隔（秒），略小于常见 NAT 超时（30s～2min），避免空闲断连
PING_INTERVAL = 25

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


app = FastAPI(title="KPSR 局域网中转站", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Connection:
    def __init__(self, websocket: WebSocket, role: str, device_id: str):
        self.websocket = websocket
        self.role = role
        self.device_id = device_id


pcs: Dict[str, Connection] = {}
phones: Dict[str, Connection] = {}
phone_to_pc: Dict[str, str] = {}
pc_to_phone: Dict[str, str] = {}


def _get_status() -> dict:
    """获取当前连接与配对状态"""
    pairings = [
        {"pc_id": pc_id, "phone_id": phone_id}
        for pc_id, phone_id in pc_to_phone.items()
    ]
    return {
        "status": "ok",
        "pcs": list(pcs.keys()),
        "phones": list(phones.keys()),
        "pairings": pairings,
        "pc_count": len(pcs),
        "phone_count": len(phones),
    }


async def _safe_send(ws: WebSocket, data) -> None:
    try:
        await ws.send_json(data)
    except Exception:
        # 对于中转站来说，发送失败就静默忽略即可
        pass


@app.get("/")
async def root() -> HTMLResponse:
    """返回管理界面"""
    return HTMLResponse(content=_admin_html())


@app.get("/health")
async def health() -> dict:
    """简单健康检查，便于排查问题"""
    return {"status": "ok", "pcs": len(pcs), "phones": len(phones)}


@app.get("/api/status")
async def api_status() -> dict:
    """管理界面用：返回详细连接状态"""
    return _get_status()


def _admin_html() -> str:
    """管理界面 HTML"""
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>KPSR 中转站管理</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e8e8e8;
            min-height: 100vh;
            padding: 32px 24px;
        }
        .container { max-width: 640px; margin: 0 auto; }
        .header {
            text-align: center;
            margin-bottom: 32px;
        }
        .header h1 { font-size: 24px; font-weight: 600; margin-bottom: 4px; }
        .header p { font-size: 13px; color: #8892a6; }
        .card {
            background: rgba(255,255,255,0.06);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 20px;
        }
        .card-title {
            font-size: 14px; font-weight: 600;
            color: #a0aec0;
            margin-bottom: 16px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .status-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .status-row:last-child { border-bottom: none; }
        .status-label { color: #a0aec0; font-size: 14px; }
        .status-value { font-weight: 500; font-size: 15px; }
        .status-value.ok { color: #48bb78; }
        .status-value.warn { color: #ecc94b; }
        .list-item {
            padding: 10px 14px;
            background: rgba(0,0,0,0.2);
            border-radius: 8px;
            margin-bottom: 8px;
            font-family: monospace;
            font-size: 13px;
            word-break: break-all;
        }
        .list-item:last-child { margin-bottom: 0; }
        .pairing-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 14px;
            background: rgba(72, 187, 120, 0.1);
            border: 1px solid rgba(72, 187, 120, 0.3);
            border-radius: 8px;
            margin-bottom: 8px;
            font-size: 13px;
        }
        .pairing-item .arrow { color: #48bb78; font-weight: bold; }
        .empty { color: #6b7280; font-size: 13px; padding: 16px 0; }
        .refresh-btn {
            display: block;
            width: 100%;
            padding: 14px;
            margin-top: 8px;
            background: rgba(99, 102, 241, 0.3);
            border: 1px solid rgba(99, 102, 241, 0.5);
            border-radius: 8px;
            color: #a5b4fc;
            font-size: 14px;
            cursor: pointer;
            transition: background 0.2s;
        }
        .refresh-btn:hover { background: rgba(99, 102, 241, 0.5); }
        .dot {
            display: inline-block;
            width: 8px; height: 8px;
            border-radius: 50%;
            background: #48bb78;
            margin-right: 8px;
            animation: pulse 2s infinite;
        }
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <h1>KPSR 中转站管理</h1>
            <p>局域网中转站 · 端口 9000</p>
        </header>

        <div class="card">
            <div class="card-title">服务状态</div>
            <div class="status-row">
                <span class="status-label">运行状态</span>
                <span class="status-value ok"><span class="dot"></span>运行中</span>
            </div>
            <div class="status-row">
                <span class="status-label">已连接电脑</span>
                <span class="status-value" id="pcCount">0</span>
            </div>
            <div class="status-row">
                <span class="status-label">已连接手机</span>
                <span class="status-value" id="phoneCount">0</span>
            </div>
            <div class="status-row">
                <span class="status-label">已配对</span>
                <span class="status-value" id="pairCount">0</span>
            </div>
        </div>

        <div class="card">
            <div class="card-title">已连接电脑 (PC)</div>
            <div id="pcList"></div>
        </div>

        <div class="card">
            <div class="card-title">已连接手机 (Phone)</div>
            <div id="phoneList"></div>
        </div>

        <div class="card">
            <div class="card-title">配对关系</div>
            <div id="pairList"></div>
        </div>

        <button class="refresh-btn" onclick="loadStatus()">刷新状态</button>
    </div>

    <script>
        async function loadStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                document.getElementById('pcCount').textContent = data.pc_count || 0;
                document.getElementById('phoneCount').textContent = data.phone_count || 0;
                document.getElementById('pairCount').textContent = (data.pairings || []).length;

                const pcList = document.getElementById('pcList');
                if (data.pcs && data.pcs.length) {
                    pcList.innerHTML = data.pcs.map(id => '<div class="list-item">' + id + '</div>').join('');
                } else {
                    pcList.innerHTML = '<div class="empty">暂无连接</div>';
                }

                const phoneList = document.getElementById('phoneList');
                if (data.phones && data.phones.length) {
                    phoneList.innerHTML = data.phones.map(id => '<div class="list-item">' + id + '</div>').join('');
                } else {
                    phoneList.innerHTML = '<div class="empty">暂无连接</div>';
                }

                const pairList = document.getElementById('pairList');
                if (data.pairings && data.pairings.length) {
                    pairList.innerHTML = data.pairings.map(p =>
                        '<div class="pairing-item">' + p.pc_id + ' <span class="arrow">↔</span> ' + p.phone_id + '</div>'
                    ).join('');
                } else {
                    pairList.innerHTML = '<div class="empty">暂无配对</div>';
                }
            } catch (e) {
                console.error(e);
            }
        }
        loadStatus();
        setInterval(loadStatus, 3000);
    </script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
@app.get("/index", response_class=HTMLResponse)
@app.get("/manage", response_class=HTMLResponse)
async def admin_page() -> HTMLResponse:
    """中转站管理界面"""
    return HTMLResponse(content=_admin_html())


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc: StarletteHTTPException):
    """404 时重定向到管理界面，避免显示 detail not found"""
    if exc.status_code == 404:
        return RedirectResponse(url="/", status_code=302)
    from starlette.responses import JSONResponse
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc.detail)})


async def _ping_loop(websocket: WebSocket) -> None:
    """后台任务：定期发送 ping，保持连接不被 NAT/路由器/休眠掐断"""
    try:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            await _safe_send(websocket, {"type": "ping"})
    except asyncio.CancelledError:
        raise
    except Exception:
        pass


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket 入口：
    - 首条消息必须是 type=register，用于声明角色与设备 ID
    - 之后处理 type=command 转发，type=pong 忽略（心跳回应）
    - 后台定时发 type=ping，避免空闲断连
    """
    await websocket.accept()
    conn: Connection | None = None
    ping_task: asyncio.Task | None = None

    try:
        first = await websocket.receive_json()
        if first.get("type") != "register":
            await _safe_send(
                websocket,
                {"type": "error", "message": "first message must be 'register'"},
            )
            await websocket.close()
            return

        role = first.get("role")
        device_id = first.get("id") or str(uuid.uuid4())

        conn = Connection(websocket, role, device_id)

        if role == "pc":
            # 电脑端：记录连接，并返回一个可供展示/扫码的 pc_id
            pcs[device_id] = conn
            await _safe_send(
                websocket,
                {"type": "registered", "pc_id": device_id, "pair_code": device_id},
            )
        elif role == "phone":
            # 手机端：使用 pair_code 指明要连接哪台 PC
            phones[device_id] = conn
            pair_code = first.get("pair_code")
            target_pc_id = None

            if pair_code and pair_code in pcs:
                target_pc_id = pair_code
                phone_to_pc[device_id] = target_pc_id
                pc_to_phone[target_pc_id] = device_id
                await _safe_send(
                    websocket,
                    {"type": "paired", "pc_id": target_pc_id, "phone_id": device_id},
                )
                await _safe_send(
                    pcs[target_pc_id].websocket,
                    {"type": "phone_paired", "phone_id": device_id},
                )
            else:
                await _safe_send(
                    websocket,
                    {"type": "waiting_pair", "message": "invalid or missing pair_code"},
                )
        else:
            await _safe_send(
                websocket,
                {"type": "error", "message": f"unknown role: {role}"},
            )

        # 启动心跳任务，防止长时间无数据被 NAT/路由器断开
        ping_task = asyncio.create_task(_ping_loop(websocket))

        # 主循环：处理 command 转发，忽略 pong
        while True:
            msg = await websocket.receive_json()
            msg_type = msg.get("type")

            if msg_type == "pong":
                continue
            if msg_type != "command" or conn is None:
                continue

            sender_id = conn.device_id

            if conn.role == "phone":
                pc_id = phone_to_pc.get(sender_id)
                target = pcs.get(pc_id) if pc_id else None
                if target:
                    await _safe_send(target.websocket, msg)
            elif conn.role == "pc":
                phone_id = pc_to_phone.get(sender_id)
                target = phones.get(phone_id) if phone_id else None
                if target:
                    await _safe_send(target.websocket, msg)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if ping_task is not None and not ping_task.done():
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass
        if conn is not None:
            if conn.role == "pc":
                pcs.pop(conn.device_id, None)
                phone_id = pc_to_phone.pop(conn.device_id, None)
                if phone_id:
                    phone_to_pc.pop(phone_id, None)
            elif conn.role == "phone":
                phones.pop(conn.device_id, None)
                pc_id = phone_to_pc.pop(conn.device_id, None)
                if pc_id:
                    pc_to_phone.pop(pc_id, None)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("relay_server:app", host="0.0.0.0", port=9000, reload=False)

