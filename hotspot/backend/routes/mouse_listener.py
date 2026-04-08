#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
鼠标按键监听服务
监听电脑上的鼠标按键事件，执行对应的快捷键映射
支持 macOS（Quartz）与 Windows（Win32 低级钩子）
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import threading
import sys
import os
import platform
import ctypes

# 添加路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入日志模块
from utils.logger import app_logger
from utils.platform_utils import get_platform

from pynput.keyboard import Key, Controller as KeyboardController

router = APIRouter()

# 键盘控制器
keyboard_controller = KeyboardController()

# 监听器状态
listener_thread = None
is_listening = False
_platform = get_platform()
is_mac = _platform == 'macos'
is_windows = _platform == 'windows'

# 权限状态
has_permission = None  # None=未检测, True=有权限, False=无权限
permission_message = ""
_mac_permission_prompted_once = False
_listener_state_lock = threading.Lock()
_mac_start_ready_event = None
_mac_start_ok = False


def _mac_accessibility_target_path() -> str:
    """返回当前发起辅助功能请求的可执行文件路径（用于提示用户精确授权对象）。"""
    try:
        if getattr(sys, "frozen", False):
            return os.path.abspath(sys.executable)
    except Exception:
        pass
    return os.path.abspath(sys.executable or "")

# 鼠标按键映射
button_mappings = {}  # 单键映射: {keyType: action}
sequence_mappings = []  # 序列映射: [{sequence: [key1, key2], action: action}, ...]

# 按键序列检测相关
import time
key_history = []  # 按键历史: [(key_type, timestamp), ...]
SEQUENCE_TIMEOUT = 0.5  # 序列超时时间（秒）
# 与 SEQUENCE_TIMEOUT 必须一致：若更短，会在「序列第二键尚未按下」时就执行单键映射，导致误触发并破坏序列判定
SINGLE_KEY_DELAY = SEQUENCE_TIMEOUT
pending_single_key = None  # 待处理的单键: (key_type, action, timestamp)
pending_timer = None  # 待处理的定时器

def load_mappings():
    """从配置文件加载鼠标按键映射（支持单键和序列）"""
    global button_mappings, sequence_mappings
    try:
        from routes.mouse_config import load_buttons
        buttons = load_buttons()
        button_mappings = {}
        sequence_mappings = []
        
        for btn in buttons:
            action = btn.get('action')
            if not action:
                continue
                
            # 检查是否是序列配置
            sequence = btn.get('sequence')
            if sequence and isinstance(sequence, list) and len(sequence) > 0:
                # 序列映射
                sequence_mappings.append({
                    'sequence': sequence,
                    'action': action,
                    'name': btn.get('name', '')
                })
            else:
                # 单键映射（向后兼容）
                key_type = btn.get('keyType')
                if key_type:
                    button_mappings[key_type] = action
        
        # 按序列长度降序排序（长序列优先匹配）
        sequence_mappings.sort(key=lambda x: len(x['sequence']), reverse=True)
        
        app_logger.info(f"加载了 {len(button_mappings)} 个单键映射: {button_mappings}", source="mouse_listener")
        app_logger.info(f"加载了 {len(sequence_mappings)} 个序列映射: {[m['sequence'] for m in sequence_mappings]}", source="mouse_listener")
    except Exception as e:
        app_logger.error(f"加载映射失败: {e}", source="mouse_listener")
        button_mappings = {}
        sequence_mappings = []

# 预解析的快捷键缓存，避免每次都解析
_shortcut_cache = {}

# 修饰键映射（按平台）
_modifier_map = {
    'ctrl': Key.ctrl, 'cmd': Key.cmd, 'alt': Key.alt,
    'shift': Key.shift, 'win': Key.cmd,
}
if is_mac:
    _modifier_map['ctrl'] = Key.cmd  # Mac 上 ctrl 常映射到 cmd

# 特殊键映射（预定义）
_special_keys = {
    'enter': Key.enter, 'tab': Key.tab, 'space': Key.space,
    'backspace': Key.backspace, 'delete': Key.delete,
    'escape': Key.esc, 'esc': Key.esc,
    'up': Key.up, 'down': Key.down, 'left': Key.left, 'right': Key.right,
    'home': Key.home, 'end': Key.end,
    'pageup': Key.page_up, 'pagedown': Key.page_down,
    'f1': Key.f1, 'f2': Key.f2, 'f3': Key.f3, 'f4': Key.f4,
    'f5': Key.f5, 'f6': Key.f6, 'f7': Key.f7, 'f8': Key.f8,
    'f9': Key.f9, 'f10': Key.f10, 'f11': Key.f11, 'f12': Key.f12,
}

# 系统命令映射（按平台）
import subprocess

def _get_system_commands():
    if is_mac:
        return {
            'launchpad': ['open', '-a', 'Launchpad'],
            'mission_control': ['open', '-a', 'Mission Control'],
            'mission': ['open', '-a', 'Mission Control'],
            'screenshot': ['screencapture', '-i', '-c'],
            'screenshot_area': ['screencapture', '-i', '-c'],
            'screenshot_window': ['screencapture', '-i', '-w', '-c'],
            'screenshot_full': ['screencapture', '-c'],
            'finder': ['open', '-a', 'Finder'],
            'desktop': ['open', os.path.expanduser('~/Desktop')],
            'downloads': ['open', os.path.expanduser('~/Downloads')],
            'documents': ['open', os.path.expanduser('~/Documents')],
            'siri': ['open', '-a', 'Siri'],
            'sleep': ['pmset', 'sleepnow'],
        }
    # Windows
    user = os.environ.get('USERPROFILE', '') or os.path.expanduser('~')
    return {
        'screenshot': ['powershell', '-NoProfile', '-Command', 'Start-Process ms-screenclip:'],
        'screenshot_area': ['powershell', '-NoProfile', '-Command', 'Start-Process ms-screenclip:'],
        'screenshot_window': ['powershell', '-NoProfile', '-Command', 'Start-Process ms-screenclip:'],
        'screenshot_full': ['powershell', '-NoProfile', '-Command', 'Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait(\"^{PRTSC}\")'],
        'finder': ['explorer', ''],
        'desktop': ['explorer', os.path.join(user, 'Desktop')],
        'downloads': ['explorer', os.path.join(user, 'Downloads')],
        'documents': ['explorer', os.path.join(user, 'Documents')],
        'sleep': ['powershell', '-NoProfile', '-Command', 'Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Application]::SetSuspendState(3, $true, $false)'],
    }

