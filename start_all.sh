#!/bin/bash

# 顶层一键启动脚本
# 自动进入「hotspot」子目录并调用原有 start_all.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$SCRIPT_DIR/hotspot" ]; then
  echo "未找到子目录：$SCRIPT_DIR/hotspot"
  echo "请确认项目目录结构是否为 Cross-screen-input/hotspot/..."
  exit 1
fi

cd "$SCRIPT_DIR/hotspot" || exit 1
exec ./start_all.sh

