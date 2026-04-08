#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
激活验证模块（Ed25519：客户端仅内置公钥，许可证由私钥离线签发）
"""

import base64
import json
import os
import re
import tempfile
import threading
from typing import Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from utils.platform_utils import get_motherboard_uuid

router = APIRouter()

# 与 scripts/issue_license.py 中 PRODUCT_ID / LICENSE_FORMAT_PREFIX 保持一致
PRODUCT_ID = "cross-screen-input"
LICENSE_FORMAT_PREFIX = "cs1"

# 打包进客户端的公钥（Raw 32 字节 → Base64）。轮换密钥时同步修改此处并发新包。
ACTIVATION_PUBLIC_KEY_B64 = "Bp9aJGLCcU9HGyThWJsKJteov2ugVLF4PeJzTqfueXE="

# 激活文件路径（使用 config 的 DATA_DIR，兼容打包与多平台）
try:
    from config import DATA_DIR

    ACTIVATION_FILE = os.path.join(DATA_DIR, "activation.json")
except Exception:
    ACTIVATION_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "activation.json")

_ed25519_public = None
_activation_file_lock = threading.Lock()


def _coerce_activated_flag(value) -> bool:
    """兼容历史脏数据（如 'false' 字符串）并统一转换为布尔值。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "y", "on"):
            return True
        if v in ("false", "0", "no", "n", "off", ""):
            return False
    return False


def _get_ed25519_public():
    global _ed25519_public
    if _ed25519_public is not None:
        return _ed25519_public
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    raw = base64.b64decode(ACTIVATION_PUBLIC_KEY_B64.encode("ascii"))
    if len(raw) != 32:
        raise RuntimeError("ACTIVATION_PUBLIC_KEY_B64 长度必须为 32 字节 Ed25519 公钥")
    _ed25519_public = Ed25519PublicKey.from_public_bytes(raw)
    return _ed25519_public


class ActivationRequest(BaseModel):
    """激活请求模型"""

    license_key: str


class ActivationStatus(BaseModel):
    """激活状态模型"""

    activated: bool
    uuid: str
    message: str
    effective_mode: str = "unknown"
    phone_requires_activation: bool = False


def normalize_uuid_for_license(uuid_str: str) -> str:
    """
    将任意设备标识规范为 24 位十六进制字符串（与签发脚本一致）。
    """
    s = (uuid_str or "").strip()
    if not s:
        s = get_motherboard_uuid() or ""
    hexonly = re.sub(r"[^a-fA-F0-9]", "", s)
    if len(hexonly) >= 24:
        return hexonly[:24].lower()
    import hashlib

    seed = hashlib.sha256(s.encode("utf-8")).hexdigest()
    return seed[:24]


def _canonical_payload_bytes(device_norm: str) -> bytes:
    obj = {"v": 1, "device": device_norm, "product": PRODUCT_ID}
    return json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _b64url_decode(segment: str) -> bytes:
    pad = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode((segment + pad).encode("ascii"))


def parse_and_verify_license(license_key: str, device_uuid_raw: str) -> Tuple[bool, str]:
    """
    验签并校验设备绑定。返回 (是否有效, 失败原因)。
    """
    blob = (license_key or "").strip()
    if not blob:
        return False, "empty"

    parts = blob.split(".")
    if len(parts) != 3 or parts[0] != LICENSE_FORMAT_PREFIX:
        return False, "format"

    try:
        msg = _b64url_decode(parts[1])
        sig = _b64url_decode(parts[2])
    except Exception:
        return False, "encoding"

    try:
        _get_ed25519_public().verify(sig, msg)
    except Exception:
        return False, "signature"

    try:
        obj = json.loads(msg.decode("utf-8"))
    except Exception:
        return False, "payload_json"

    if obj.get("v") != 1:
        return False, "payload_version"
    if obj.get("product") != PRODUCT_ID:
        return False, "product"
    device_norm = normalize_uuid_for_license(device_uuid_raw)
    if obj.get("device") != device_norm:
        return False, "device_mismatch"

    return True, "ok"


