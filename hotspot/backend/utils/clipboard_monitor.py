#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
剪贴板和截图监听模块
用于检测剪贴板变化或截图完成，支持按需启动/停止
"""

import hashlib
import threading
import time
from typing import Callable, Optional, Dict, List
import subprocess
import platform
import os
import glob
from pathlib import Path


def _default_screenshot_dirs():
    """按平台返回要轮询的截图目录列表"""
    if platform.system() == 'Darwin':
        return [str(Path.home() / "Desktop")]
    if platform.system() == 'Windows':
        user = os.environ.get('USERPROFILE', '') or str(Path.home())
        dirs = [
            os.path.join(user, 'Pictures', 'Screenshots'),
            os.path.join(user, 'OneDrive', 'Pictures', 'Screenshots'),
            os.path.join(user, 'Desktop'),
        ]
        return [d for d in dirs if os.path.isdir(d)] or [os.path.join(user, 'Pictures', 'Screenshots')]
    return [str(Path.home() / "Desktop")]


class ClipboardMonitor:
    """剪贴板监听器（支持 macOS / Windows / Linux）"""

    def __init__(self) -> None:
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._callbacks: Dict[str, Callable[[str], None]] = {}
        self._last_hash: Optional[str] = None
        self._last_screenshot_time: float = 0
        self._poll_interval: float = 0.2
        self._lock: threading.Lock = threading.Lock()
        self._platform: str = 'macos' if platform.system() == 'Darwin' else ('windows' if platform.system() == 'Windows' else 'linux')
        self._screenshot_dirs: List[str] = _default_screenshot_dirs()

    def _get_clipboard_content(self) -> Optional[bytes]:
        """获取剪贴板内容（用于计算哈希）"""
        try:
            if platform.system() == 'Darwin':
                result = subprocess.run(
                    ['pbpaste'],
                    capture_output=True,
                    timeout=1
                )
                return result.stdout
            if platform.system() == 'Windows':
                try:
                    import pyperclip
                    s = pyperclip.paste()
                    return (s or '').encode('utf-8', errors='replace')
                except Exception:
                    return None
            # Linux
            try:
                import pyperclip
                s = pyperclip.paste()
                return (s or '').encode('utf-8', errors='replace')
            except Exception:
                return None
        except Exception as e:
            from utils.logger import error
            error(f"获取剪贴板内容失败: {e}", source="clipboard_monitor")
            return None
    
    def _get_clipboard_hash(self) -> Optional[str]:
        """获取剪贴板内容的哈希值"""
        content = self._get_clipboard_content()
        if content is None:
            return None
        return hashlib.md5(content).hexdigest()
    
    def _get_latest_screenshot_time(self) -> float:
        """获取最新截图文件的修改时间（多目录、多命名规则）"""
        try:
            if platform.system() == 'Darwin':
                patterns_per_dir = [
                    "Screenshot*.png",
                    "屏幕截图*.png",
                ]
            elif platform.system() == 'Windows':
                patterns_per_dir = [
                    "*.png",
                    "*.jpg",
                ]
            else:
                patterns_per_dir = ["Screenshot*.png", "*.png"]
            latest_time = 0.0
            for dir_path in self._screenshot_dirs:
                for pat in patterns_per_dir:
                    pattern = os.path.join(dir_path, pat)
                    for f in glob.glob(pattern):
                        try:
                            mtime = os.path.getmtime(f)
                            if mtime > latest_time:
                                latest_time = mtime
                        except Exception:
                            pass
            return latest_time
        except Exception:
            return 0.0
    
    def _check_new_screenshot(self) -> bool:
        """检查是否有新的截图文件"""
        current_time = self._get_latest_screenshot_time()
        if current_time > self._last_screenshot_time:
            return True
        return False
    
    def _poll_loop(self) -> None:
        """轮询循环：同时检测剪贴板变化和新截图文件"""
        from utils.logger import info, error
        
        info("========== 监听开始 ==========", source="clipboard_monitor")
        
        # 记录初始状态
        self._last_hash = self._get_clipboard_hash()
        self._last_screenshot_time = self._get_latest_screenshot_time()
        
        info(f"初始剪贴板哈希: {self._last_hash}", source="clipboard_monitor")
        info(f"初始截图时间: {self._last_screenshot_time}", source="clipboard_monitor")
        info(f"截图目录: {self._screenshot_dirs}", source="clipboard_monitor")
        
        poll_count = 0
        while self._running:
            try:
                # 检查是否还有活动的监听
                with self._lock:
                    if not self._callbacks:
                        info("没有活动的监听，停止轮询", source="clipboard_monitor")
                        self._running = False
                        break
                
                poll_count += 1
                detected_change = False
                change_type = ""
                
                # 1. 检测剪贴板变化
                current_hash = self._get_clipboard_hash()
                if current_hash and current_hash != self._last_hash:
                    info(f"🎉 检测到剪贴板变化!", source="clipboard_monitor")
                    self._last_hash = current_hash
                    detected_change = True
                    change_type = "clipboard"
                
                # 2. 检测新截图文件
                current_screenshot_time = self._get_latest_screenshot_time()
                if current_screenshot_time > self._last_screenshot_time:
                    info(f"📸 检测到新截图文件!", source="clipboard_monitor")
                    info(f"  旧时间: {self._last_screenshot_time}", source="clipboard_monitor")
                    info(f"  新时间: {current_screenshot_time}", source="clipboard_monitor")
                    self._last_screenshot_time = current_screenshot_time
                    detected_change = True
                    change_type = "screenshot" if not change_type else change_type + "+screenshot"
                
                # 每5次轮询输出一次状态（约1秒一次）
                if poll_count % 5 == 0:
                    info(f"⏳ 轮询中... 第{poll_count}次", source="clipboard_monitor")
                
                # 如果检测到变化，通知所有监听者
                if detected_change:
                    info(f"✅ 检测到变化类型: {change_type}", source="clipboard_monitor")
                    
                    with self._lock:
                        callbacks_copy = dict(self._callbacks)
                    
                    info(f"准备通知 {len(callbacks_copy)} 个监听者", source="clipboard_monitor")
                    
                    for button_id, callback in callbacks_copy.items():
                        try:
                            info(f"📢 通知按钮 {button_id}", source="clipboard_monitor")
                            callback(button_id)
                            info(f"✅ 按钮 {button_id} 回调执行完成", source="clipboard_monitor")
                        except Exception as e:
                            error(f"❌ 回调执行失败: {e}", source="clipboard_monitor")
                
                time.sleep(self._poll_interval)
                
            except Exception as e:
                error(f"轮询出错: {e}", source="clipboard_monitor")
                time.sleep(0.5)
        
        info("========== 监听结束 ==========", source="clipboard_monitor")
    
    def start_monitoring(self, button_id: str, callback: Callable[[str], None]) -> None:
        """开始监听指定按钮的剪贴板变化"""
        from utils.logger import info
        
        with self._lock:
            self._callbacks[button_id] = callback
            info(f"添加监听: {button_id}, 当前监听数: {len(self._callbacks)}", source="clipboard_monitor")
        
        # 如果轮询线程未运行，启动它
        if not self._running:
            self._running = True
            # 重新获取当前剪贴板状态作为基准
            self._last_hash = self._get_clipboard_hash()
            self._thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._thread.start()
            info("启动轮询线程", source="clipboard_monitor")
    
    def stop_monitoring(self, button_id: str) -> None:
        """停止监听指定按钮"""
        from utils.logger import info
        
        with self._lock:
            if button_id in self._callbacks:
                del self._callbacks[button_id]
                info(f"移除监听: {button_id}, 剩余监听数: {len(self._callbacks)}", source="clipboard_monitor")
            
            # 如果没有监听者了，轮询会自动停止
            if not self._callbacks:
                info("没有剩余监听，轮询将自动停止", source="clipboard_monitor")
    
    def is_monitoring(self, button_id: str) -> bool:
        """检查是否正在监听指定按钮"""
        with self._lock:
            return button_id in self._callbacks
    
    def get_active_monitors(self) -> List[str]:
        """获取所有活动的监听"""
        with self._lock:
            return list(self._callbacks.keys())


# 全局单例
clipboard_monitor = ClipboardMonitor()
