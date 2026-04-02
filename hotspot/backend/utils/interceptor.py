#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
请求拦截器
用于拦截和管理手机发送到电脑的请求
"""

import os
import json
import time
from typing import Dict, List, Optional, Any


class RequestInterceptor:
    """
    请求拦截器类
    """
    
    def __init__(self):
        """
        初始化拦截器
        """
        self.config_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'data',
            'interceptor_config.json'
        )
        self.log_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'logs',
            'interceptor.log'
        )
        self.load_config()
        self.ensure_directories()
    
    def ensure_directories(self):
        """
        确保目录存在
        """
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
    
    def load_config(self):
        """
        加载配置
        """
        default_config = {
            "enabled": False,
            "rules": [],
            "blocked_endpoints": [],
            "allowed_endpoints": [],
            "log_enabled": True
        }
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                # 合并默认配置
                for key, value in default_config.items():
                    if key not in self.config:
                        self.config[key] = value
            except Exception:
                self.config = default_config
        else:
            self.config = default_config
            self.save_config()
    
    def save_config(self):
        """
        保存配置
        """
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False
    
    def log_request(self, request: Dict[str, Any], blocked: bool, reason: str):
        """
        记录请求
        """
        if not self.config.get('log_enabled', True):
            return
        
        log_entry = {
            "timestamp": time.time(),
            "datetime": time.strftime('%Y-%m-%d %H:%M:%S'),
            "method": request.get('method', 'GET'),
            "path": request.get('path', ''),
            "client_ip": request.get('client_ip', ''),
            "body": request.get('body', ''),
            "blocked": blocked,
            "reason": reason
        }
        
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        except Exception:
            pass
    
    def should_block(self, request: Dict[str, Any]) -> tuple[bool, str]:
        """
        判断是否应该拦截请求
        
        Args:
            request: 请求信息
            
        Returns:
            (是否拦截, 拦截原因)
        """
        path = request.get('path', '')
        method = request.get('method', 'GET')
        
        # 检查是否在允许列表中（优先检查，确保基本功能可用）
        allowed_endpoints = self.config.get('allowed_endpoints', [])
        for endpoint in allowed_endpoints:
            if path.startswith(endpoint):
                return False, "在允许列表中"
        
        # 检查激活状态（未激活时统一限制：仅放行激活、电脑端控制台与基础静态页）
        try:
            from routes.activation import load_activation_status

            activation_status = load_activation_status()
            if not activation_status.get("activated", False):
                if (
                    not path.startswith("/api/activation")
                    and not path.startswith("/api/interceptor")
                    and not path.startswith("/api/desktop/")
                    and not path == "/"
                    and not path.startswith("/frontend/")
                    and not path == "/phone"
                    and not (path == "/send" and method == "GET")
                    and not path.endswith(".html")
                    and not path.endswith(".css")
                    and not path.endswith(".js")
                    and not path.endswith(".png")
                    and not path.endswith(".jpg")
                    and not path.endswith(".ico")
                ):
                    return True, "设备未激活，已拦截请求"
        except Exception:
            pass
        
        if not self.config.get('enabled', False):
            return False, "拦截器未启用"
        
        # 检查是否在阻止列表中
        blocked_endpoints = self.config.get('blocked_endpoints', [])
        for endpoint in blocked_endpoints:
            if path.startswith(endpoint):
                return True, f"在阻止列表中: {endpoint}"
        
        # 检查规则
        rules = self.config.get('rules', [])
        for rule in rules:
            if 'path_pattern' in rule and path.startswith(rule['path_pattern']):
                if 'method' in rule and rule['method'] != method:
                    continue
                if rule.get('block', True):
                    return True, f"匹配规则: {rule.get('name', 'Unknown')}"
        
        return False, "未匹配任何拦截规则"
    
    def update_config(self, new_config: Dict[str, Any]) -> bool:
        """
        更新配置
        """
        self.config.update(new_config)
        return self.save_config()
    
    def get_config(self) -> Dict[str, Any]:
        """
        获取配置
        """
        return self.config
    
    def get_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取日志
        """
        logs = []
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            log_entry = json.loads(line.strip())
                            logs.append(log_entry)
                        except Exception:
                            pass
            # 按时间倒序排列，取最近的记录
            logs.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
            return logs[:limit]
        except Exception:
            return []


# 创建全局拦截器实例
interceptor = RequestInterceptor()
