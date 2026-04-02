#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中转站模块（可插拔）
- 热点模式：本机直连，手机通过私有网 IP 访问本机服务
- 局域网模式：预留，后续可接入独立中转站与设备标签
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from utils.platform_utils import get_motherboard_uuid
from utils.lan_ws_client import start_lan_ws_client

try:
    from config import HTTP_PORT as _HTTP_PORT
except Exception:
    _HTTP_PORT = 2345

# 当前使用的中转站实例
_current_station: Optional["RelayStation"] = None
# 手动指定模式：None=自动根据网络，hotspot/lan=强制
_manual_mode: Optional[str] = None

# 本机私有 IP 列表缓存（模式判定须看「全部网卡」，不能只看列表首项）
_cached_private_ip_list: Optional[list] = None
_cached_primary_ip_at: float = 0
_PRIMARY_IP_TTL_SEC = 30


def _collect_private_ips_from_os() -> list:
    """枚举本机所有私有 IPv4（顺序不保证稳定，勿单独用 [0] 做模式判定）。"""
    private_ips: list = []
    try:
        import platform

        system = platform.system()
        if system == "Darwin":
            result = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5)
            out = result.stdout or ""
            private_ips = re.findall(r"inet\s+(10\.\d+\.\d+\.\d+)", out)
            private_ips.extend(re.findall(r"inet\s+(172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)", out))
            private_ips.extend(re.findall(r"inet\s+(192\.168\.\d+\.\d+)", out))
        elif system == "Linux":
            result = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5)
            out = result.stdout or ""
            private_ips = re.findall(r"inet\s+(10\.\d+\.\d+\.\d+)", out)
            private_ips.extend(re.findall(r"inet\s+(172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)", out))
            private_ips.extend(re.findall(r"inet\s+(192\.168\.\d+\.\d+)", out))
        else:
            result = subprocess.run(["ipconfig"], capture_output=True, text=True, timeout=5)
            out = result.stdout or ""
            private_ips = re.findall(r"IPv4 Address[^\d]*(10\.\d+\.\d+\.\d+)", out)
            private_ips.extend(re.findall(r"IPv4 Address[^\d]*(172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)", out))
            private_ips.extend(re.findall(r"IPv4 Address[^\d]*(192\.168\.\d+\.\d+)", out))
    except Exception:
        pass
    # 去重且保持大致稳定顺序
    return list(dict.fromkeys(private_ips))


def _refresh_private_ip_cache() -> None:
    global _cached_private_ip_list, _cached_primary_ip_at
    _cached_private_ip_list = _collect_private_ips_from_os()
    _cached_primary_ip_at = time.time()


def _get_cached_private_ip_list() -> list:
    """带 TTL 的私有 IP 列表。"""
    global _cached_private_ip_list
    now = time.time()
    if _cached_private_ip_list is not None and (now - _cached_primary_ip_at) < _PRIMARY_IP_TTL_SEC:
        return _cached_private_ip_list
    _refresh_private_ip_cache()
    return _cached_private_ip_list or []


def _pick_display_primary_ip(ips: list) -> Optional[str]:
    """多网卡时优先展示路由器网段 IP，避免展示顺序抖动。"""
    if not ips:
        return None
    for ip in ips:
        if ip.startswith("192.168."):
            return ip
    for ip in ips:
        parts = ip.split(".")
        if len(parts) == 4 and parts[0] == "172":
            try:
                b = int(parts[1])
            except ValueError:
                continue
            if b == 20 and parts[2] == "10":
                continue
            if 16 <= b <= 31:
                return ip
    return ips[0]


def _get_primary_private_ip() -> Optional[str]:
    """获取本机主私有网 IP（带短期缓存；展示用）"""
    ips = _get_cached_private_ip_list()
    if not ips:
        return None
    return _pick_display_primary_ip(ips)


