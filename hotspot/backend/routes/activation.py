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
from typing import Tuple, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from utils.platform_utils import get_motherboard_uuid

router = APIRouter()

# ===== Trial / Free usage (offline) =====
# 默认 7 天试用（发布版）。可用环境变量覆盖，方便本地/CI 快速回归。
DEFAULT_TRIAL_SECONDS = 7 * 24 * 60 * 60
TRIAL_SECONDS_ENV_KEYS = ("KPSR_TRIAL_SECONDS", "KPSR_TRIAL_SECS")
TRIAL_CLOCK_ROLLBACK_TOLERANCE_SECONDS = 2


def _trial_duration_seconds() -> int:
    for k in TRIAL_SECONDS_ENV_KEYS:
        raw = (os.environ.get(k) or "").strip()
        if not raw:
            continue
        try:
            v = int(float(raw))
            if v >= 0:
                return v
        except Exception:
            pass
    return DEFAULT_TRIAL_SECONDS


def _now_ts() -> int:
    import time

    return int(time.time())


def format_trial_remaining_human(seconds: int) -> str:
    """与桌面端倒计时一致：≥1 天 / 小时 / 分钟 / 秒（单档最大单位）。"""
    s = max(0, int(seconds or 0))
    if s >= 86400:
        return f"{s // 86400} 天"
    if s >= 3600:
        return f"{s // 3600} 小时"
    if s >= 60:
        return f"{s // 60} 分钟"
    return f"{s} 秒"

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
    # 是否已使用激活码（与「试用期内对外算已激活」区分）
    license_activated: bool = False
    # 试用状态（离线）
    trial_active: bool = False
    trial_expired: bool = False
    trial_never_started: bool = True
    trial_remaining_seconds: int = 0
    clock_rollback_detected: bool = False


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


def _ensure_trial_fields(status: dict) -> dict:
    """
    确保试用辅助字段存在（时长、last_seen 等）。
    trial_started_at 仅由用户点击「开始试用」后经 POST /api/desktop/trial-start 写入，不在此自动赋值。
    """
    status = dict(status or {})
    now = _now_ts()
    changed = False

    if status.get("trial_duration_seconds") is None:
        status["trial_duration_seconds"] = _trial_duration_seconds()
        changed = True

    # 仅在“未激活且从未开始过试用”时写入开始时间；不在到期时重置
    activated = _coerce_activated_flag(status.get("activated", False))
    # 试用开始时间仅由用户点击「开始试用」并同意后写入，禁止在此自动开跑

    if status.get("last_seen_at") is None:
        status["last_seen_at"] = now
        changed = True

    if status.get("clock_rollback_detected") is None:
        status["clock_rollback_detected"] = False
        changed = True

    if changed:
        save_activation_status(status)
    return status


def start_trial_if_needed(now_ts: Optional[int] = None) -> dict:
    """
    在用户点击「开始试用」并同意协议后调用（POST /api/desktop/trial-start）。仅一次，不续命。
    - 已激活：不启动试用
    - 未激活：写入 trial_started_at、trial_explicit_started=true
    """
    try:
        status = load_activation_status()
        if _coerce_activated_flag(status.get("activated", False)):
            return status
        status = dict(status or {})
        now = int(now_ts) if now_ts is not None else _now_ts()
        changed = False

        if status.get("trial_duration_seconds") is None:
            status["trial_duration_seconds"] = _trial_duration_seconds()
            changed = True
        if status.get("trial_started_at") is None:
            status["trial_started_at"] = now
            changed = True
        if status.get("trial_explicit_started") is not True:
            status["trial_explicit_started"] = True
            changed = True
        # 与 trial_started_at 同步写入，标记为「用户显式开始试用」
        if status.get("last_seen_at") is None:
            status["last_seen_at"] = now
            changed = True
        if status.get("clock_rollback_detected") is None:
            status["clock_rollback_detected"] = False
            changed = True

        if changed:
            save_activation_status(status)
        return status
    except Exception:
        # 不影响协议写入流程
        return load_activation_status()


