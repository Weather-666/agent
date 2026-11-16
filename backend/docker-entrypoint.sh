#!/usr/bin/env bash
# backend 启动入口：
# 1) 若未显式配置 EXPERT_ACP_AUTH_TOKEN，则从网关自举产物读取 backend-acp 虚拟 key；
# 2) 若未显式配置 EXPERT_AGENT_GATEWAY_MODEL_API_KEY，则从自举产物读取 LLM 数据面 key
#    （发布专家时写进 codex runtime 的 auth.json，codex 经它调用网关模型路由）；
# 3) 有参数时透传执行（compose 的 backend-init 用它跑 scripts/bootstrap_admin.py）；
# 4) 无参数时启动 FastAPI。
set -euo pipefail

if [ -z "${EXPERT_ACP_AUTH_TOKEN:-}" ] && [ -s /bootstrap/backend-acp.key ]; then
  export EXPERT_ACP_AUTH_TOKEN="$(cat /bootstrap/backend-acp.key)"
  echo "EXPERT_ACP_AUTH_TOKEN auto-loaded from gateway bootstrap" >&2
fi

if [ -z "${EXPERT_AGENT_GATEWAY_MODEL_API_KEY:-}" ] && [ -s /bootstrap/llm-data.key ]; then
  export EXPERT_AGENT_GATEWAY_MODEL_API_KEY="$(cat /bootstrap/llm-data.key)"
  echo "EXPERT_AGENT_GATEWAY_MODEL_API_KEY auto-loaded from gateway bootstrap" >&2
fi

if [ $# -gt 0 ]; then
  exec "$@"
fi

exec python -m uvicorn app.main:app --host 0.0.0.0 --port 15000
