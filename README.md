# financial-market-analysis

面向 DeepSeek Harness 的金融市场分析技能（通用版）：A股 / 基金 / QDII / 黄金 / 亚太指数 /
全球市场 的宏观、政策、地缘、规则化分析，以及投资日报（早报/晚报）、指标追踪、决策追踪。

零个人硬编码：持仓、投递群、凭据、数据目录全部通过 config/config.example.json 配置，
凭据只从环境变量读取。

> 仅供学习参考，不构成投资建议。

## 特性

- 多数据源：泰康 TIPVS / AIIB / 奇瑞 / 吉利 / UNGM / 世界银行 WDS / 新浪 / yfinance 等
  （详见 references/data-source-gotchas.md）。
- 首席投资分析师式日报：直接给「钱往哪放 / 什么时候加减仓止盈 / 新方向 / 风险」。
- 指标追踪：每天先核对上期所有触发条件的当前状态（已触发/未触发/已破止损），再给当天指令。
- 决策追踪：加减仓/止盈建议自动写入 decisions 表，30 天后可回填验证胜率。
- 数据降级：数据源失败时按 fallback 协议自动降级（DB → 备源 → 硬编码兜底）。

## 安装

    git clone <repo-url> market-intel
    cd market-intel

    # 1) Python 依赖
    pip install -r requirements.txt
    # 或隔离安装：python3 -m pip install --target .pyreqs requests feedparser

    # 2) 配置
    cp config/config.example.json config/config.json
    vim config/config.json   # 填数据目录、飞书投递、持仓

    # 3) 准备数据目录（可选：先跑一次 P0 建库抓数）
    export MARKET_INTEL_ROOT="$HOME/.dsh/market_intel"
    PYTHONPATH=scripts python3 scripts/run_all_p0.py

## 使用

### 手动跑一份早报

    export MARKET_INTEL_ROOT="$HOME/.dsh/market_intel"
    export FEISHU_APP_ID=cli_xxx
    export FEISHU_APP_SECRET=xxx
    python3 scripts/render_prompts.py          # 渲染 report_prompts → rendered/
    dsh --profile headless "$(cat rendered/morning.txt)"

### 定时任务（macOS launchd）

参考 examples/launchd/（P0 入库 07:50 / 早报 09:00 / 晚报 16:00，工作日），
或自行配置 cron / systemd。

## 目录结构

- SKILL.md — 技能说明（DSH skill 扫描根读取）
- scripts/ — 数据管道（_lib.py 提供可配置 ROOT；run_all_p0.py 建库抓数；
  evaluate_today*.py / ai_compute.py / hot_themes.py 等分析；decision_tracker.py 决策追踪；
  render_prompts.py 渲染报告 prompt）
- report_prompts/ — 早报/晚报 agent 提示词模板（{{占位符}}）
- references/ — 数据源、fallback 协议、报告模板、pitfall（方法论）
- config/config.example.json — 配置样例（复制为 config.json）
- examples/launchd/ — launchd 定时任务样例

## 配置说明（config.json）

| 键 | 说明 |
| --- | --- |
| market_intel_root | 数据目录（含 scripts/db/state），默认 ~/.dsh/market_intel；也可用环境变量 MARKET_INTEL_ROOT 覆盖 |
| feishu.app_id_env / app_secret_env | 飞书凭据的环境变量名（凭据不入库、不入文档） |
| feishu.domain | 飞书 API 域名 |
| feishu.deliver_chat_ids | 报告投递的 chat_id 列表 |
| portfolio.total_capital / positions / cash_equivalent | 总资金、持仓（code/name/amount/proxy 代理指数）、现金 |
| reports | 早报/晚报时间与工作日 |
| decision_expires_days | 决策过期天数（默认 30） |

## 与 DeepSeek Harness 的配合

- 技能放在 DSH 的技能扫描根（如 ~/.dsh/skills/ 或项目 .dsh/skills/）即被加载。
- 定时日报可用 dsh --profile headless "$(cat rendered/morning.txt)" 触发（见 examples/launchd/）。
- 如需把数据目录放到任意位置，设 MARKET_INTEL_ROOT 即可，所有脚本均通过 _lib.ROOT 定位。

## License

MIT
