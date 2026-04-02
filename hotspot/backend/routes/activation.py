#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
激活验证模块
"""

import os
import json
import hashlib
import re
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from utils.platform_utils import get_motherboard_uuid

router = APIRouter()

# 激活文件路径（使用 config 的 DATA_DIR，兼容打包与多平台）
try:
    from config import DATA_DIR
    ACTIVATION_FILE = os.path.join(DATA_DIR, 'activation.json')
except Exception:
    ACTIVATION_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'activation.json')


class ActivationRequest(BaseModel):
    """激活请求模型"""
    license_key: str


class ActivationStatus(BaseModel):
    """激活状态模型"""

    activated: bool
    uuid: str
    message: str
    # 内部中转站模式（hotspot/lan），仅作诊断展示；激活策略不再区分网段
    effective_mode: str = "unknown"
    # 未激活时手机端相关能力是否必须先完成激活（现统一：未激活即为 True）
    phone_requires_activation: bool = False


class GenerateLicenseRequest(BaseModel):
    """生成激活码请求模型"""
    uuid: str


class GenerateLicenseResponse(BaseModel):
    """生成激活码响应模型"""
    license_key: str
    message: str


def normalize_uuid_for_license(uuid_str: str) -> str:
    """
    将任意设备标识规范为 24 位十六进制字符串，再用于生成激活码。
    避免空串、过短串、中文「获取失败」等导致激活码几乎全为分隔符而被猜中。
    """
    s = (uuid_str or "").strip()
    if not s:
        s = get_motherboard_uuid() or ""
    hexonly = re.sub(r"[^a-fA-F0-9]", "", s)
    if len(hexonly) >= 24:
        return hexonly[:24].lower()
    seed = hashlib.sha256(s.encode("utf-8")).hexdigest()
    return seed[:24]


def generate_license_key(uuid):
    """
    根据设备标识生成激活码（确定性）
    """
    normalized = normalize_uuid_for_license(uuid)
    shuffled = normalized[:24]
    groups = [shuffled[i : i + 4] for i in range(0, 24, 4)]
    license_key = "-".join(groups).upper()
    return license_key


def hash_license_key(license_key):
    """
    对激活码进行哈希处理，用于密文存储
    """
    return hashlib.sha256(license_key.encode()).hexdigest()


def verify_license_key(license_key, stored_hash):
    """
    验证激活码是否正确
    """
    return hash_license_key(license_key) == stored_hash


def load_activation_status():
    """
    加载激活状态
    """
    if os.path.exists(ACTIVATION_FILE):
        try:
            with open(ACTIVATION_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"activated": False, "uuid": get_motherboard_uuid(), "license_key_hash": ""}


def save_activation_status(status):
    """
    保存激活状态
    """
    try:
        os.makedirs(os.path.dirname(ACTIVATION_FILE), exist_ok=True)
        with open(ACTIVATION_FILE, 'w', encoding='utf-8') as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


@router.get("/status", response_model=ActivationStatus)
def get_activation_status():
    """
    获取激活状态；uuid 始终为当前机器实时读取（不沿用旧文件，避免换机/修复后仍显示错误 UUID）。
    """
    from utils.relay_station import ensure_station_for_current_network, get_current_station
    from config import HTTP_PORT

    status = load_activation_status()
    activated = bool(status.get("activated", False))
    device_uuid = get_motherboard_uuid()
    ensure_station_for_current_network(port=HTTP_PORT)
    station = get_current_station()
    effective = getattr(station, "mode", "unknown") or "unknown"
    # 不再按网段区分「热点 vs 路由器局域网」：未激活则统一要求激活后再使用手机端能力
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
    激活许可证
    """
    current_uuid = get_motherboard_uuid()
    status = load_activation_status()

    # 生成期望的激活码（用于验证）
    expected_license = generate_license_key(current_uuid)
    
    # 验证激活码是否正确
    if request.license_key == expected_license:
        # 保存哈希后的激活码
        status = {
            "activated": True,
            "uuid": current_uuid,
            "license_key_hash": hash_license_key(request.license_key)
        }
        
        if save_activation_status(status):
            return {"status": "success", "message": "激活成功"}
        else:
            raise HTTPException(status_code=500, detail="保存激活状态失败")
    else:
        raise HTTPException(status_code=400, detail="激活码无效")


@router.post("/deactivate")
def deactivate_license():
    """
    取消激活
    """
    status = {
        "activated": False,
        "uuid": get_motherboard_uuid(),
        "license_key_hash": ""
    }
    
    if save_activation_status(status):
        return {"status": "success", "message": "已取消激活"}
    else:
        raise HTTPException(status_code=500, detail="保存激活状态失败")


@router.post("/generate", response_model=GenerateLicenseResponse)
def generate_license(request: GenerateLicenseRequest):
    """
    生成激活码（用于测试或管理）
    """
    license_key = generate_license_key(request.uuid)
    return GenerateLicenseResponse(
        license_key=license_key,
        message="激活码生成成功"
    )
