#!/bin/bash

# 停止所有服务的脚本
echo "=================================="
echo "停止所有服务..."
echo "=================================="

# 停止主服务（端口 2345）
echo "停止主服务..."
sudo lsof -ti :2345 | xargs kill -9 2>/dev/null || true

# 停止激活码生成器（端口 8000）
echo "停止激活码生成器..."
sudo lsof -ti :8000 | xargs kill -9 2>/dev/null || true

# 停止局域网中转站（端口 9000）
echo "停止局域网中转站..."
sudo lsof -ti :9000 | xargs kill -9 2>/dev/null || true

echo "=================================="
echo "所有服务已停止！"
echo "=================================="
