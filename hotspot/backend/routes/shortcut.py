#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快捷键执行路由
提供键盘快捷键执行功能
支持 Windows / macOS / Linux
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pynput.keyboard import Key, Controller
import re
import sys
import os

# 添加utils目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.logger import info, error
from utils.platform_utils import get_platform, CURRENT_PLATFORM, MODIFIER_KEY_MAP, IS_WINDOWS

# 创建路由器实例
router = APIRouter()

# 初始化键盘控制器
keyboard = Controller()


def _merge_optional_keys(mapping, entries):
    """仅在当前平台 pynput 提供对应 Key 时才加入映射（Darwin 常缺少 insert、print_screen 等）。"""
    for alias, attr in entries:
        key_obj = getattr(Key, attr, None)
        if key_obj is not None:
            mapping[alias] = key_obj


# ============================================
# 完整按键映射表（Windows 全功能 + macOS/Linux 兼容）
# ============================================

# 基础按键映射表
BASE_KEY_MAP = {
    # ===== 修饰键 =====
    'alt': Key.alt,
    'shift': Key.shift,
    'ctrl': Key.ctrl,
    'control': Key.ctrl,
    'alt_l': Key.alt_l,
    'alt_r': Key.alt_r,
    'shift_l': Key.shift_l,
    'shift_r': Key.shift_r,
    'ctrl_l': Key.ctrl_l,
    'ctrl_r': Key.ctrl_r,
    
    # ===== 方向键 =====
    'up': Key.up,
    'down': Key.down,
    'left': Key.left,
    'right': Key.right,
    
    # ===== 编辑键 =====
    'backspace': Key.backspace,
    'delete': Key.delete,
    'del': Key.delete,

    # ===== 导航键 =====
    'home': Key.home,
    'end': Key.end,
    'pageup': Key.page_up,
    'pagedown': Key.page_down,
    'pgup': Key.page_up,
    'pgdn': Key.page_down,
    
    # ===== 特殊键 =====
    'esc': Key.esc,
    'escape': Key.esc,
    'enter': Key.enter,
    'return': Key.enter,
    'tab': Key.tab,
    'space': Key.space,

    # ===== 锁定键 =====
    'caps_lock': Key.caps_lock,
    'caps': Key.caps_lock,

    # ===== 媒体键 =====
    'volume_up': Key.media_volume_up,
    'volume_down': Key.media_volume_down,
    'volume_mute': Key.media_volume_mute,
    'play_pause': Key.media_play_pause,
    'play': Key.media_play_pause,
    'next': Key.media_next,
    'next_track': Key.media_next,
    'previous': Key.media_previous,
    'prev': Key.media_previous,
    'prev_track': Key.media_previous,

}

_merge_optional_keys(
    BASE_KEY_MAP,
    [
        ('insert', 'insert'),
        ('ins', 'insert'),
        ('prtsc', 'print_screen'),
        ('printscreen', 'print_screen'),
        ('print_scr', 'print_screen'),
        ('print', 'print_screen'),
        ('ps', 'print_screen'),
        ('scroll_lock', 'scroll_lock'),
        ('scroll', 'scroll_lock'),
        ('pause', 'pause'),
        ('break', 'pause'),
        ('menu', 'menu'),
        ('apps', 'menu'),
        ('num_lock', 'num_lock'),
        ('num', 'num_lock'),
        ('stop', 'media_stop'),
    ],
)

# 数字小键盘按键映射
NUM_PAD_KEY_MAP = {
    'num_0': '0',
    'num_1': '1',
    'num_2': '2',
    'num_3': '3',
    'num_4': '4',
    'num_5': '5',
    'num_6': '6',
    'num_7': '7',
    'num_8': '8',
    'num_9': '9',
    'num_decimal': '.',
    'num_dot': '.',
    'num_add': '+',
    'num_subtract': '-',
    'num_minus': '-',
    'num_multiply': '*',
    'num_star': '*',
    'num_divide': '/',
    'num_slash': '/',
    'num_enter': Key.enter,
    'num_return': Key.enter,
}

# 合并所有映射表
BASE_KEY_MAP.update(NUM_PAD_KEY_MAP)
KEY_MAP = {**BASE_KEY_MAP, **MODIFIER_KEY_MAP}

# ============================================
# 请求/响应模型
# ============================================

class ShortcutRequest(BaseModel):
    shortcut: str
    action_type: str = "single"  # "single" | "multi" | "toggle"

class ShortcutResponse(BaseModel):
    status: str
    message: str

# ============================================
# 快捷键解析和执行
# ============================================

def parse_shortcut(shortcut_str):
    """
    解析快捷键字符串，返回 pynput 键对象列表
    支持格式: "ctrl+v", "alt+f4", "win+l", "ctrl+shift+t" 等
    """
    shortcut_str = shortcut_str.strip().lower()
    
    # 验证格式
    pattern = r'^[a-z0-9_]+(\+[a-z0-9_]+)*$'
    if not re.match(pattern, shortcut_str):
        raise ValueError(f"快捷键格式不正确，必须使用小写字母、数字和下划线，用+分隔，例如：ctrl+v，当前输入：{shortcut_str}")
    
    parts = shortcut_str.split('+')
    keys = []
    
    for part in parts:
        part = part.strip()
        
        # 1. 查映射表
        if part in KEY_MAP:
            key = KEY_MAP[part]
            # 如果是字符串（如数字小键盘），直接使用
            keys.append(key)
        # 2. 功能键（f1-f20）
        elif part.startswith('f') and len(part) > 1 and part[1:].isdigit():
            f_num = part[1:]
            f_key = getattr(Key, f'f{f_num}', None)
            if f_key:
                keys.append(f_key)
            else:
                raise ValueError(f"无效的功能键: {part}，支持 f1-f20")
        # 3. 字母和数字（单个字符）
        elif len(part) == 1 and part.isalnum():
            keys.append(part)
        else:
            raise ValueError(f"无效的按键: {part}")
    
    return keys