def _get_shell_commands():
    if is_mac:
        return {
            'spotlight': 'osascript -e \'tell application "System Events" to keystroke space using command down\'',
            'notification_center': 'open -g "x-apple.systempreferences:com.apple.preference.notifications"',
            'notification': 'open -g "x-apple.systempreferences:com.apple.preference.notifications"',
            'dictation': 'osascript -e \'tell application "System Events" to keystroke "d" using {command down, fn down}\'',
            'volume_up': 'osascript -e "set volume output volume (output volume of (get volume settings) + 10)"',
            'volume_down': 'osascript -e "set volume output volume (output volume of (get volume settings) - 10)"',
            'volume_mute': 'osascript -e "set volume output muted not (output muted of (get volume settings))"',
            'play_pause': 'osascript -e \'tell application "System Events" to key code 16 using {command down, option down}\'',
            'next_track': 'osascript -e \'tell application "System Events" to key code 17 using {command down, option down}\'',
            'prev_track': 'osascript -e \'tell application "System Events" to key code 18 using {command down, option down}\'',
            'lock_screen': 'osascript -e \'tell application "System Events" to keystroke "q" using {command down, control down}\'',
            'show_desktop': 'osascript -e \'tell application "System Events" to key code 103\'',
        }
    # Windows: 使用 PowerShell 或 rundll32 / nircmd 等
    return {
        'spotlight': 'powershell -NoProfile -Command "Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.Interaction]::AppActivate(\\\"Search\\\")"',
        'notification_center': 'powershell -NoProfile -Command "Get-Process -Name \"ShellExperienceHost\" -ErrorAction SilentlyContinue | Out-Null; Start-Process ms-actioncenter:"',
        'notification': 'powershell -NoProfile -Command "Start-Process ms-actioncenter:"',
        'dictation': 'powershell -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait(\"%h\")"',
        'volume_up': 'powershell -NoProfile -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]175)"',
        'volume_down': 'powershell -NoProfile -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]174)"',
        'volume_mute': 'powershell -NoProfile -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"',
        'play_pause': 'powershell -NoProfile -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]179)"',
        'next_track': 'powershell -NoProfile -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]176)"',
        'prev_track': 'powershell -NoProfile -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]177)"',
        'lock_screen': None,   # 在 execute_system_command 中用 pynput 发 Win+L
        'show_desktop': None,  # 在 execute_system_command 中用 pynput 发 Win+D
    }

_system_commands = _get_system_commands()
_shell_commands = _get_shell_commands()

def execute_system_command(command_key: str) -> bool:
    """
    执行系统命令（按平台）
    返回: True 表示执行成功，False 表示命令不存在
    """
    command_key = command_key.lower().strip()

    try:
        # Windows 上锁屏/显示桌面用 pynput 发 Win+L / Win+D
        if is_windows and command_key == 'lock_screen':
            keyboard_controller.press(Key.cmd)
            keyboard_controller.press('l')
            keyboard_controller.release('l')
            keyboard_controller.release(Key.cmd)
            return True
        if is_windows and command_key == 'show_desktop':
            keyboard_controller.press(Key.cmd)
            keyboard_controller.press('d')
            keyboard_controller.release('d')
            keyboard_controller.release(Key.cmd)
            return True

        # 优先使用快速命令（列表形式）
        if command_key in _system_commands:
            cmd = _system_commands[command_key]
            if cmd and (isinstance(cmd, list) and len(cmd) > 0):
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=not is_windows,
                    creationflags=(0x0800 if is_windows and hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
                )
            return True

        # 使用 shell 命令
        if command_key in _shell_commands:
            cmd = _shell_commands[command_key]
            if cmd is None:
                return False
            subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=not is_windows,
                creationflags=(0x0800 if is_windows and hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
            )
            return True

        return False
    except Exception:
        return False

def _parse_shortcut(shortcut: str):
    """解析快捷键（带缓存）"""
    if shortcut in _shortcut_cache:
        return _shortcut_cache[shortcut]
    
    keys = shortcut.lower().split('+')
    modifiers = []
    main_key = None
    
    for k in keys:
        if k in _modifier_map:
            modifiers.append(_modifier_map[k])
        elif len(k) == 1:
            main_key = k
        else:
            main_key = _special_keys.get(k, k)
    
    result = (modifiers, main_key)
    _shortcut_cache[shortcut] = result
    return result

def execute_shortcut_fast(shortcut: str):
    """快速执行快捷键或系统命令（无日志，直接执行）"""
    try:
        shortcut = shortcut.strip().lower()
        
        # 先检查是否是系统命令
        if shortcut in _system_commands:
            execute_system_command(shortcut)
            return
        
        modifiers, main_key = _parse_shortcut(shortcut)
        if main_key is None:
            return
        
        # 按下修饰键
        for mod in modifiers:
            keyboard_controller.press(mod)
        
        # 按下并释放主键
        keyboard_controller.press(main_key)
        keyboard_controller.release(main_key)
        
        # 释放修饰键
        for mod in reversed(modifiers):
            keyboard_controller.release(mod)
    except Exception as e:
        app_logger.error(f"execute_shortcut_fast 失败: {shortcut!r} -> {e}", source="mouse_listener")


