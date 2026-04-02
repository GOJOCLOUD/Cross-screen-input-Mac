#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拦截器管理路由
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, List, Any

from utils.interceptor import interceptor

router = APIRouter()


class InterceptorConfig(BaseModel):
    """拦截器配置模型"""
    enabled: bool
    rules: List[Dict[str, Any]]
    blocked_endpoints: List[str]
    allowed_endpoints: List[str]
    log_enabled: bool


class LogsRequest(BaseModel):
    """日志请求模型"""
    limit: int = 100


@router.get("/config")
def get_interceptor_config():
    """
    获取拦截器配置
    """
    return interceptor.get_config()


@router.put("/config")
def update_interceptor_config(config: InterceptorConfig):
    """
    更新拦截器配置
    """
    if interceptor.update_config(config.dict()):
        return {"status": "success", "message": "配置更新成功"}
    else:
        raise HTTPException(status_code=500, detail="配置更新失败")


@router.get("/logs")
def get_interceptor_logs(limit: int = 100):
    """
    获取拦截器日志
    """
    return interceptor.get_logs(limit)


@router.post("/test")
def test_interceptor(request: Dict[str, Any]):
    """
    测试拦截器规则
    """
    blocked, reason = interceptor.should_block(request)
    return {
        "blocked": blocked,
        "reason": reason,
        "request": request
    }


@router.post("/clear-logs")
def clear_interceptor_logs():
    """
    清除拦截器日志
    """
    try:
        import os
        log_file = interceptor.log_file
        if os.path.exists(log_file):
            os.remove(log_file)
        return {"status": "success", "message": "日志已清除"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))