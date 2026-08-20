# financial-market-analysis

> ⚠️ **DISCLAIMER (IMPORTANT)**
> This project and all its content (including but not limited to: market analysis, holdings
> advice, add/reduce/take-profit/stop-loss signals, buy/sell directions, new investment
> directions, decision tracking) are provided **for learning, research and technical exchange
> only, and do NOT constitute investment advice, investment consultation, or any promise of
> returns.** **Investing involves risk; be cautious when entering the market.** Any investment
> decision shall be made independently by you, and you shall bear all risks and consequences
> yourself. The author accepts no liability for any direct or indirect loss arising from the
> use of this project.

> 📌 **Unrelated to bidding/tender monitoring services**
> This project is a **financial market analysis** skill. It does NOT provide bidding agency,
> tender monitoring, bid submission, or any procurement-service business. The words
> "tender / procurement" appearing herein refer only to public procurement-notice data sources
> used as **industry-sentiment and order-demand research data** (e.g. State Grid tender YoY as
> an equipment-sector activity indicator) — financial/industry research only.

A configurable **financial market analysis skill for DeepSeek Harness**: A-shares / funds /
QDII / gold / Asia-Pacific indices / global markets — macro, policy, geo and rule-based
analysis, plus daily reports (morning/evening), indicator tracking and decision tracking.

**Zero personal hardcoding**: holdings, delivery chats, credentials and data directory are all
configured via `config/config.example.json`; credentials are read from environment variables only.

## Features

- Multi-source data: Taikang TIPVS / AIIB / Chery / Geely / UNGM / World Bank WDS / Sina / Yahoo
  (see `references/data-source-gotchas.md`).
- Chief-Investment-Analyst style daily reports: directly tells you "where to put the money /
  when to add/reduce/take profit / new directions / risks".
- Indicator tracking: each day first re-checks the status of all prior trigger conditions
  (triggered / not-triggered / stop-loss hit), then gives today's instructions.
- Decision tracking: buy/reduce/take-profit recommendations are automatically written to the
  `decisions` table; after 30 days you can backfill to verify win rate.
- Data degradation: on data-source failure, automatically falls back per the fallback protocol
  (DB → backup source → hardcoded last resort).

## Installation

```bash
git clone <repo-url> market-intel
cd market-intel

# 1) Python dependencies
pip install -r requirements.txt
# or isolated: python3 -m pip install --target .pyreqs requests feedparser

# 2) Configure
cp config/config.example.json config/config.json
vim config/config.json   # data dir, Feishu delivery, portfolio

# 3) Prepare data dir (optional: run P0 once to init DB and ingest)
export MARKET_INTEL_ROOT="$HOME/.dsh/market_intel"
PYTHONPATH=scripts python3 scripts/run_all_p0.py
```

## Usage

### Run a morning report manually

```bash
export MARKET_INTEL_ROOT="$HOME/.dsh/market_intel"
export FEISHU_APP_ID=cli_xxx
export FEISHU_APP_SECRET=xxx
python3 scripts/render_prompts.py          # render report_prompts → rendered/
dsh --profile headless "$(cat rendered/morning.txt)"
```

### Scheduled tasks (macOS launchd)

See `examples/launchd/` (P0 ingest 07:50 / morning 09:00 / evening 16:00, weekdays),
or use cron / systemd yourself.

## Directory Layout

- `SKILL.md` — skill description (read by DSH skill scanner)
- `scripts/` — data pipeline (`_lib.py` provides configurable ROOT; `run_all_p0.py` inits DB and ingests;
  `evaluate_today*.py`/`ai_compute.py`/`hot_themes.py` etc. analysis; `decision_tracker.py` decision tracking;
  `render_prompts.py` renders report prompts)
- `report_prompts/` — morning/evening agent prompt templates (`{{placeholders}}`)
- `references/` — data sources, fallback protocol, report template, pitfalls (methodology)
- `config/config.example.json` — config sample (copy to config.json)
- `examples/launchd/` — launchd scheduled-task samples

## Configuration (config.json)

| Key | Description |
| --- | --- |
| market_intel_root | Data dir (contains scripts/db/state); default ~/.dsh/market_intel; can be overridden by env MARKET_INTEL_ROOT |
| feishu.app_id_env / app_secret_env | Env var names for Feishu credentials (never stored in repo/docs) |
| feishu.domain | Feishu API domain |
| feishu.deliver_chat_ids | chat_id list to deliver reports |
| portfolio.total_capital / positions / cash_equivalent | Total capital, positions (code/name/amount/proxy index), cash |
| reports | Morning/evening times and weekdays |
| decision_expires_days | Decision expiry days (default 30) |

## Working with DeepSeek Harness

- Put the skill in a DSH skill scan root (e.g. ~/.dsh/skills/ or project .dsh/skills/) to load it.
- Scheduled reports can be triggered via `dsh --profile headless "$(cat rendered/morning.txt)"` (see examples/launchd/).
- To place the data dir anywhere, set MARKET_INTEL_ROOT; all scripts locate files via _lib.ROOT.

## Related Projects

- **[dsh-feishu-bridge](https://github.com/pwangxo-sg/dsh-feishu-bridge)** — Full Feishu/Lark channel for DeepSeek Harness (two-way chat + Feishu approvals); pair it with this skill to receive reports on Feishu.

## Customization & Support

Need it tailored to your scenario (private data sources, multi-account holdings, custom report
templates, scheduled deployment)? Contact: **p.wangxo@gmail.com** (subject prefix "[定制]").

## License

MIT