def dispatch_shortcut_from_hook(shortcut: str):
    """
    在独立线程中执行快捷键。Windows 的 WH_MOUSE_LL 回调内若直接调用 SendInput（pynput 所用），
    易导致按键不生效、被吞或死锁；macOS 事件 tap 回调内同步注入也同样不安全。
    """
    if not shortcut or not str(shortcut).strip():
        return
    s = str(shortcut).strip()

    def _run():
        try:
            execute_shortcut_fast(s)
        except Exception as e:
            app_logger.error(f"异步派发快捷键失败: {s!r} -> {e}", source="mouse_listener")

    threading.Thread(target=_run, daemon=True).start()


def execute_shortcut(shortcut: str):
    """执行快捷键或系统命令（带日志，用于调试）"""
    try:
        shortcut = shortcut.strip().lower()
        
        # 先检查是否是系统命令
        if shortcut in _system_commands:
            execute_system_command(shortcut)
            return
        
        modifiers, main_key = _parse_shortcut(shortcut)
        
        if main_key is None:
            app_logger.error(f"快捷键解析失败: {shortcut}", source="mouse_listener")
            return
        
        app_logger.info(f"执行快捷键: {shortcut}", source="mouse_listener")
        
        for mod in modifiers:
            keyboard_controller.press(mod)
        
        keyboard_controller.press(main_key)
        keyboard_controller.release(main_key)
        
        for mod in reversed(modifiers):
            keyboard_controller.release(mod)
            
        app_logger.info(f"快捷键执行完成: {shortcut}", source="mouse_listener")
        
    except Exception as e:
        app_logger.error(f"执行快捷键失败: {e}", source="mouse_listener")

def check_sequence_match(history: list) -> tuple:
    """
    检查按键历史是否匹配任何序列
    返回: (matched_action, is_prefix)
    - matched_action: 匹配到的动作，None 表示没有完全匹配
    - is_prefix: 当前历史是否是某个序列的前缀
    """
    if not history:
        return None, False
    
    history_keys = [h[0] for h in history]
    matched_action = None
    is_prefix = False
    
    for mapping in sequence_mappings:
        seq = mapping['sequence']
        action = mapping['action']
        
        # 完全匹配
        if history_keys == seq:
            matched_action = action
            break
        
        # 检查是否是前缀
        if len(history_keys) < len(seq) and seq[:len(history_keys)] == history_keys:
            is_prefix = True
    
    return matched_action, is_prefix


def _button_has_mouse_shortcut_config(button_type: str) -> bool:
    """该侧键是否出现在用户已保存的单键映射或任意序列中（未配置的键不拦截、不记历史）。"""
    if button_type in button_mappings:
        return True
    for m in sequence_mappings:
        seq = m.get("sequence") or []
        if button_type in seq:
            return True
    return False


def execute_pending_single_key():
    """执行待处理的单键操作（与序列竞态时：若历史已推进为完整序列或不再是「仅首键」，则放弃单键）"""
    global pending_single_key, pending_timer

    pending_timer = None
    if not pending_single_key:
        return
    key_type, action, _ = pending_single_key
    hist = [h[0] for h in key_history]
    if hist != [key_type]:
        app_logger.debug(
            f"取消延迟单键：按键历史已变为 {hist}，不再执行单键 {key_type}",
            source="mouse_listener",
        )
        pending_single_key = None
        return
    app_logger.info(f"执行单键操作: {key_type} -> {action}", source="mouse_listener")
    dispatch_shortcut_from_hook(action)
    pending_single_key = None

def cancel_pending_single_key():
    """取消待处理的单键操作"""
    global pending_single_key, pending_timer
    
    if pending_timer:
        pending_timer.cancel()
        pending_timer = None
    pending_single_key = None

def handle_mouse_button(button_number: int) -> bool:
    """
    处理鼠标按键事件。
    返回 True：该键已在软件中配置（单键或序列），应吞掉系统默认并执行映射逻辑。
    返回 False：未配置该键，放行系统默认（钩子层不拦截）。
    """
    global key_history, pending_single_key, pending_timer
    # 按键编号映射
    # macOS: 0=左键, 1=右键, 2=中键, 3=侧键1(后退), 4=侧键2(前进)
    button_map = {
        0: 'left',
        1: 'right', 
        2: 'middle',
        3: 'side1',
        4: 'side2',
    }
    
    button_type = button_map.get(button_number)
    if not button_type:
        return False

    # 未出现在任何单键/序列配置中的侧键：不记历史、不拦截（用户仍可使用系统默认）
    if not _button_has_mouse_shortcut_config(button_type):
        return False
    
    current_time = time.time()
    
    # 清理过期的按键历史
    key_history = [(k, t) for k, t in key_history if current_time - t < SEQUENCE_TIMEOUT]
    
    # 添加当前按键到历史
    key_history.append((button_type, current_time))
    
    # 如果有序列映射，先检查序列匹配
    if sequence_mappings:
        matched_action, is_prefix = check_sequence_match(key_history)
        
        if matched_action:
            # 完全匹配序列，取消待处理的单键，执行序列动作
            cancel_pending_single_key()
            app_logger.info(f"序列匹配: {[h[0] for h in key_history]} -> {matched_action}", source="mouse_listener")
            dispatch_shortcut_from_hook(matched_action)
            key_history = []  # 清空历史
            return True
        
        if is_prefix:
            # 当前是某个序列的前缀，取消之前的单键延迟，等待后续按键
            cancel_pending_single_key()
            
            # 如果当前按键有单键映射，设置延迟执行
            if button_type in button_mappings:
                action = button_mappings[button_type]
                pending_single_key = (button_type, action, current_time)
                pending_timer = threading.Timer(SINGLE_KEY_DELAY, execute_pending_single_key)
                pending_timer.start()
                app_logger.info(f"按键 {button_type} 可能是序列前缀，延迟 {SINGLE_KEY_DELAY}s 执行单键操作", source="mouse_listener")
            
            return True  # 阻止默认行为，等待序列完成
    
    # 没有匹配的序列，检查单键映射
    if button_type in button_mappings:
        # 取消之前的待处理单键
        cancel_pending_single_key()
        
        shortcut = button_mappings[button_type]
        dispatch_shortcut_from_hook(shortcut)
        key_history = []  # 执行后清空历史
        return True
    
    # 已 append 但本拍既不是完整序列、也不是可执行单键：撤销本次历史，避免误伤后续判定
    if key_history and key_history[-1][0] == button_type:
        key_history.pop()
    return False

