#!/bin/bash

# 启动所有服务的脚本
echo "=================================="
echo "启动所有服务..."
echo "=================================="

# 清理端口
echo "清理端口..."
sudo lsof -ti :2345 | xargs kill -9 2>/dev/null || true
sudo lsof -ti :8000 | xargs kill -9 2>/dev/null || true
sudo lsof -ti :9000 | xargs kill -9 2>/dev/null || true
echo "端口清理完成"

# 启动局域网中转服务器（后台，端口 9000，供局域网模式使用）
echo "启动局域网中转站..."
cd "$(dirname "$0")/../lan" && python3 relay_server.py > ../hotspot/logs/relay.log 2>&1 &
sleep 1

# 启动主服务（后台运行）
echo "启动主服务..."
cd "$(dirname "$0")/backend" && python3 main.py > ../logs/main.log 2>&1 &
MAIN_PID=$!
sleep 3

# 检查服务状态
echo "=================================="
echo "服务启动状态检查"
echo "=================================="

# 检查主服务
if lsof -i :2345 > /dev/null 2>&1; then
    echo "✅ 主服务已启动 (端口: 2345)"
    echo "   电脑端界面: http://localhost:2345"
    # 获取本地IP
    LOCAL_IP=$(ifconfig | grep 'inet ' | grep -v '127.0.0.1' | head -1 | awk '{print $2}')
    if [ -n "$LOCAL_IP" ]; then
        echo "   手机端界面: http://$LOCAL_IP:2345/phone"
    fi
else
    echo "❌ 主服务启动失败"
    cat ../logs/main.log | tail -20
fi

# 检查局域网中转站
if lsof -i :9000 > /dev/null 2>&1; then
    echo "✅ 局域网中转站已启动 (端口: 9000)"
    echo "   管理界面: http://localhost:9000"
else
    echo "⚠️ 局域网中转站未启动（局域网模式需手动启动 lan/start.sh）"
fi

echo "=================================="
echo "所有服务启动完成！"
echo "=================================="
echo ""
echo "操作提示:"
echo "1. 打开 http://localhost:2345 访问电脑端界面"
echo "2. 电脑端可切换「热点模式」或「局域网模式」"
echo "3. 如有问题，请查看 logs 目录下的日志文件"
echo ""
echo "要停止所有服务，请运行: ./stop_all.sh"
echo "=================================="
