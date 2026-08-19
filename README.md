# financial-market-analysis

> ⚠️ **免责声明（重要）**  
> **本项目及其中所有内容（包括但不限于：市场分析、持仓建议、加减仓/止盈/止损提示、
> 买入卖出方向、新投资方向、决策追踪等）仅供学习、研究和技术交流使用，
> 不构成任何形式的投资建议、投资咨询或收益承诺。**  
> **投资有风险，入市需谨慎。** 任何投资决策应由您自行独立判断，并自行承担全部风险与后果。
> 作者不对因使用本项目而产生的任何直接或间接损失承担责任。
> 若您依据本项目做出投资行为，视为您已完全理解并接受本免责声明。

面向 DeepSeek Harness 的金融市场分析技能（通用版）：A股 / 基金 / QDII / 黄金 / 亚太指数 /
全球市场 的宏观、政策、地缘、规则化分析，以及投资日报（早报/晚报）、指标追踪、决策追踪。

## 特性

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

## 赞助与定制

喜欢这个项目？欢迎通过以下方式支持：

- **GitHub Sponsors**：[Sponsor me](https://github.com/sponsors/pwangxo-sg) —— 点击这里赞助
- **定制服务**：如果你需要针对自己的持仓 / 数据源 / 投递渠道做定制（把技能接到你的飞书群、加新的采购/招标公告类数据源或行情数据源、调整报告风格），欢迎邮件联系：
  - 邮箱：**p.wangxo@gmail.com**（邮件标题建议带 [定制] 前缀）
- 定制内容示例：私有数据源接入、多账户持仓管理、专属报告模板、定时任务部署（macOS launchd / Linux systemd / cron）。

> 注意：本项目为开源学习项目，Sponsors 与定制服务均与投资建议无关，详见顶部免责声明。

## License

MIT
