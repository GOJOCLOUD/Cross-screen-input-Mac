#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从中转站收到的 command 在电脑端执行（剪贴板 / 快捷键 / 鼠标）
供 lan_ws_client 调用，与 HTTP 路由共用同一套执行逻辑。
"""

from typing import Any, Dict


def execute_command(command_type: str, payload: Dict[str, Any]) -> None:
    """
    根据 command_type 和 payload 执行对应操作。
    payload 格式与前端/中转约定一致。
    """
    if command_type == "clipboard":
        text = (payload or {}).get("text") or (payload or {}).get("msg") or ""
        if not text:
            return
        import pyperclip
        pyperclip.copy(text)

    elif command_type == "shortcut":
        shortcut = (payload or {}).get("shortcut", "").strip()
        if not shortcut:
            return
        from routes.shortcut import execute_shortcut
        execute_shortcut(shortcut)

    elif command_type == "mouse":
        action = (payload or {}).get("action", "").strip()
        if not action:
            return
        from routes.mouse import execute_mouse_action
        execute_mouse_action(action)

    else:
        pass  # 未知类型忽略


__all__ = ["execute_command"]