def _invalidate_if_broken(status: dict) -> dict:
    status["activated"] = _coerce_activated_flag(status.get("activated", False))
    if not status.get("activated"):
        return status
    if not status.get("license_blob"):
        status = {
            "activated": False,
            "uuid": get_motherboard_uuid(),
            "license_blob": "",
        }
        save_activation_status(status)
        return status
    ok, _ = parse_and_verify_license(status["license_blob"], get_motherboard_uuid())
    if not ok:
        status = {
            "activated": False,
            "uuid": get_motherboard_uuid(),
            "license_blob": "",
        }
        save_activation_status(status)
    return status


def load_activation_status() -> dict:
    """
    加载激活状态；若许可被篡改或与当前设备不符则自动失效。
    """
    if os.path.exists(ACTIVATION_FILE):
        try:
            with open(ACTIVATION_FILE, "r", encoding="utf-8") as f:
                status = json.load(f)
                if isinstance(status, dict):
                    return _invalidate_if_broken(status)
        except Exception:
            pass
    return {"activated": False, "uuid": get_motherboard_uuid(), "license_blob": ""}


def save_activation_status(status: dict) -> bool:
    """
    保存激活状态
    """
    try:
        os.makedirs(os.path.dirname(ACTIVATION_FILE), exist_ok=True)
        payload = json.dumps(status, ensure_ascii=False, indent=2)
        with _activation_file_lock:
            tmp_fd, tmp_path = tempfile.mkstemp(
                prefix="activation.",
                suffix=".tmp",
                dir=os.path.dirname(ACTIVATION_FILE),
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    f.write(payload)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, ACTIVATION_FILE)
            finally:
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
        return True
    except Exception:
        return False


@router.get("/uuid")
def get_device_uuid():
    """供桌面控制台展示 / 复制设备标识"""
    return {"uuid": get_motherboard_uuid()}


@router.get("/status", response_model=ActivationStatus)
def get_activation_status():
    """
    获取激活状态；uuid 始终为当前机器实时读取。
    """
    from utils.relay_station import ensure_station_for_current_network, get_current_station
    from config import HTTP_PORT

    status = load_activation_status()
    activated = _coerce_activated_flag(status.get("activated", False))
    device_uuid = get_motherboard_uuid()
    ensure_station_for_current_network(port=HTTP_PORT)
    station = get_current_station()
    effective = getattr(station, "mode", "unknown") or "unknown"
    phone_requires_activation = not activated

    if activated:
        msg = "已激活"
    else:
        msg = "请激活后使用手机端功能"

    return ActivationStatus(
        activated=activated,
        uuid=device_uuid,
        message=msg,
        effective_mode=effective,
        phone_requires_activation=phone_requires_activation,
    )


@router.post("/activate")
def activate_license(request: ActivationRequest):
    """
    激活许可证：校验 Ed25519 签名与设备绑定后写入 license_blob。
    """
    current_uuid = get_motherboard_uuid()
    ok, reason = parse_and_verify_license(request.license_key, current_uuid)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail="激活码无效" if reason != "device_mismatch" else "激活码与当前设备不匹配",
        )

    status = {
        "activated": True,
        "uuid": current_uuid,
        "license_blob": request.license_key.strip(),
    }

    if save_activation_status(status):
        return {
            "status": "success",
            "success": True,
            "activated": True,
            "message": "激活成功",
        }
    raise HTTPException(status_code=500, detail="保存激活状态失败")


@router.post("/deactivate")
def deactivate_license():
    """
    取消激活
    """
    status = {
        "activated": False,
        "uuid": get_motherboard_uuid(),
        "license_blob": "",
    }

    if save_activation_status(status):
        return {"status": "success", "success": True, "message": "已取消激活"}
    raise HTTPException(status_code=500, detail="保存激活状态失败")
