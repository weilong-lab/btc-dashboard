#!/usr/bin/env bash
# 长期运行：崩溃或断网后 30 秒自动重启。日志写到 out/monitor.log
cd "$(dirname "$0")"
mkdir -p out
# 用哪个 Python：优先环境变量 PYTHON；本机有回测用的虚拟环境（装了 pandas）就用它，模拟盘和模型喊单才能跑；否则用 python3
PY="${PYTHON:-}"
if [ -z "$PY" ] && [ -x ../backtest/.venv/bin/python ]; then PY=../backtest/.venv/bin/python; fi
PY="${PY:-python3}"
# Key 和令牌不写进任何文件：DeepSeek Key 从 macOS 钥匙串读（服务名 btc-dashboard-deepseek）；
# 配了 GITHUB_REPO / RECORDS_REPO 但没给 GITHUB_TOKEN 时，用本机 gh 登录的令牌
if [ -z "${DEEPSEEK_API_KEY:-}" ] && command -v security >/dev/null 2>&1; then
  k=$(security find-generic-password -s btc-dashboard-deepseek -w 2>/dev/null || true)
  if [ -n "$k" ]; then export DEEPSEEK_API_KEY="$k"; fi
fi
if [ -z "${GITHUB_TOKEN:-}" ] && { [ -n "${GITHUB_REPO:-}" ] || [ -n "${RECORDS_REPO:-}" ]; } && command -v gh >/dev/null 2>&1; then
  t=$(gh auth token 2>/dev/null || true)
  if [ -n "$t" ]; then export GITHUB_TOKEN="$t"; fi
fi
while true; do
  "$PY" -W ignore monitor.py "$@" >> out/monitor.log 2>&1
  echo "$(date) monitor 退出，30 秒后重启" >> out/monitor.log
  sleep 30
done
