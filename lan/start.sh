#!/bin/bash
# 启动局域网中转服务器（端口 9000）
cd "$(dirname "$0")"
python3 relay_server.py
