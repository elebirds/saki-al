#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DISPATCHER_DIR="${ROOT_DIR}/saki-dispatcher"

PATTERN='runtime_domain client is not connected|dispatcher exited with error|orchestrator tick failed|database is not configured|runtime stream connected|executor registered|dispatcher queue full'

if rg -n --glob '*.go' "${PATTERN}" "${DISPATCHER_DIR}/cmd" "${DISPATCHER_DIR}/internal"; then
  echo "检测到未中文化日志或错误文案，请修复后再提交。"
  exit 1
fi

echo "dispatcher 日志中文化检查通过。"
