#!/usr/bin/env bash
# 长期运行：崩溃或断网后 30 秒自动重启。日志写到 out/monitor.log
cd "$(dirname "$0")"
mkdir -p out
# 用哪个 Python：优先环境变量 PYTHON；本机有回测用的虚拟环境（装了 pandas）就用它，模拟盘和模型喊单才能跑；否则用 python3
PY="${PYTHON:-}"
if [ -z "$PY" ] && [ -x ../backtest/.venv/bin/python ]; then PY=../backtest/.venv/bin/python; fi
PY="${PY:-python3}"
while true; do
  "$PY" -W ignore monitor.py "$@" >> out/monitor.log 2>&1
  echo "$(date) monitor 退出，30 秒后重启" >> out/monitor.log
  sleep 30
done