def get_trial_snapshot() -> dict:
    """
    返回试用快照（不抛异常）。规则：
    - 已激活：trial_active=false
    - 未激活：从 trial_started_at 起算 trial_duration_seconds
    - 若检测到明显时间回退：clock_rollback_detected=true，并直接视为到期
    """
    # 试用期开始必须绑定“已同意用户协议”。
    # 未同意前不初始化 trial_started_at，避免在未同意协议时被动“开跑”试用倒计时。
    try:
        # 复用 desktop_api 的持久化文件与版本号
        from routes.desktop_api import EULA_FILE, EULA_VERSION  # type: ignore
        import os as _os

        accepted = False
        if _os.path.isfile(EULA_FILE):
            try:
                import json as _json

                with open(EULA_FILE, "r", encoding="utf-8") as _f:
                    _j = _json.load(_f)
                accepted = bool(_j.get("accepted")) and _j.get("version") == EULA_VERSION
            except Exception:
                accepted = False
        if not accepted:
            return {
                "trial_active": False,
                "trial_expired": False,
                "trial_never_started": True,
                "trial_remaining_seconds": 0,
                "clock_rollback_detected": False,
            }
    except Exception:
        # 若协议状态读取失败，则保守：不自动开启试用
        return {
            "trial_active": False,
            "trial_expired": False,
            "trial_never_started": True,
            "trial_remaining_seconds": 0,
            "clock_rollback_detected": False,
        }

    status = load_activation_status()
    # 旧版可能只写入了 trial_started_at 而未经过「开始试用」；忽略并清理，避免一打开就算试用中
    if status.get("trial_started_at") is not None and status.get("trial_explicit_started") is not True:
        status = dict(status)
        status["trial_started_at"] = None
        save_activation_status(status)

    status = _ensure_trial_fields(status)

    activated = _coerce_activated_flag(status.get("activated", False))
    if activated:
        return {
            "trial_active": False,
            "trial_expired": False,
            "trial_never_started": False,
            "trial_remaining_seconds": 0,
            "clock_rollback_detected": bool(status.get("clock_rollback_detected", False)),
        }

    # 必须同时有「显式开始」标记与开始时间（均由 POST /trial-start 写入）
    if status.get("trial_explicit_started") is not True or status.get("trial_started_at") is None:
        return {
            "trial_active": False,
            "trial_expired": False,
            "trial_never_started": True,
            "trial_remaining_seconds": 0,
            "clock_rollback_detected": False,
        }

    now = _now_ts()
    last_seen = status.get("last_seen_at")
    try:
        last_seen = int(last_seen)
    except Exception:
        last_seen = None

    rollback = bool(status.get("clock_rollback_detected", False))
    if last_seen is not None and now < (last_seen - TRIAL_CLOCK_ROLLBACK_TOLERANCE_SECONDS):
        rollback = True

    # last_seen_at 单调递增
    if last_seen is None or now > last_seen:
        status["last_seen_at"] = now
        status["clock_rollback_detected"] = rollback
        save_activation_status(status)
    elif rollback and not bool(status.get("clock_rollback_detected", False)):
        status["clock_rollback_detected"] = True
        save_activation_status(status)

    if rollback:
        return {
            "trial_active": False,
            "trial_expired": True,
            "trial_never_started": False,
            "trial_remaining_seconds": 0,
            "clock_rollback_detected": True,
        }

    try:
        started = int(status.get("trial_started_at") or now)
    except Exception:
        started = now
    try:
        dur = int(status.get("trial_duration_seconds") or _trial_duration_seconds())
    except Exception:
        dur = _trial_duration_seconds()

    remaining = max(0, (started + max(0, dur)) - now)
    active = remaining > 0
    expired = not active
    return {
        "trial_active": active,
        "trial_expired": expired,
        "trial_never_started": False,
        "trial_remaining_seconds": int(remaining),
        "clock_rollback_detected": False,
    }


def is_phone_allowed_by_activation_or_trial() -> bool:
    """
    供 main.py 等处调用：激活或试用未到期则允许手机端功能。
    """
    try:
        # 未同意协议前，一律不放开手机端（避免绕过桌面端协议遮罩层）
        try:
            from routes.desktop_api import EULA_FILE, EULA_VERSION  # type: ignore
            import os as _os
            import json as _json

            if not _os.path.isfile(EULA_FILE):
                return False
            with open(EULA_FILE, "r", encoding="utf-8") as _f:
                _j = _json.load(_f)
            if not (bool(_j.get("accepted")) and _j.get("version") == EULA_VERSION):
                return False
        except Exception:
            return False

        status = load_activation_status()
        if _coerce_activated_flag(status.get("activated", False)):
            return True
        snap = get_trial_snapshot()
        return bool(snap.get("trial_active", False))
    except Exception:
        # 保守：异常时不要放开手机端
        return False


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
    raw_activated = _coerce_activated_flag(status.get("activated", False))
    trial = get_trial_snapshot()
    # 试用期内，对外表现为“已激活”
    activated = bool(raw_activated or bool(trial.get("trial_active", False)))
    device_uuid = get_motherboard_uuid()
    ensure_station_for_current_network(port=HTTP_PORT)
    station = get_current_station()
    effective = getattr(station, "mode", "unknown") or "unknown"
    phone_requires_activation = not activated

    rem = int(trial.get("trial_remaining_seconds", 0) or 0)
    rem_h = format_trial_remaining_human(rem)
    never_started = bool(trial.get("trial_never_started", False))
    if activated:
        # 区分真实激活 vs 试用激活态，仅影响提示文案
        msg = "已激活" if raw_activated else f"免费试用中，剩余 {rem_h}"
    else:
        if bool(trial.get("clock_rollback_detected", False)):
            msg = "检测到系统时间回退，请激活后使用手机端功能"
        elif bool(trial.get("trial_active", False)):
            msg = f"免费试用中，剩余 {rem_h}"
        elif never_started:
            msg = "未激活：可点击左上角「开始试用」或输入激活码"
        else:
            msg = "试用已到期，请激活后使用手机端功能"

    return ActivationStatus(
        activated=activated,
        uuid=device_uuid,
        message=msg,
        effective_mode=effective,
        phone_requires_activation=phone_requires_activation,
        license_activated=raw_activated,
        trial_active=bool(trial.get("trial_active", False)),
        trial_expired=bool(trial.get("trial_expired", False)),
        trial_never_started=never_started,
        trial_remaining_seconds=int(trial.get("trial_remaining_seconds", 0) or 0),
        clock_rollback_detected=bool(trial.get("clock_rollback_detected", False)),
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
