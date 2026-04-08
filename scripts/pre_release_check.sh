#!/usr/bin/env bash
set -euo pipefail

# 说明：
# - 默认只跑轻量检查（不构建，不签名）
# - 传入 --with-dist 可执行本地无证书 mac 打包（identity=null）

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WITH_DIST=0

for arg in "$@"; do
  case "$arg" in
    --with-dist)
      WITH_DIST=1
      ;;
    *)
      echo "未知参数: $arg"
      echo "用法: scripts/pre_release_check.sh [--with-dist]"
      exit 2
      ;;
  esac
done

echo "==> 进入项目根目录: $ROOT_DIR"
cd "$ROOT_DIR"

echo "==> 1/5 Python 后端契约测试"
PYTHONPATH="hotspot/backend" python3 -m unittest discover -s hotspot/backend/tests -p "test_*.py" -v

echo "==> 2/5 Electron 主进程语法检查"
node --check electron/main.cjs

echo "==> 3/5 签名脚本语法检查"
bash -n self_sign_app.sh

echo "==> 4/5 关键未提交变更提示"
git status --short

if [[ "$WITH_DIST" -eq 1 ]]; then
  echo "==> 5/5 无证书本地打包（mac arm64, identity=null）"
  (
    cd electron
    npm run dist:mac:arm64 -- --config.mac.identity=null
  )

  if ls electron/dist/*.dmg >/dev/null 2>&1 || ls electron/dist/*.zip >/dev/null 2>&1; then
    echo "==> 产物哈希（SHA256）"
    shasum -a 256 electron/dist/*.dmg electron/dist/*.zip 2>/dev/null || true
  fi
else
  echo "==> 5/5 跳过打包（如需本地无证书打包，追加 --with-dist）"
fi

echo "==> 预发布检查完成"
