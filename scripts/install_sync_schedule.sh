#!/usr/bin/env bash
# SousVille — 安裝 launchd 每小時同步排程到當前使用者帳號。
#
# 安裝：
#   bash scripts/install_sync_schedule.sh
#
# 解除：
#   bash scripts/install_sync_schedule.sh --uninstall
#
# 立刻跑一次（不重啟 daemon）：
#   launchctl kickstart -k gui/$(id -u)/com.sousville.sync
#
# 看下次預定時間 + 上次結果：
#   launchctl print gui/$(id -u)/com.sousville.sync | grep -E 'state|next'

set -euo pipefail

LABEL="com.sousville.sync"
PLIST_NAME="${LABEL}.plist"
TEMPLATE_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/deploy/${PLIST_NAME}.template"
SOUSVILLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
TARGET_PLIST="${LAUNCH_AGENTS_DIR}/${PLIST_NAME}"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3)}"
DATA_DIR="${SOUSVILLE_DIR}/data"

uninstall() {
    if launchctl list 2>/dev/null | grep -q "${LABEL}"; then
        echo "▶ 解除 launchd job：${LABEL}"
        launchctl bootout "gui/$(id -u)" "${TARGET_PLIST}" 2>/dev/null || \
        launchctl unload "${TARGET_PLIST}" 2>/dev/null || true
    fi
    if [ -f "${TARGET_PLIST}" ]; then
        rm -f "${TARGET_PLIST}"
        echo "✅ 已移除 ${TARGET_PLIST}"
    else
        echo "（沒找到 ${TARGET_PLIST}，已是乾淨狀態）"
    fi
}

if [ "${1:-}" = "--uninstall" ]; then
    uninstall
    exit 0
fi

# ── 檢查環境變數 ──
if [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_SERVICE_KEY:-}" ]; then
    if [ -f "${SOUSVILLE_DIR}/.env" ]; then
        echo "▶ 從 ${SOUSVILLE_DIR}/.env 讀環境變數"
        # shellcheck disable=SC1091
        set -a
        source "${SOUSVILLE_DIR}/.env"
        set +a
    fi
fi

if [ -z "${SUPABASE_URL:-}" ] || [ -z "${SUPABASE_SERVICE_KEY:-}" ]; then
    cat <<EOF >&2
❌ 缺 SUPABASE_URL 或 SUPABASE_SERVICE_KEY。
請在 ${SOUSVILLE_DIR}/.env 加上：
    SUPABASE_URL=https://your-project.supabase.co
    SUPABASE_SERVICE_KEY=eyJ...

或者 export 到當前 shell 後再跑這個腳本。
EOF
    exit 1
fi

echo "▶ Python：${PYTHON_BIN}"
echo "▶ SousVille：${SOUSVILLE_DIR}"

mkdir -p "${LAUNCH_AGENTS_DIR}" "${DATA_DIR}"

# 先 unload 舊的（如果有）
if [ -f "${TARGET_PLIST}" ]; then
    launchctl bootout "gui/$(id -u)" "${TARGET_PLIST}" 2>/dev/null || \
    launchctl unload "${TARGET_PLIST}" 2>/dev/null || true
fi

# ── 把 template 變數展開 ──
# 用 python 做安全的字串替換（避免 sed 對特殊字元的麻煩）
python3 - <<PYEOF > "${TARGET_PLIST}"
from pathlib import Path
import os
src = Path("${TEMPLATE_FILE}").read_text(encoding="utf-8")
out = (
    src
    .replace("\${SOUSVILLE_DIR}", "${SOUSVILLE_DIR}")
    .replace("\${PYTHON_BIN}", "${PYTHON_BIN}")
    .replace("\${SUPABASE_URL}", os.environ.get("SUPABASE_URL", ""))
    .replace("\${SUPABASE_SERVICE_KEY}", os.environ.get("SUPABASE_SERVICE_KEY", ""))
)
print(out)
PYEOF

chmod 600 "${TARGET_PLIST}"  # 含 service key，鎖權限
echo "✅ 寫入 ${TARGET_PLIST}"

# ── 載入到當前使用者的 launchd ──
launchctl bootstrap "gui/$(id -u)" "${TARGET_PLIST}"
launchctl enable "gui/$(id -u)/${LABEL}"

# RunAtLoad 會立刻跑一次；額外確保踢一次
launchctl kickstart -k "gui/$(id -u)/${LABEL}" || true

echo ""
echo "✅ 已安裝 launchd job：${LABEL}"
echo "   下次自動執行：每小時整點"
echo "   Log：${DATA_DIR}/sync.log"
echo ""
echo "查狀態：    launchctl print gui/\$(id -u)/${LABEL}"
echo "立刻跑：    launchctl kickstart -k gui/\$(id -u)/${LABEL}"
echo "解除：      bash $(basename "$0") --uninstall"