def classify_mode_from_private_ips(ips: list) -> str:
    """
    根据「全部」私有 IP 判定自动模式（仅影响内部中转站类型），避免多网卡时 ipconfig 顺序变化导致 hotspot/lan 抖动。
    激活是否必填与网段无关，由 activation 模块统一处理。
    规则：
    - 若存在典型「路由器/局域网」网段（192.168.x、172.16–31 且非 172.20.10.x iPhone 热点段）→ lan
    - 否则若仅有 10.x 或 172.20.10.x 等 → hotspot
    """
    if not ips:
        return "hotspot"
    has_lan = False
    has_only_hotspot_shape = False
    for ip in ips:
        parts = ip.split(".")
        if len(parts) != 4:
            continue
        try:
            a, b = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if a == 192 and b == 168:
            has_lan = True
            break
        if a == 172 and 16 <= b <= 31:
            if b == 20 and parts[2] == "10":
                has_only_hotspot_shape = True
            else:
                has_lan = True
                break
        if a == 10:
            has_only_hotspot_shape = True
    if has_lan:
        return "lan"
    if has_only_hotspot_shape:
        return "hotspot"
    return "hotspot"


def get_auto_mode_from_network() -> str:
    """
    根据当前网络自动选择模式：
    - 多网卡时综合全部 IPv4，不依赖单一「第一个」地址
    - 10.x / 172.20.10.x（iPhone 热点常见）→ hotspot
    - 192.168.x.x / 其他 172.16-31（路由器等）→ lan
    """
    ips = _get_cached_private_ip_list()
    return classify_mode_from_private_ips(ips)


def set_manual_mode(mode: Optional[str]) -> None:
    """设置手动模式：None=自动，hotspot/lan=强制"""
    global _manual_mode
    _manual_mode = mode if mode in ("hotspot", "lan") else None


def get_manual_mode() -> Optional[str]:
    """获取当前手动模式：None=自动，hotspot/lan=强制"""
    return _manual_mode


def get_effective_mode() -> str:
    """获取当前生效的模式（自动或手动）"""
    if _manual_mode:
        return _manual_mode
    return get_auto_mode_from_network()


def ensure_station_for_current_network(port: int = None) -> RelayStation:
    """
    根据当前有效模式（自动或手动）确保 _current_station 正确，必要时重新初始化。
    """
    if port is None:
        port = _HTTP_PORT
    global _current_station
    effective = get_effective_mode()
    current_mode = _current_station.mode if _current_station else None
    if current_mode != effective:
        if effective == "hotspot":
            _current_station = HotspotStation(port=port)
        else:
            # 局域网模式：使用内置中转站（与主服务同端口，通过 /lan/ws 提供 WebSocket）
            _current_station = LanRelayStation(port=port, relay_host="127.0.0.1", relay_port=port)
    return _current_station


def is_private_ip(ip: str) -> bool:
    """检查 IP 是否在允许的私有网段（10/172.16-31/192.168/127.0.0.1/::1）"""
    if ip in ("127.0.0.1", "localhost", "::1"):
        return True
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    if parts[0] == "10":
        return True
    if parts[0] == "172" and 16 <= int(parts[1]) <= 31:
        return True
    if parts[0] == "192" and parts[1] == "168":
        return True
    return False


class RelayStation(ABC):
    """中转站抽象：统一访问信息、状态与访问控制，便于切换热点/局域网等模式"""

    @abstractmethod
    def get_access_info(self) -> Dict[str, Any]:
        """返回电脑端/手机端访问所需信息（phone_url、qrcode_url 等）"""
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """返回与连接方式相关的状态（如是否已连接、展示用 IP 等）"""
        pass

    @abstractmethod
    def is_request_allowed(self, client_ip: str) -> bool:
        """是否允许该 IP 访问本服务（用于中间件）"""
        pass

    @abstractmethod
    def get_local_ip(self) -> str:
        """获取本机局域网 IP（用于健康检查等）"""
        pass

    @property
    @abstractmethod
    def mode(self) -> str:
        """当前模式标识，如 'hotspot' / 'lan_relay'"""
        pass


