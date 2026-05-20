#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
离线激活/试用状态持久化。

设计目标不是“绝对不可逆”，而是避免把关键状态裸露在单一明文 JSON 中：
- macOS：优先 Keychain
- Windows：使用 DPAPI 保护镜像文件
- 所有平台：保留两份加密镜像，启动时按保守策略合并
"""

from __future__ import annotations

import base64
import json
import os
import platform
import secrets
import subprocess
import tempfile
import threading
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from config import DATA_DIR, USER_DATA_DIR
from utils.platform_utils import get_motherboard_uuid


PRODUCT_ID = "cross-screen-input"
KEYCHAIN_SERVICE = "com.gojocloud.crossscreeninput.activation-state"
APP_SECRET = b"kpsr-offline-state-v1::gojocloud"
_lock = threading.Lock()


def _platform_name() -> str:
    s = platform.system()
    if s == "Darwin":
        return "macos"
    if s == "Windows":
        return "windows"
    return "linux"


def _device_id() -> str:
    raw = (get_motherboard_uuid() or "").strip()
    return sha256(f"{PRODUCT_ID}|{raw}".encode("utf-8")).hexdigest()


def _derive_key() -> bytes:
    return sha256(APP_SECRET + b"|" + _device_id().encode("ascii")).digest()


def _support_dir() -> Path:
    home = Path.home()
    plat = _platform_name()
    if plat == "macos":
        return home / "Library" / "Preferences" / ".kpsr"
    if plat == "windows":
        base = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        return base / "GOJOCLOUD" / "CrossScreenInput"
    return home / ".config" / ".kpsr"


def mirror_paths() -> list[Path]:
    return [
        Path(DATA_DIR) / "activation.cache",
        _support_dir() / "activation.state",
    ]


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def _encrypt_payload(payload: dict) -> bytes:
    nonce = secrets.token_bytes(12)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ct = AESGCM(_derive_key()).encrypt(nonce, raw, PRODUCT_ID.encode("utf-8"))
    envelope = {
        "v": 1,
        "alg": "aesgcm",
        "device": _device_id(),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ct": base64.b64encode(ct).decode("ascii"),
    }
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _decrypt_payload(blob: bytes) -> Optional[dict]:
    try:
        env = json.loads(blob.decode("utf-8"))
        if env.get("v") != 1 or env.get("alg") != "aesgcm" or env.get("device") != _device_id():
            return None
        nonce = base64.b64decode(env["nonce"])
        ct = base64.b64decode(env["ct"])
        raw = AESGCM(_derive_key()).decrypt(nonce, ct, PRODUCT_ID.encode("utf-8"))
        obj = json.loads(raw.decode("utf-8"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _dpapi_protect(data: bytes) -> bytes:
    if _platform_name() != "windows":
        return data
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

        buf = ctypes.create_string_buffer(data)
        in_blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
        out_blob = DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if not crypt32.CryptProtectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
        ):
            return data
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except Exception:
        return data


def _dpapi_unprotect(data: bytes) -> bytes:
    if _platform_name() != "windows":
        return data
    try:
        import ctypes
        from ctypes import wintypes

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

        buf = ctypes.create_string_buffer(data)
        in_blob = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
        out_blob = DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        if not crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
        ):
            return data
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)
    except Exception:
        return data


def _keychain_read() -> Optional[dict]:
    if _platform_name() != "macos":
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", _device_id(), "-w"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return _decrypt_payload(base64.b64decode(result.stdout.strip().encode("ascii")))
    except Exception:
        return None


def _keychain_write(payload: dict) -> None:
    if _platform_name() != "macos":
        return
    try:
        encoded = base64.b64encode(_encrypt_payload(payload)).decode("ascii")
        subprocess.run(
            [
                "security",
                "add-generic-password",
                "-U",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                _device_id(),
                "-w",
                encoded,
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return


def _read_mirror(path: Path) -> Optional[dict]:
    try:
        if not path.exists():
            return None
        raw = path.read_bytes()
        return _decrypt_payload(_dpapi_unprotect(raw))
    except Exception:
        return None


def _write_mirror(path: Path, payload: dict) -> None:
    _atomic_write_bytes(path, _dpapi_protect(_encrypt_payload(payload)))


def _bool(v) -> bool:
    return bool(v)


def _min_positive(values: Iterable[Optional[int]]) -> Optional[int]:
    xs = [int(v) for v in values if isinstance(v, (int, float)) and int(v) > 0]
    return min(xs) if xs else None


def _max_int(values: Iterable[Optional[int]]) -> Optional[int]:
    xs = [int(v) for v in values if isinstance(v, (int, float))]
    return max(xs) if xs else None


def merge_states(states: Iterable[dict]) -> dict:
    valid = [dict(s) for s in states if isinstance(s, dict)]
    if not valid:
        return {}
    merged = max(valid, key=lambda s: int(s.get("updated_at") or 0)).copy()
    merged["device_id"] = _device_id()
    merged["trial_explicit_started"] = any(_bool(s.get("trial_explicit_started")) for s in valid)
    merged["license_ever_activated"] = any(_bool(s.get("license_ever_activated")) for s in valid)
    merged["clock_rollback_detected"] = any(_bool(s.get("clock_rollback_detected")) for s in valid)
    merged["trial_started_at"] = _min_positive(s.get("trial_started_at") for s in valid)
    merged["first_seen_at"] = _min_positive(s.get("first_seen_at") for s in valid)
    merged["last_seen_at"] = _max_int(s.get("last_seen_at") for s in valid)
    merged["updated_at"] = _max_int(s.get("updated_at") for s in valid)
    newest = max(valid, key=lambda s: int(s.get("updated_at") or 0))
    merged["activated"] = _bool(newest.get("activated"))
    merged["license_blob"] = newest.get("license_blob", "")
    return merged


def load_secure_state() -> dict:
    with _lock:
        states = []
        keychain = _keychain_read()
        if keychain:
            states.append(keychain)
        for path in mirror_paths():
            item = _read_mirror(path)
            if item:
                states.append(item)
        return merge_states(states)


def save_secure_state(payload: dict) -> bool:
    try:
        with _lock:
            normalized = dict(payload or {})
            normalized["device_id"] = _device_id()
            for path in mirror_paths():
                _write_mirror(path, normalized)
            _keychain_write(normalized)
        return True
    except Exception:
        return False
