#!/usr/bin/env bash
# 长期运行：崩溃或断网后 30 秒自动重启。日志写到 out/monitor.log
cd "$(dirname "$0")"
mkdir -p out
while true; do
  python3 monitor.py "$@" >> out/monitor.log 2>&1
  echo "$(date) monitor 退出，30 秒后重启" >> out/monitor.log
  sleep 30
done
