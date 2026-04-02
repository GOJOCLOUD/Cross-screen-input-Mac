#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
平台工具模块
支持 macOS / Windows / Linux
"""

import subprocess
import re
import platform as _platform
from pynput.keyboard import Key

_system = _platform.system()
CURRENT_PLATFORM = 'macos' if _system == 'Darwin' else ('windows' if _system == 'Windows' else 'linux')
IS_WINDOWS = _system == 'Windows'
IS_MAC = _system == 'Darwin'
IS_LINUX = _system == 'Linux'


def get_platform():
    """
    检测操作系统平台
    返回: 'macos' | 'windows' | 'linux'
    """
    return CURRENT_PLATFORM


def get_modifier_key_map():
    """
    获取当前平台修饰键映射
    """
    if IS_MAC:
        return {
            'ctrl': Key.ctrl,
            'cmd': Key.cmd,
            'win': Key.cmd,
            'shift': Key.shift,
            'alt': Key.alt,
        }
    # Windows / Linux
    return {
        'ctrl': Key.ctrl,
        'cmd': Key.cmd,   # pynput 上 Win 键为 Key.cmd
        'win': Key.cmd,
        'shift': Key.shift,
        'alt': Key.alt,
    }


def _get_windows_machine_guid_registry():
    """读取 Windows MachineGuid（注册表），打包/无 wmic 环境下最稳定。"""
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
        )
        try:
            val, _ = winreg.QueryValueEx(key, "MachineGuid")
            if val and isinstance(val, str) and len(val.strip()) >= 8:
                return val.strip()
        finally:
            winreg.CloseKey(key)
    except Exception:
        pass
    return None


def _get_windows_cim_uuid():
    """PowerShell Get-CimInstance Win32_ComputerSystemProduct.UUID（无 wmic 时可用）。"""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(Get-CimInstance -ClassName Win32_ComputerSystemProduct).UUID",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        out = (result.stdout or "").strip()
        if out and len(out) >= 8 and "failed" not in out.lower():
            return out
    except Exception:
        pass
    return None


def get_motherboard_uuid():
    """
    获取设备唯一标识（用于激活）
    macOS: ioreg IOPlatformUUID
    Windows:
      1) 优先 HKLM\\...\\Cryptography MachineGuid（与启动方式无关，最稳定）
      2) 其次 CIM Win32_ComputerSystemProduct.UUID
      3) 最后回退为环境变量哈希（历史兼容；若从 Electron 与从终端启动时环境变量不一致，会得到不同哈希）
    """
    if IS_MAC:
        try:
            result = subprocess.run(
                ['ioreg', '-d2', '-c', 'IOPlatformExpertDevice'],
                capture_output=True,
                text=True,
                timeout=5
            )
            uuid_match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', result.stdout or '')
            if uuid_match:
                return uuid_match.group(1)
            return "获取UUID失败"
        except Exception as e:
            return f"错误: {str(e)}"

    if IS_WINDOWS:
        # 与「改端口」无关：旧版仅用环境变量做哈希，Electron 子进程环境常与 CMD 不一致 → UUID 会变
        mid = _get_windows_machine_guid_registry()
        if mid:
            return mid
        mid = _get_windows_cim_uuid()
        if mid:
            return mid
        # 历史回退（不推荐；仅当注册表/CIM 均不可用时）
        try:
            import hashlib
            import os

            computer_name = os.environ.get("COMPUTERNAME", "")
            user = os.environ.get("USERNAME", "")
            user_domain = os.environ.get("USERDOMAIN", "")
            processor_id = os.environ.get("PROCESSOR_IDENTIFIER", "")

            raw = f"{computer_name}|{user}|{user_domain}|{processor_id}|windows"
            if raw.strip("|"):
                return hashlib.sha256(raw.encode("utf-8")).hexdigest()
        except Exception:
            pass

        import hashlib
        return hashlib.sha256(b"unknown-windows-machine").hexdigest()

    # Linux
    try:
        with open('/etc/machine-id', 'r') as f:
            return f.read().strip() or "获取UUID失败"
    except Exception:
        pass
    try:
        with open('/var/lib/dbus/machine-id', 'r') as f:
            return f.read().strip() or "获取UUID失败"
    except Exception:
        return "获取UUID失败"


# 预加载修饰键映射
MODIFIER_KEY_MAP = get_modifier_key_map()


__all__ = [
    'get_platform',
    'get_modifier_key_map',
    'get_motherboard_uuid',
    'CURRENT_PLATFORM',
    'IS_WINDOWS',
    'IS_MAC',
    'IS_LINUX',
    'MODIFIER_KEY_MAP',
]
