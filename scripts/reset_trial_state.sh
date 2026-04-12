#!/usr/bin/env bash
# 回到「开始试用」之前：清除安装版用户数据中的协议与试用字段（macOS）。
# 开发目录下的数据：hotspot/backend/data/activation.json + hotspot/.kpsr_user/eula_accepted.json
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

clean_activation_json() {
  cat <<'JSON'
{
  "activated": false,
  "uuid": "",
  "license_blob": "",
  "trial_duration_seconds": 30,
  "clock_rollback_detected": false
}
JSON
}

echo "==> 安装版用户目录（Electron：kpsr-desktop）"
APP_UD="$HOME/Library/Application Support/kpsr-desktop"
if [[ -d "$APP_UD" ]]; then
  rm -f "$APP_UD/eula_accepted.json"
  mkdir -p "$APP_UD/data"
  clean_activation_json >"$APP_UD/data/activation.json"
  echo "    已写入 $APP_UD/data/activation.json ，已删除 eula_accepted.json（若存在）"
else
  echo "    未找到 $APP_UD ，跳过"
fi

echo "==> 仓库开发数据（文件夹调试）"
mkdir -p "$ROOT/hotspot/backend/data"
mkdir -p "$ROOT/hotspot/.kpsr_user"
clean_activation_json >"$ROOT/hotspot/backend/data/activation.json"
rm -f "$ROOT/hotspot/.kpsr_user/eula_accepted.json"
echo "    已写入 $ROOT/hotspot/backend/data/activation.json"
echo "    已删除 $ROOT/hotspot/.kpsr_user/eula_accepted.json（若存在）"

echo "完成。请完全退出「跨屏输入」后重新打开。"
