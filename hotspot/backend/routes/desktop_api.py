#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电脑端控制台API
提供电脑端界面所需的数据接口；访问信息与连接状态由中转站模块提供。
"""

import os
import json
import socket
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any

from utils.logger import app_logger
from utils.relay_station import (
    get_current_station,
    init_relay_station,
    ensure_station_for_current_network,
    get_manual_mode,
)
from config import (
    HTTP_PORT,
    USER_DATA_DIR,
    get_http_port,
    save_http_port,
    is_chromium_forbidden_web_port,
)

router = APIRouter()

# 用户协议版本：更新协议正文时请 bump，以要求用户重新确认
EULA_VERSION = "2026-01"
EULA_FILE = os.path.join(USER_DATA_DIR, "eula_accepted.json")


@router.get("/eula-status")
async def get_eula_status() -> Dict[str, Any]:
    """是否已同意当前版本用户协议（持久化在用户目录，不依赖浏览器 localStorage）。"""
    accepted = False
    if os.path.isfile(EULA_FILE):
        try:
            with open(EULA_FILE, "r", encoding="utf-8") as f:
                j = json.load(f)
            accepted = bool(j.get("accepted")) and j.get("version") == EULA_VERSION
        except Exception:
            pass
    return {"accepted": accepted, "version": EULA_VERSION}


@router.post("/eula-accept")
async def post_eula_accept() -> Dict[str, Any]:
    """记录用户已同意当前版本协议。"""
    try:
        os.makedirs(USER_DATA_DIR, exist_ok=True)
        with open(EULA_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"accepted": True, "version": EULA_VERSION},
                f,
                ensure_ascii=False,
                indent=2,
            )
        # 试用开始由用户点击「开始试用」后 POST /trial-start，不在此处自动开跑
        return {"success": True, "version": EULA_VERSION}
    except Exception as e:
        app_logger.error(f"写入 eula 失败: {e}", "desktop_api")
        raise HTTPException(status_code=500, detail="保存失败") from e


@router.post("/trial-start")
async def post_trial_start() -> Dict[str, Any]:
    """
    在用户已同意当前版本协议的前提下，开始试用（仅首次写入 trial_started_at）。
    与「仅保存协议」分离：正常流程为同意协议后再点此逻辑，或由前端连续调用 eula-accept + trial-start。
    """
    accepted = False
    if os.path.isfile(EULA_FILE):
        try:
            with open(EULA_FILE, "r", encoding="utf-8") as f:
                j = json.load(f)
            accepted = bool(j.get("accepted")) and j.get("version") == EULA_VERSION
        except Exception:
            pass
    if not accepted:
        raise HTTPException(status_code=400, detail="请先同意用户协议")
    try:
        from routes.activation import start_trial_if_needed

        start_trial_if_needed()
        return {"success": True}
    except Exception as e:
        app_logger.error(f"trial-start 失败: {e}", "desktop_api")
        raise HTTPException(status_code=500, detail="试用启动失败") from e


@router.get("/access-info")
async def get_access_info() -> Dict[str, Any]:
    """
    获取访问信息（由当前中转站提供；自动模式下会按网络刷新）
    """
    try:
        ensure_station_for_current_network(port=HTTP_PORT)
        station = get_current_station()
        data = station.get_access_info()
        app_logger.info(
            f"返回访问信息: hotspot_ip={data.get('hotspot_ip')}, port={data.get('port')}",
            "desktop_api",
        )
        return data
    except Exception as e:
        app_logger.error(f"获取访问信息失败: {e}", "desktop_api")
        return {
            "hotspot_ip": None,
            "port": HTTP_PORT,
            "phone_url": f"http://localhost:{HTTP_PORT}/phone",
            "qrcode_url": f"http://localhost:{HTTP_PORT}/phone",
            "localhost_url": f"http://localhost:{HTTP_PORT}",
            "error": str(e),
        }


@router.get("/status")
async def get_status() -> Dict[str, Any]:
    """
    获取服务状态（连接相关由中转站提供；自动模式下会按网络刷新）
    """
    try:
        ensure_station_for_current_network(port=HTTP_PORT)
        station = get_current_station()
        data = station.get_status()
        port = data["port"]

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.1)
                result = sock.connect_ex(("localhost", port))
                data["server_running"] = result == 0
        except Exception:
            data["server_running"] = False

        try:
            from routes.mouse_listener import is_listener_running, get_permission_snapshot
            data["mouse_listener_status"] = is_listener_running()
            data["mouse_permission"] = get_permission_snapshot()
            data["mouse_permission_hint"] = data["mouse_permission"].get("message")
        except Exception:
            data["mouse_listener_status"] = False
            data["mouse_permission"] = {
                "platform": "unknown",
                "has_accessibility": False,
                "has_input_monitoring": False,
                "all_granted": False,
                "message": "权限状态读取失败",
            }
            data["mouse_permission_hint"] = "权限状态读取失败"

        data["timestamp"] = app_logger._create_entry("INFO", "", "desktop_api")[
            "timestamp"
        ]
        app_logger.info(
            f"返回状态信息: server_running={data['server_running']}, mouse_listener={data['mouse_listener_status']}",
            "desktop_api",
        )
        return data
    except Exception as e:
        app_logger.error(f"获取状态信息失败: {e}", "desktop_api")
        return {
            "server_running": False,
            "port": HTTP_PORT,
            "hotspot_connected": False,
            "hotspot_ip": None,
            "mouse_listener_status": False,
            "mouse_permission": {
                "platform": "unknown",
                "has_accessibility": False,
                "has_input_monitoring": False,
                "all_granted": False,
                "message": "状态获取失败",
            },
            "mouse_permission_hint": "状态获取失败",
            "error": str(e),
        }


class ModeRequest(BaseModel):
    mode: str  # "auto" | "hotspot" | "lan"


class HttpPortRequest(BaseModel):
    http_port: int


@router.get("/settings")
async def get_desktop_settings() -> Dict[str, Any]:
    """
    当前进程实际监听端口与配置解析结果（修改 settings.json 后需重启进程才监听新端口）。
    """
    return {
        "listening_port": HTTP_PORT,
        "configured_port": get_http_port(),
    }


@router.post("/port")
async def set_http_port(req: HttpPortRequest) -> Dict[str, Any]:
    """写入用户目录 settings.json；需完全重启应用后生效。"""
    if not (1024 <= req.http_port <= 65535):
        raise HTTPException(status_code=400, detail="无效端口（需为 1024–65535）")
    if is_chromium_forbidden_web_port(req.http_port):
        raise HTTPException(
            status_code=400,
            detail="该端口被 Chromium/Electron 禁止用于本地网页（例如 6666、6000）。请改用其它端口（如 2345、8080、9000）。程序不会自动改回默认端口。",
        )
    if not save_http_port(req.http_port):
        raise HTTPException(status_code=400, detail="保存失败")
    return {
        "success": True,
        "message": "端口已保存，请完全退出并重新启动应用后生效",
        "http_port": get_http_port(),
    }


@router.get("/mode")
async def get_mode() -> Dict[str, Any]:
    """
    获取当前连接模式（manual_mode + effective_mode）
    """
    ensure_station_for_current_network(port=HTTP_PORT)
    station = get_current_station()
    manual = get_manual_mode()
    return {
        "mode": manual or "auto",
        "effective_mode": station.mode,
    }


@router.post("/mode")
async def set_mode(request: ModeRequest) -> Dict[str, Any]:
    """
    设置当前连接模式。
    - auto: 根据网络自动选择
    - hotspot: 强制热点直连
    - lan: 强制局域网中转
    """
    mode = request.mode
    if mode not in ("auto", "hotspot", "lan"):
        raise HTTPException(status_code=400, detail="不支持的模式")

    station = init_relay_station(mode=mode, port=HTTP_PORT)
    app_logger.info(f"切换连接模式为: {mode}", "desktop_api")

    info = station.get_access_info()
    info["mode"] = "auto" if mode == "auto" else mode
    info["effective_mode"] = station.mode
    return info