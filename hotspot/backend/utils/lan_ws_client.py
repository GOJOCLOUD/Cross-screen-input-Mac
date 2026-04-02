#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
局域网中转站 WebSocket 客户端（电脑端）

职责：
- 在局域网模式下，作为 PC 端连接到中转服务器 /ws
- 发送 register 消息，标识当前电脑的 pc_id
- 持续接收来自中转站的 command 消息（当前仅打印日志，后续可对接执行逻辑）
"""

import asyncio
import json
import threading
from typing import Optional

import websockets

from .logger import app_logger


_client_thread: Optional[threading.Thread] = None
_running = False


def _run_client_loop(relay_ws_url: str, pc_id: str) -> None:
    async def client():
        nonlocal relay_ws_url, pc_id
        while _running:
            try:
                app_logger.info(f"连接局域网中转站: {relay_ws_url}", "lan_ws_client")
                # ping_interval/ping_timeout 保持连接活跃，避免 NAT/路由器空闲断连
                async with websockets.connect(
                    relay_ws_url,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                ) as ws:
                    # 注册当前电脑
                    register_msg = {
                        "type": "register",
                        "role": "pc",
                        "id": pc_id,
                    }
                    await ws.send(json.dumps(register_msg))
                    app_logger.info(
                        f"已向中转站注册 PC: pc_id={pc_id}", "lan_ws_client"
                    )

                    # 循环接收消息（当前仅打印日志）
                    async for message in ws:
                        try:
                            data = json.loads(message)
                        except Exception:
                            app_logger.error(
                                f"收到无法解析的消息: {message}", "lan_ws_client"
                            )
                            continue

                        msg_type = data.get("type")
                        if msg_type == "ping":
                            await ws.send(json.dumps({"type": "pong"}))
                            continue
                        if msg_type == "command":
                            cmd_type = data.get("command_type") or data.get("commandType")
                            payload = data.get("payload") or {}
                            try:
                                from .command_executor import execute_command
                                execute_command(cmd_type or "", payload)
                                app_logger.info(
                                    f"已执行 command: {cmd_type}", "lan_ws_client"
                                )
                            except Exception as e:
                                app_logger.error(
                                    f"执行 command 失败: {e}", "lan_ws_client"
                                )
                        else:
                            app_logger.info(
                                f"收到中转站消息: {data}", "lan_ws_client"
                            )
            except Exception as e:
                app_logger.error(f"连接中转站失败: {e}", "lan_ws_client")

            # 等待一段时间再重连，避免频繁重试
            if _running:
                await asyncio.sleep(5)

    asyncio.run(client())


def start_lan_ws_client(relay_ws_url: str, pc_id: str) -> None:
    """
    启动到局域网中转站的 WebSocket 客户端（幂等调用）。
    """
    global _client_thread, _running
    if _client_thread and _client_thread.is_alive():
        return

    _running = True
    _client_thread = threading.Thread(
        target=_run_client_loop, args=(relay_ws_url, pc_id), daemon=True
    )
    _client_thread.start()
    app_logger.info("已启动局域网中转站 WebSocket 客户端线程", "lan_ws_client")


def stop_lan_ws_client() -> None:
    """停止客户端（当前仅用于将来扩展）。"""
    global _running
    _running = False


__all__ = ["start_lan_ws_client", "stop_lan_ws_client"]