class HotspotStation(RelayStation):
    """
    热点模式中转站：本机即中转站，通过私有网 IP 直连。
    手机连热点或同一局域网后访问本机 IP:port/phone。
    """

    MODE = "hotspot"

    def __init__(self, port: int = None):
        self._port = port if port is not None else _HTTP_PORT

    @property
    def mode(self) -> str:
        return self.MODE

    def _get_private_ip(self) -> Optional[str]:
        """从本机网卡获取私有网 IP（10/172.16-31/192.168）"""
        try:
            import platform

            system = platform.system()
            private_ips = []

            if system == "Darwin":
                result = subprocess.run(
                    ["ifconfig"], capture_output=True, text=True, timeout=5
                )
                private_ips = re.findall(r"inet\s+(10\.\d+\.\d+\.\d+)", result.stdout)
                private_ips.extend(
                    re.findall(
                        r"inet\s+(172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)",
                        result.stdout,
                    )
                )
                private_ips.extend(
                    re.findall(r"inet\s+(192\.168\.\d+\.\d+)", result.stdout)
                )
            elif system == "Linux":
                result = subprocess.run(
                    ["ifconfig"], capture_output=True, text=True, timeout=5
                )
                private_ips = re.findall(r"inet\s+(10\.\d+\.\d+\.\d+)", result.stdout)
                private_ips.extend(
                    re.findall(
                        r"inet\s+(172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)",
                        result.stdout,
                    )
                )
                private_ips.extend(
                    re.findall(r"inet\s+(192\.168\.\d+\.\d+)", result.stdout)
                )
            else:
                result = subprocess.run(
                    ["ipconfig"], capture_output=True, text=True, timeout=5
                )
                private_ips = re.findall(
                    r"IPv4 Address[^\d]*(10\.\d+\.\d+\.\d+)", result.stdout
                )
                private_ips.extend(
                    re.findall(
                        r"IPv4 Address[^\d]*(172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)",
                        result.stdout,
                    )
                )
                private_ips.extend(
                    re.findall(
                        r"IPv4 Address[^\d]*(192\.168\.\d+\.\d+)", result.stdout
                    )
                )
                if not private_ips:
                    private_ips = re.findall(r"(10\.\d+\.\d+\.\d+)", result.stdout)
                    private_ips.extend(
                        re.findall(
                            r"(172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)",
                            result.stdout,
                        )
                    )
                    private_ips.extend(
                        re.findall(r"(192\.168\.\d+\.\d+)", result.stdout)
                    )

            if private_ips:
                return private_ips[0]
        except Exception:
            pass
        return None

    def get_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.0.0.1", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "localhost"

    def get_access_info(self) -> Dict[str, Any]:
        hotspot_ip = self._get_private_ip()
        port = self._port
        if hotspot_ip:
            phone_url = f"http://{hotspot_ip}:{port}/phone"
            qrcode_url = phone_url
        else:
            phone_url = "未检测到热点，请先开启热点"
            qrcode_url = f"http://localhost:{port}/phone"
        return {
            "hotspot_ip": hotspot_ip,
            "port": port,
            "phone_url": phone_url,
            "qrcode_url": qrcode_url,
            "localhost_url": f"http://localhost:{port}",
        }

    def get_status(self) -> Dict[str, Any]:
        hotspot_ip = self._get_private_ip()
        return {
            "port": self._port,
            "hotspot_connected": hotspot_ip is not None,
            "hotspot_ip": hotspot_ip,
        }

    def is_request_allowed(self, client_ip: str) -> bool:
        return is_private_ip(client_ip)