# ---------- macOS 监听器（Quartz）----------
_run_loop = None
_tap = None

if is_mac:
    import Quartz
    from Quartz import (
        CGEventTapCreate, CGEventTapEnable, CGEventTapIsEnabled,
        kCGSessionEventTap, kCGHeadInsertEventTap, kCGEventTapOptionDefault,
        CGEventMaskBit,
        kCGEventLeftMouseDown,
        kCGEventRightMouseDown,
        kCGEventOtherMouseDown,
        kCGEventLeftMouseUp,
        kCGEventRightMouseUp,
        kCGEventOtherMouseUp,
        CGEventGetIntegerValueField, kCGMouseEventButtonNumber,
        CFMachPortCreateRunLoopSource, CFRunLoopGetCurrent, CFRunLoopAddSource,
        kCFRunLoopCommonModes, CFRunLoopRun, CFRunLoopStop
    )

    def _mac_mouse_event_mask():
        """左/右键在 macOS 上走 Left/RightMouseDown，不是 OtherMouseDown；须一并订阅才能拦截映射。"""
        return (
            CGEventMaskBit(kCGEventLeftMouseDown)
            | CGEventMaskBit(kCGEventRightMouseDown)
            | CGEventMaskBit(kCGEventOtherMouseDown)
            | CGEventMaskBit(kCGEventLeftMouseUp)
            | CGEventMaskBit(kCGEventRightMouseUp)
            | CGEventMaskBit(kCGEventOtherMouseUp)
        )

    # 已拦截的 MouseDown 对应的 MouseUp 需一并丢弃，避免目标应用收到不成对按钮事件
    _mac_pending_mouseup = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}

    def _mac_try_consume_mouseup(btn: int) -> bool:
        c = _mac_pending_mouseup.get(btn, 0)
        if c > 0:
            _mac_pending_mouseup[btn] = c - 1
            return True
        return False

    def _mac_note_intercepted_down(btn: int) -> None:
        if btn in _mac_pending_mouseup:
            _mac_pending_mouseup[btn] += 1