def execute_shortcut(shortcut_str):
    """执行指定的快捷键"""
    try:
        shortcut_str = shortcut_str.strip().lower()
        keys = parse_shortcut(shortcut_str)
        
        if not keys:
            raise ValueError("快捷键解析结果为空")
        
        info(f"执行快捷键: {shortcut_str} -> {keys}", "shortcut")
        
        if len(keys) == 1:
            # 单个键
            keyboard.press(keys[0])
            keyboard.release(keys[0])
        else:
            # 组合键
            modifiers = keys[:-1]
            main_key = keys[-1]
            with keyboard.pressed(*modifiers):
                keyboard.press(main_key)
                keyboard.release(main_key)
        
        return True
    except ValueError:
        raise
    except Exception as e:
        error(f"执行快捷键失败: {e}", "shortcut")
        raise ValueError(f"执行快捷键失败: {str(e)}")

# ============================================
# API 端点
# ============================================

@router.post("/execute", response_model=ShortcutResponse)
async def execute_shortcut_endpoint(request: ShortcutRequest):
    """执行键盘快捷键"""
    try:
        if not request.shortcut:
            raise HTTPException(status_code=400, detail="快捷键不能为空")
        
        shortcut_str = request.shortcut.strip().lower()
        info(f"执行快捷键: {shortcut_str}", "shortcut")
        
        execute_shortcut(shortcut_str)
        
        return ShortcutResponse(
            status="success",
            message="快捷键执行成功"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        error(f"快捷键执行失败: {e}", "shortcut")
        raise HTTPException(status_code=500, detail=f"执行快捷键失败: {str(e)}")

@router.get("/platform")
async def get_platform_info():
    """获取当前操作系统平台信息和按键列表"""
    platform = get_platform()
    
    # 常用快捷键建议
    suggestions = {
        'windows': {
            'copy': 'ctrl+c',
            'paste': 'ctrl+v',
            'cut': 'ctrl+x',
            'select_all': 'ctrl+a',
            'undo': 'ctrl+z',
            'redo': 'ctrl+y',
            'save': 'ctrl+s',
            'print_screen': 'prtsc',
            'lock_screen': 'win+l',
            'task_manager': 'ctrl+shift+esc',
        },
        'macos': {
            'copy': 'cmd+c',
            'paste': 'cmd+v',
            'cut': 'cmd+x',
            'select_all': 'cmd+a',
            'undo': 'cmd+z',
            'redo': 'cmd+shift+z',
            'save': 'cmd+s',
        },
        'linux': {
            'copy': 'ctrl+c',
            'paste': 'ctrl+v',
            'cut': 'ctrl+x',
            'select_all': 'ctrl+a',
            'undo': 'ctrl+z',
            'redo': 'ctrl+y',
            'save': 'ctrl+s',
        }
    }
    
    # 支持的按键列表
    supported_keys = {
        'modifiers': ['ctrl', 'alt', 'shift', 'win', 'cmd'],
        'function_keys': [f'f{i}' for i in range(1, 21)],
        'navigation': ['up', 'down', 'left', 'right', 'home', 'end', 'pageup', 'pagedown'],
        'editing': ['backspace', 'delete', 'insert', 'tab', 'enter', 'esc'],
        'special': ['prtsc', 'printscreen', 'scroll_lock', 'pause', 'menu', 'caps_lock', 'num_lock'],
        'media': ['volume_up', 'volume_down', 'volume_mute', 'play_pause', 'next', 'previous', 'stop'],
        'numpad': [f'num_{i}' for i in range(10)] + ['num_enter', 'num_add', 'num_subtract', 'num_multiply', 'num_divide', 'num_decimal'],
    }
    
    note = 'Windows 完整支持所有按键' if IS_WINDOWS else f'当前平台: {platform}'
    
    return {
        'platform': platform,
        'suggestions': suggestions.get(platform, {}),
        'supported_keys': supported_keys,
        'note': note
    }

@router.get("/keys")
async def get_supported_keys():
    """获取所有支持的按键列表"""
    return {
        'modifiers': ['ctrl', 'alt', 'shift', 'win', 'cmd', 'ctrl_l', 'ctrl_r', 'alt_l', 'alt_r', 'shift_l', 'shift_r'],
        'letters': list('abcdefghijklmnopqrstuvwxyz'),
        'numbers': list('0123456789'),
        'function_keys': [f'f{i}' for i in range(1, 21)],
        'navigation': ['up', 'down', 'left', 'right', 'home', 'end', 'pageup', 'pagedown', 'pgup', 'pgdn'],
        'editing': ['backspace', 'delete', 'del', 'insert', 'ins', 'tab', 'enter', 'return', 'esc', 'escape', 'space'],
        'special': [
            'prtsc', 'printscreen', 'print_scr', 'print', 'ps',
            'scroll_lock', 'scroll', 'pause', 'break',
            'menu', 'apps', 'caps_lock', 'caps', 'num_lock', 'num'
        ],
        'media': [
            'volume_up', 'volume_down', 'volume_mute',
            'play_pause', 'play', 'pause',
            'next', 'next_track', 'previous', 'prev', 'prev_track', 'stop'
        ],

        'numpad': [
            'num_0', 'num_1', 'num_2', 'num_3', 'num_4',
            'num_5', 'num_6', 'num_7', 'num_8', 'num_9',
            'num_decimal', 'num_dot', 'num_add', 'num_subtract', 'num_minus',
            'num_multiply', 'num_star', 'num_divide', 'num_slash',
            'num_enter', 'num_return'
        ],
    }
