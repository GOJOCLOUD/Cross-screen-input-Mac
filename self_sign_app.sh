#!/usr/bin/env bash
set -euo pipefail

APP_PATH="${1:-/Applications/跨屏输入.app}"

if [[ ! -d "${APP_PATH}" ]]; then
  echo "应用不存在: ${APP_PATH}"
  exit 1
fi

echo "清理扩展属性: ${APP_PATH}"
xattr -cr "${APP_PATH}" || true

echo "执行 ad-hoc 自签名: ${APP_PATH}"
codesign --force --deep --sign - "${APP_PATH}"

echo "验证 codesign:"
codesign --verify --deep --strict --verbose=2 "${APP_PATH}"

echo "评估 Gatekeeper:"
spctl --assess --type execute -vv "${APP_PATH}" || true

echo "产物摘要（SHA256）:"
shasum -a 256 "${APP_PATH}" || true

echo "完成。"
