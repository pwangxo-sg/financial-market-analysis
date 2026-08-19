#!/bin/bash
# 早报 wrapper 示例：把 REPO_DIR 替换为你的技能目录
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export MARKET_INTEL_ROOT="$HOME/.dsh/market_intel"
# 飞书凭据通过环境变量注入（不写死在脚本里）
cd REPO_DIR
python3 scripts/render_prompts.py
dsh --profile headless "$(cat rendered/morning.txt)"