def _open_macos_accessibility_settings():
    """打开 macOS 辅助功能权限设置页。"""
    if not is_mac:
        return
    try:
        subprocess.Popen(
            ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        app_logger.warning(f"打开辅助功能设置页失败: {e}", source="mouse_listener")

    # 同时在 Finder 中定位实际需要授权的可执行文件，减少“授权了 App 但监听进程无权限”的误操作。
    target = _mac_accessibility_target_path()
    if target and os.path.exists(target):
        try:
            subprocess.Popen(
                ["open", "-R", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            app_logger.warning(f"在 Finder 中定位授权目标失败: {e}", source="mouse_listener")


def check_accessibility_permission(prompt: bool = False) -> bool:
    """检测 macOS 辅助功能权限（仅 Mac）"""
    global has_permission, permission_message
    if not is_mac:
        has_permission = True
        permission_message = "当前平台无需辅助功能权限"
        return True
    try:
        # prompt=True 时会触发系统授权提示；False 时仅静默检测。
        trusted = False
        if hasattr(Quartz, "AXIsProcessTrustedWithOptions") and hasattr(Quartz, "kAXTrustedCheckOptionPrompt"):
            trusted = bool(
                Quartz.AXIsProcessTrustedWithOptions(
                    {Quartz.kAXTrustedCheckOptionPrompt: bool(prompt)}
                )
            )
        elif hasattr(Quartz, "AXIsProcessTrusted"):
            trusted = bool(Quartz.AXIsProcessTrusted())

        if trusted:
            has_permission = True
            permission_message = "已获得辅助功能权限，鼠标侧键功能可用"
            app_logger.info(permission_message, source="mouse_listener")
            return True
        else:
            has_permission = False
            target = _mac_accessibility_target_path()
            if target:
                permission_message = (
                    "未获得辅助功能权限，鼠标侧键功能不可用。"
                    "请在 系统设置 > 隐私与安全性 > 辅助功能 中授权该可执行文件："
                    f"{target}"
                )
            else:
                permission_message = "未获得辅助功能权限，鼠标侧键功能不可用。请在 系统设置 > 隐私与安全性 > 辅助功能 中授权本程序"
            app_logger.warning(permission_message, source="mouse_listener")
            return False
    except Exception as e:
        has_permission = False
        permission_message = f"权限检测失败: {e}"
        app_logger.error(permission_message, source="mouse_listener")
        return False


def ensure_accessibility_permission_on_startup() -> bool:
    """
    启动阶段确保辅助功能权限：
    1) 先静默检测；
    2) 若未授权，本次进程仅触发一次系统授权提示；
    3) 若仍未授权，打开系统设置页，便于用户手动勾选。
    """
    global _mac_permission_prompted_once
    if not is_mac:
        return True

    if check_accessibility_permission(prompt=False):
        return True

    if not _mac_permission_prompted_once:
        _mac_permission_prompted_once = True
        app_logger.info("首次启动触发辅助功能权限请求", source="mouse_listener")
        check_accessibility_permission(prompt=True)

    if check_accessibility_permission(prompt=False):
        return True

    _open_macos_accessibility_settings()
    return False

def _mouse_callback(proxy, event_type, event, refcon):
    """macOS 鼠标事件回调"""
    global _tap
    if _tap and not CGEventTapIsEnabled(_tap):
        CGEventTapEnable(_tap, True)
    try:
        button_number = CGEventGetIntegerValueField(event, kCGMouseEventButtonNumber)
        if event_type == kCGEventLeftMouseUp:
            up_btn = 0
        elif event_type == kCGEventRightMouseUp:
            up_btn = 1
        elif event_type == kCGEventOtherMouseUp:
            up_btn = int(button_number)
        else:
            up_btn = None

        if up_btn is not None and _mac_try_consume_mouseup(up_btn):
            return None

        if event_type not in (
            kCGEventLeftMouseDown,
            kCGEventRightMouseDown,
            kCGEventOtherMouseDown,
        ):
            return event

        handled = handle_mouse_button(int(button_number))
        if handled:
            _mac_note_intercepted_down(int(button_number))
            return None
    except Exception:
        pass
    return event

def _run_macos_listener():
    """运行 macOS 监听器"""
    global _run_loop, _tap, is_listening, has_permission, permission_message, _mac_start_ok
    try:
        _tap = CGEventTapCreate(
            kCGSessionEventTap, kCGHeadInsertEventTap, kCGEventTapOptionDefault,
            _mac_mouse_event_mask(), _mouse_callback, None
        )
        if _tap is None:
            app_logger.error("创建事件 tap 失败，请检查辅助功能权限", source="mouse_listener")
            has_permission = False
            target = _mac_accessibility_target_path()
            if target:
                permission_message = f"辅助功能权限未生效，请在系统设置中重新勾选该可执行文件后重试：{target}"
            else:
                permission_message = "辅助功能权限未生效，请在系统设置中重新勾选后重试"
            _mac_start_ok = False
            if _mac_start_ready_event:
                _mac_start_ready_event.set()
            _open_macos_accessibility_settings()
            is_listening = False
            return
        CGEventTapEnable(_tap, True)
        source = CFMachPortCreateRunLoopSource(None, _tap, 0)
        _run_loop = CFRunLoopGetCurrent()
        CFRunLoopAddSource(_run_loop, source, kCFRunLoopCommonModes)
        _mac_start_ok = True
        is_listening = True
        if _mac_start_ready_event:
            _mac_start_ready_event.set()
        app_logger.info("macOS 监听器已启动", source="mouse_listener")
        CFRunLoopRun()
    except Exception as e:
        app_logger.error(f"macOS 监听器异常: {e}", source="mouse_listener")
        _mac_start_ok = False
        if _mac_start_ready_event:
            _mac_start_ready_event.set()
        is_listening = False

# ---------- Windows 监听器（Win32 低级钩子）----------
_win_hook_handle = None
_win_listener_thread_id = None
_win_callback_ref = None  # 保持回调引用防止被垃圾回收

# Windows 钩子常量（模块级定义）
_WH_MOUSE_LL = 14
_WM_QUIT = 0x0012
_WM_LBUTTONDOWN, _WM_LBUTTONUP = 0x0201, 0x0202
_WM_RBUTTONDOWN, _WM_RBUTTONUP = 0x0204, 0x0205
_WM_MBUTTONDOWN, _WM_MBUTTONUP = 0x0207, 0x0208
_WM_XBUTTONDOWN = 0x020B
_WM_XBUTTONUP = 0x020C
_XBUTTON1, _XBUTTON2 = 1, 2
# 已拦截的 XBUTTONDOWN 与后续 XBUTTONUP 配对计数（高字：XBUTTON1=1, XBUTTON2=2），避免只吞 DOWN、UP 仍进入 Chromium 等
_win_pending_xbutton_up = {1: 0, 2: 0}
# 左/右/中键（0/1/2）同样需 DOWN/UP 成对吞掉
_win_pending_primary_up = {0: 0, 1: 0, 2: 0}


def _win_consume_matched_xbutton(hi: int) -> int:
    """记录一次已吞掉的侧键 DOWN，对应 UP 也需吞掉以保持成对。"""
    if hi in _win_pending_xbutton_up:
        _win_pending_xbutton_up[hi] += 1
    return 1


def _win_try_consume_xbutton_up(hi: int) -> bool:
    c = _win_pending_xbutton_up.get(hi, 0)
    if c > 0:
        _win_pending_xbutton_up[hi] = c - 1
        return True
    return False


def _win_consume_matched_primary(btn: int) -> int:
    if btn in _win_pending_primary_up:
        _win_pending_primary_up[btn] += 1
    return 1


def _win_try_consume_primary_up(btn: int) -> bool:
    c = _win_pending_primary_up.get(btn, 0)
    if c > 0:
        _win_pending_primary_up[btn] = c - 1
        return True
    return False


if is_windows:
    class _MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("pt", ctypes.wintypes.POINT),
            ("mouseData", ctypes.wintypes.DWORD),
            ("flags", ctypes.wintypes.DWORD),
            ("time", ctypes.wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    # Windows 钩子回调类型（模块级定义，stdcall 调用约定）
    # 签名: LRESULT CALLBACK LowLevelMouseProc(int nCode, WPARAM wParam, LPARAM lParam)
    # LRESULT 在 64 位 Windows 上是 ctypes.c_longlong
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        _LRESULT = ctypes.c_longlong
    else:
        _LRESULT = ctypes.c_long

    _HOOKPROC_TYPE = ctypes.WINFUNCTYPE(
        _LRESULT, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM
    )

    @_HOOKPROC_TYPE
    def _win_low_level_handler(nCode, wParam, lParam):
        """Windows 低级鼠标钩子回调函数"""
        if nCode == 0 and lParam:  # HC_ACTION
            try:
                s = _MSLLHOOKSTRUCT.from_address(lParam)
                # 与已拦截的侧键 DOWN 成对吞掉 UP（否则部分应用/Chromium 会收到不对称按钮事件）
                if wParam == _WM_XBUTTONUP:
                    hi_up = (s.mouseData >> 16) & 0xFFFF
                    if hi_up in (_XBUTTON1, _XBUTTON2) and _win_try_consume_xbutton_up(hi_up):
                        app_logger.debug(
                            "Windows钩子: 吞掉 XBUTTONUP（与已拦截的侧键 DOWN 配对）",
                            source="mouse_listener",
                        )
                        return 1

                if wParam == _WM_LBUTTONUP and _win_try_consume_primary_up(0):
                    app_logger.debug(
                        "Windows钩子: 吞掉 LBUTTONUP（与已拦截的左键 DOWN 配对）",
                        source="mouse_listener",
                    )
                    return 1
                if wParam == _WM_RBUTTONUP and _win_try_consume_primary_up(1):
                    app_logger.debug(
                        "Windows钩子: 吞掉 RBUTTONUP（与已拦截的右键 DOWN 配对）",
                        source="mouse_listener",
                    )
                    return 1
                if wParam == _WM_MBUTTONUP and _win_try_consume_primary_up(2):
                    app_logger.debug(
                        "Windows钩子: 吞掉 MBUTTONUP（与已拦截的中键 DOWN 配对）",
                        source="mouse_listener",
                    )
                    return 1

                btn = -1
                btn_name = "unknown"
                hi = None  # WM_XBUTTONDOWN 时 mouseData 高字（XBUTTON1=1, XBUTTON2=2）

                if wParam == _WM_LBUTTONDOWN:
                    btn = 0
                    btn_name = "left"
                elif wParam == _WM_RBUTTONDOWN:
                    btn = 1
                    btn_name = "right"
                elif wParam == _WM_MBUTTONDOWN:
                    btn = 2
                    btn_name = "middle"
                elif wParam == _WM_XBUTTONDOWN:
                    hi = (s.mouseData >> 16) & 0xFFFF
                    if hi == _XBUTTON1:
                        btn = 3
                        btn_name = "side1(X1)"
                    elif hi == _XBUTTON2:
                        btn = 4
                        btn_name = "side2(X2)"

                if btn >= 0:
                    handled = handle_mouse_button(btn)
                    if handled:
                        app_logger.info(f"Windows钩子拦截: {btn_name} -> 已处理并阻止", source="mouse_listener")
                        if btn >= 3:
                            hx = hi if hi is not None else ((s.mouseData >> 16) & 0xFFFF)
                            return _win_consume_matched_xbutton(hx)
                        return _win_consume_matched_primary(btn)
                    app_logger.debug(f"Windows钩子: {btn_name} -> 无映射，放行", source="mouse_listener")

            except Exception as e:
                app_logger.error(f"Windows钩子异常: {e}", source="mouse_listener")

        # 调用下一个钩子或让事件继续传递
        return ctypes.windll.user32.CallNextHookEx(None, nCode, wParam, lParam)

    def _run_windows_listener():
        """运行 Windows 鼠标监听器（WH_MOUSE_LL）"""
        global _win_hook_handle, _win_listener_thread_id, _win_callback_ref, is_listening
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            _win_listener_thread_id = threading.get_ident()

            # WH_MOUSE_LL 是全局钩子，hMod 参数必须为 NULL (0)
            # 直接使用装饰器创建的回调函数
            _win_callback_ref = _win_low_level_handler
            _win_hook_handle = user32.SetWindowsHookExW(
                _WH_MOUSE_LL, _win_callback_ref, None, 0
            )
            if not _win_hook_handle:
                err = kernel32.GetLastError()
                app_logger.error(f"Windows 安装鼠标钩子失败，错误码: {err}", source="mouse_listener")
                _win_callback_ref = None
                is_listening = False
                return
            app_logger.info("Windows 监听器已启动", source="mouse_listener")
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0):
                if msg.message == _WM_QUIT:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            user32.UnhookWindowsHookEx(_win_hook_handle)
            _win_hook_handle = None
            _win_callback_ref = None
        except Exception as e:
            app_logger.error(f"Windows 监听器异常: {e}", source="mouse_listener")
            is_listening = False
            if _win_hook_handle:
                try:
                    ctypes.windll.user32.UnhookWindowsHookEx(_win_hook_handle)
                except Exception:
                    pass
                _win_hook_handle = None
            _win_callback_ref = None
        finally:
            _win_listener_thread_id = None


def start_listener():
    """启动鼠标监听（按平台）"""
    global listener_thread, is_listening, has_permission, _mac_start_ready_event, _mac_start_ok
    with _listener_state_lock:
        if is_listening:
            load_mappings()
            return {
                'success': True,
                'message': '监听器已在运行，已重新加载配置',
                'permission': has_permission,
                'permission_message': permission_message
            }

        if is_mac and not ensure_accessibility_permission_on_startup():
            return {
                'success': False,
                'message': '未获得辅助功能权限，已打开系统设置页，请授权后重试',
                'permission': has_permission,
                'permission_message': permission_message
            }

        load_mappings()

        if is_windows:
            # 注意：不要在函数内再 import threading，否则 Python 会把 threading 视为整函内容的局部变量，
            # macOS 分支执行 listener_thread = threading.Thread(...) 时会报「引用前尚未赋值」。
            # 使用文件顶部已导入的 threading 模块即可。
            # 使用事件来等待钩子安装完成
            _hook_ready_event = threading.Event()
            _hook_success = [False]  # 使用列表来存储结果
            
            def _windows_listener_wrapper():
                """包装器，用于通知钩子安装状态"""
                global _win_hook_handle, _win_listener_thread_id, _win_callback_ref, is_listening
                try:
                    import ctypes
                    from ctypes import wintypes
                    user32 = ctypes.windll.user32
                    kernel32 = ctypes.windll.kernel32
                    _win_listener_thread_id = threading.get_ident()

                    # WH_MOUSE_LL 是全局钩子，hMod 参数必须为 NULL (0)
                    _win_callback_ref = _win_low_level_handler
                    _win_hook_handle = user32.SetWindowsHookExW(
                        _WH_MOUSE_LL, _win_callback_ref, None, 0
                    )
                    if not _win_hook_handle:
                        err = kernel32.GetLastError()
                        app_logger.error(f"Windows 安装鼠标钩子失败，错误码: {err}", source="mouse_listener")
                        _win_callback_ref = None
                        is_listening = False
                        _hook_success[0] = False
                        _hook_ready_event.set()
                        return
                    
                    # 钩子安装成功
                    app_logger.info("Windows 监听器已启动", source="mouse_listener")
                    _hook_success[0] = True
                    _hook_ready_event.set()
                    
                    # 进入消息循环
                    msg = wintypes.MSG()
                    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0):
                        if msg.message == _WM_QUIT:
                            break
                        user32.TranslateMessage(ctypes.byref(msg))
                        user32.DispatchMessageW(ctypes.byref(msg))
                    user32.UnhookWindowsHookEx(_win_hook_handle)
                    _win_hook_handle = None
                    _win_callback_ref = None
                except Exception as e:
                    app_logger.error(f"Windows 监听器异常: {e}", source="mouse_listener")
                    is_listening = False
                    _hook_success[0] = False
                    if not _hook_ready_event.is_set():
                        _hook_ready_event.set()
                    if _win_hook_handle:
                        try:
                            ctypes.windll.user32.UnhookWindowsHookEx(_win_hook_handle)
                        except Exception:
                            pass
                        _win_hook_handle = None
                    _win_callback_ref = None
                finally:
                    _win_listener_thread_id = None
            
            listener_thread = threading.Thread(target=_windows_listener_wrapper, daemon=True)
            listener_thread.start()
            
            # 等待钩子安装完成（最多等待3秒）
            _hook_ready_event.wait(timeout=3.0)
            
            if _hook_success[0]:
                is_listening = True
                return {
                    'success': True,
                    'message': 'Windows 鼠标监听器启动成功',
                    'permission': True,
                    'permission_message': '鼠标侧键功能可用（若无效请以管理员身份运行）'
                }
            else:
                return {
                    'success': False,
                    'message': 'Windows 鼠标钩子安装失败，请检查权限或以管理员身份运行',
                    'permission': False,
                    'permission_message': '鼠标钩子安装失败'
                }

        _mac_start_ready_event = threading.Event()
        _mac_start_ok = False
        listener_thread = threading.Thread(target=_run_macos_listener, daemon=True)
        listener_thread.start()
        _mac_start_ready_event.wait(timeout=2.5)
        if _mac_start_ok:
            return {
                'success': True,
                'message': '鼠标监听器启动成功',
                'permission': has_permission,
                'permission_message': permission_message
            }
        return {
            'success': False,
            'message': '鼠标监听器启动失败，请确认辅助功能权限已对当前应用生效',
            'permission': has_permission,
            'permission_message': permission_message
        }

def stop_listener():
    """停止鼠标监听（按平台）"""
    global listener_thread, is_listening, _run_loop, _tap, _win_listener_thread_id

    with _listener_state_lock:
        if not is_listening:
            return {'success': True, 'message': '监听器未运行'}

        try:
            if is_windows and _win_listener_thread_id is not None:
                import ctypes
                WM_QUIT = 0x0012
                ctypes.windll.user32.PostThreadMessageW(_win_listener_thread_id, WM_QUIT, 0, 0)
                if listener_thread and listener_thread.is_alive():
                    listener_thread.join(timeout=2.0)
                is_listening = False
                return {'success': True, 'message': '鼠标监听器已停止'}
            if is_mac:
                if _run_loop:
                    CFRunLoopStop(_run_loop)
                    _run_loop = None
                if _tap:
                    CGEventTapEnable(_tap, False)
                    _tap = None
            is_listening = False
            return {'success': True, 'message': '鼠标监听器已停止'}
        except Exception as e:
            app_logger.error(f"停止监听器失败: {e}", source="mouse_listener")
            is_listening = False
            return {'success': False, 'message': f'停止监听器失败: {e}'}

def is_listener_running():
    """检查监听器是否正在运行"""
    global is_listening
    
    # Windows 平台：检查钩子句柄和线程状态
    if is_windows:
        hook_handle = globals().get('_win_hook_handle')
        thread_id = globals().get('_win_listener_thread_id')
        
        app_logger.debug(f"is_listener_running check: hook_handle={hook_handle}, thread_id={thread_id}, is_listening={is_listening}", source="mouse_listener")
        
        # 检查钩子句柄是否有效
        if hook_handle is not None:
            # 钩子已安装
            return True
        # 钩子句柄为 None，但线程可能还在运行（正在安装中或已失败）
        if thread_id is not None:
            # 线程还在运行，可能是正在安装中
            return is_listening
        # 线程和钩子都不存在
        return False
    
    # Mac 平台：使用原来的逻辑
    return is_listening

def reload_mappings():
    """重新加载按键映射"""
    load_mappings()
    return {
        'success': True,
        'message': '按键映射已重新加载',
        'button_mappings': button_mappings,
        'sequence_mappings': sequence_mappings
    }


def reload_and_restart_listener():
    """
    兼容 mouse_config 路由调用：在不破坏当前运行状态的前提下应用最新映射。
    - 监听器运行中：仅热重载映射，不中断监听；
    - 监听器未运行：尝试按当前平台启动（会做权限检查）。
    """
    if is_listener_running():
        return reload_mappings()
    return start_listener()

# API 端点
@router.post("/start")
async def api_start_listener():
    """启动鼠标监听器"""
    return start_listener()

@router.post("/stop")
async def api_stop_listener():
    """停止鼠标监听器"""
    return stop_listener()

@router.get("/status")
async def api_get_status():
    """获取监听器状态"""
    return {
        'is_listening': is_listening,
        'permission': has_permission,
        'permission_message': permission_message,
        'button_mappings_count': len(button_mappings),
        'sequence_mappings_count': len(sequence_mappings)
    }

@router.post("/reload")
async def api_reload_mappings():
    """重新加载按键映射"""
    return reload_and_restart_listener()

@router.get("/mappings")
async def api_get_mappings():
    """获取当前按键映射"""
    return {
        'button_mappings': button_mappings,
        'sequence_mappings': sequence_mappings
    }

@router.get("/permission")
async def api_check_permission():
    """检查辅助功能权限"""
    check_accessibility_permission(prompt=False)
    return {
        'has_permission': has_permission,
        'message': permission_message
    }


@router.post("/permission/request")
async def api_request_permission():
    """主动请求辅助功能权限并尝试启动监听器（macOS）。"""
    if not is_mac:
        return {'success': True, 'permission': True, 'message': '当前平台无需辅助功能权限'}

    check_accessibility_permission(prompt=True)
    if check_accessibility_permission(prompt=False):
        if not is_listener_running():
            return start_listener()
        return {
            'success': True,
            'permission': True,
            'message': '已获得辅助功能权限，监听器已就绪',
            'permission_message': permission_message,
        }

    _open_macos_accessibility_settings()
    return {
        'success': False,
        'permission': False,
        'message': '尚未获得辅助功能权限，已打开系统设置页',
        'permission_message': permission_message,
    }

@router.get("/platform")
async def api_get_platform():
    """获取平台信息（与前端 macos/windows 一致小写）"""
    plat = get_platform()
    if plat == 'macos':
        version = platform.mac_ver()[0] or "N/A"
    elif plat == 'windows':
        version = platform.win32_ver()[1] or platform.win32_ver()[2] or "N/A"
    else:
        version = platform.release() or "N/A"
    return {
        "platform": plat,
        "system": platform.system(),
        "version": version
    }


"""
# Windows API 实现（用于后续Windows平台支持）
# 以下代码用于屏蔽已设置鼠标按键的系统默认功能

# Windows 鼠标按键拦截实现
"""

'''
# Windows 专用代码 - 用于屏蔽鼠标按键的系统默认功能
# 注：此代码已注释，不会执行，仅作为后续Windows化的参考

if platform.system() == 'Windows':
    import win32api
    import win32con
    import win32gui
    import pythoncom
    import pyHook
    
    def OnMouseEvent(event):
        """Windows 鼠标事件处理函数"""
        # 鼠标按键映射
        button_map = {
            0: 'left',    # 左键
            1: 'right',   # 右键
            2: 'middle',  # 中键
            3: 'side1',   # 侧键1（后退）
            4: 'side2',   # 侧键2（前进）
        }
        
        # 获取按键类型
        button_number = event.Button
        button_type = button_map.get(button_number)
        
        # 检查是否有映射
        if button_type and button_type in button_mappings:
            # 执行映射的动作
            action = button_mappings[button_type]
            execute_shortcut_fast(action)
            # 返回 False 阻止系统默认行为
            return False
        
        # 检查序列映射
        current_time = time.time()
        key_history = [(k, t) for k, t in key_history if current_time - t < SEQUENCE_TIMEOUT]
        key_history.append((button_type, current_time))
        
        matched_action, is_prefix = check_sequence_match(key_history)
        if matched_action:
            execute_shortcut_fast(matched_action)
            key_history = []
            return False
        
        # 允许系统默认处理
        return True
    
    def _run_windows_listener():
        """运行 Windows 监听器"""
        global is_listening
        
        try:
            # 创建钩子管理器
            hm = pyHook.HookManager()
            # 监听所有鼠标事件
            hm.MouseAll = OnMouseEvent
            # 安装钩子
            hm.HookMouse()
            # 进入消息循环
            pythoncom.PumpMessages()
        except Exception as e:
            app_logger.error(f"Windows 监听器异常: {e}", source="mouse_listener")
            is_listening = False
    
    def start_windows_listener():
        """启动 Windows 鼠标监听"""
        global listener_thread, is_listening
        
        if is_listening:
            load_mappings()
            return {
                'success': True,
                'message': '监听器已在运行，已重新加载配置'
            }
        
        # 加载映射
        load_mappings()
        
        # 启动监听线程
        listener_thread = threading.Thread(target=_run_windows_listener, daemon=True)
        listener_thread.start()
        is_listening = True
        
        return {
            'success': True,
            'message': 'Windows 鼠标监听器启动成功'
        }
    
    def stop_windows_listener():
        """停止 Windows 鼠标监听"""
        global is_listening
        
        if not is_listening:
            return {
                'success': True,
                'message': '监听器未运行'
            }
        
        try:
            # 停止消息循环
            # 注意：在 pyHook 中，需要通过其他方式停止，这里仅作为示例
            is_listening = False
            
            return {
                'success': True,
                'message': 'Windows 鼠标监听器已停止'
            }
        except Exception as e:
            app_logger.error(f"停止 Windows 监听器失败: {e}", source="mouse_listener")
            return {
                'success': False,
                'message': f'停止监听器失败: {e}'
            }
'''