class LanRelayStation(RelayStation):
    """
    局域网中转站模式：
    - 电脑本机作为「PC 端」，通过 WebSocket 连接到局域网中转服务器
    - 电脑界面展示的是中转服务器地址 + 本机标签 / 配对码
    - 目前仅提供访问信息与基本状态，具体指令转发后续按需扩展
    """

    MODE = "lan"

    def __init__(
        self,
        port: int = None,
        relay_host: str = "127.0.0.1",
        relay_port: int = None,
    ):
        self._port = port if port is not None else _HTTP_PORT
        self._relay_host = relay_host
        self._relay_port = relay_port if relay_port is not None else self._port
        # 使用主板 UUID 作为 PC 设备 ID，便于在中转站中识别
        raw_uuid = get_motherboard_uuid() or "unknown-pc"
        self._pc_id = f"pc_{raw_uuid}"

    @property
    def mode(self) -> str:
        return self.MODE

    def get_local_ip(self) -> str:
        """
        局域网模式下返回本机局域网 IP（手机可访问的地址）。
        优先用 ifconfig 获取私有网 IP（兼容校园网 192.168.x.x），
        失败时用 socket 连接外网获取出口 IP 作为备选。
        """
        ip = _get_primary_private_ip()
        if ip:
            return ip
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127."):
                return ip
        except Exception:
            pass
        return "localhost"

    def get_access_info(self) -> Dict[str, Any]:
        """
        返回给电脑端界面的访问信息：
        - relay_ws_url: 本机连中转用
        - relay_ws_url_phone: 手机连中转用（用本机局域网 IP，手机可访问）
        - phone_url / qrcode_url: 手机打开后带 mode=lan&relay_ws&pc_id，用于配对
        """
        from urllib.parse import quote

        # 内置中转站挂载在主应用 /lan 前缀下
        relay_ws_url = f"ws://{self._relay_host}:{self._relay_port}/lan/ws"
        relay_http_url = f"http://{self._relay_host}:{self._relay_port}/lan/health"
        lan_ip = self.get_local_ip()
        if lan_ip == "localhost":
            lan_ip = "127.0.0.1"
        relay_ws_url_phone = f"ws://{lan_ip}:{self._relay_port}/lan/ws"
        # 手机页地址：带参数，扫码或打开后自动走局域网中转
        base_phone = f"http://{lan_ip}:{self._port}/phone"
        phone_url = f"{base_phone}?mode=lan&relay_ws={quote(relay_ws_url_phone, safe='')}&pc_id={quote(self._pc_id, safe='')}"
        qrcode_url = phone_url

        try:
            start_lan_ws_client(relay_ws_url, self._pc_id)
        except Exception:
            pass

        return {
            "mode": self.MODE,
            "relay_ws_url": relay_ws_url,
            "relay_ws_url_phone": relay_ws_url_phone,
            "relay_http_url": relay_http_url,
            "pc_id": self._pc_id,
            "hotspot_ip": None,
            "port": self._port,
            "phone_url": phone_url,
            "qrcode_url": qrcode_url,
            "localhost_url": f"http://localhost:{self._port}",
        }

    def get_status(self) -> Dict[str, Any]:
        """
        返回与当前模式相关的状态。
        目前简单返回模式与中转服务器位置，后续可按需扩展为真正的连接检测。
        """
        return {
            "mode": self.MODE,
            "port": self._port,
            "relay_host": self._relay_host,
            "relay_port": self._relay_port,
            "hotspot_connected": True,  # 为避免前端误报，先认为“已就绪”
            "hotspot_ip": None,
        }

    def is_request_allowed(self, client_ip: str) -> bool:
        """
        局域网模式下仍然只接受私有网段访问，策略与热点模式一致。
        """
        return is_private_ip(client_ip)


def get_current_station() -> RelayStation:
    """获取当前生效的中转站实例（未初始化时按自动/手动模式创建）"""
    global _current_station
    if _current_station is None:
        ensure_station_for_current_network(port=_HTTP_PORT)
    return _current_station


def init_relay_station(mode: str = "auto", port: int = None) -> RelayStation:
    """
    初始化并设置当前中转站模式。
    - auto: 根据网络自动选择（默认）
    - hotspot: 强制热点直连
    - lan: 强制局域网中转
    """
    global _current_station
    if port is None:
        port = _HTTP_PORT
    if mode == "auto":
        set_manual_mode(None)
        return ensure_station_for_current_network(port=port)
    if mode == "hotspot":
        set_manual_mode("hotspot")
        _current_station = HotspotStation(port=port)
    elif mode == "lan":
        set_manual_mode("lan")
        # 内置中转站与主服务端口一致，通过 /lan/ws 提供 WebSocket
        _current_station = LanRelayStation(port=port, relay_host="127.0.0.1", relay_port=port)
    else:
        set_manual_mode(None)
        return ensure_station_for_current_network(port=port)
    return _current_station


__all__ = [
    "RelayStation",
    "HotspotStation",
    "LanRelayStation",
    "get_current_station",
    "init_relay_station",
    "get_effective_mode",
    "get_auto_mode_from_network",
    "set_manual_mode",
    "get_manual_mode",
    "ensure_station_for_current_network",
    "is_private_ip",
]
