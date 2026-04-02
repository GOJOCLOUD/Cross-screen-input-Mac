#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端口管理模块
按平台杀掉占用指定端口的进程
"""

import subprocess
import sys

from utils.logger import app_logger


def kill_process_on_port(port: int) -> bool:
    """
    杀掉占用指定端口的进程

    Args:
        port: 要清理的端口号

    Returns:
        bool: 成功返回 True，失败返回 False
    """
    if sys.platform == 'win32':
        return _kill_port_windows(port)
    return _kill_port_unix(port)


def _kill_port_windows(port: int) -> bool:
    """Windows: netstat -ano 找 PID，taskkill /F /PID <pid>"""
    try:
        creationflags = 0x0800 if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        result = subprocess.run(
            ['netstat', '-ano'],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=creationflags
        )
        if result.returncode != 0:
            app_logger.info(f"端口 {port} 未被占用", "port_manager")
            return True
        # 找 LISTENING 且本地地址为 :port 的行，最后一列是 PID
        pids = set()
        for line in (result.stdout or '').splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            # 本地地址格式 0.0.0.0:2345 或 [::]:2345
            local = parts[1]
            if ':' in local:
                try:
                    _, p = local.rsplit(':', 1)
                    if int(p) == port and parts[0].upper() == 'TCP':
                        pid = parts[-1]
                        if pid.isdigit():
                            pids.add(pid)
                except ValueError:
                    continue
        if not pids:
            app_logger.info(f"端口 {port} 未被占用", "port_manager")
            return True
        app_logger.info(f"找到占用端口 {port} 的进程 PID: {list(pids)}", "port_manager")
        all_ok = True
        for pid in pids:
            kill_result = subprocess.run(
                ['taskkill', '/F', '/PID', pid],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=creationflags
            )
            if kill_result.returncode == 0:
                app_logger.info(f"成功杀掉进程 PID: {pid}", "port_manager")
            else:
                app_logger.warning(f"杀掉进程失败 PID {pid}: {kill_result.stderr}", "port_manager")
                all_ok = False
        return all_ok
    except subprocess.TimeoutExpired:
        app_logger.error("执行命令超时", "port_manager")
        return False
    except Exception as e:
        app_logger.error(f"清理端口 {port} 失败: {e}", "port_manager")
        return False


def _kill_port_unix(port: int) -> bool:
    """macOS/Linux: lsof -ti :port + kill -9"""
    try:
        result = subprocess.run(
            ['lsof', '-ti', f':{port}'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode != 0:
            app_logger.info(f"端口 {port} 未被占用", "port_manager")
            return True
        pids = [p.strip() for p in (result.stdout or '').strip().splitlines() if p.strip().isdigit()]
        if not pids:
            app_logger.info(f"端口 {port} 未被占用", "port_manager")
            return True
        app_logger.info(f"找到占用端口 {port} 的进程 PID: {pids}", "port_manager")
        all_ok = True
        for pid in pids:
            kill_result = subprocess.run(
                ['kill', '-9', pid],
                capture_output=True,
                text=True,
                timeout=5
            )
            if kill_result.returncode == 0:
                app_logger.info(f"成功杀掉进程 PID: {pid}", "port_manager")
            else:
                app_logger.warning(f"杀掉进程失败 PID {pid}: {kill_result.stderr}", "port_manager")
                all_ok = False
        return all_ok
    except subprocess.TimeoutExpired:
        app_logger.error("执行命令超时", "port_manager")
        return False
    except Exception as e:
        app_logger.error(f"清理端口 {port} 失败: {e}", "port_manager")
        return False
