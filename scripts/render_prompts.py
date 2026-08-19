#!/usr/bin/env python3
"""把 report_prompts/*.txt 的 {{占位符}} 用 config/config.json 渲染到 rendered/。

用法:
    python3 scripts/render_prompts.py [config.json] [输出目录]
默认读取 config/config.json，输出到 rendered/。
"""
import json, os, re, sys
from pathlib import Path

def main():
    base = Path(__file__).resolve().parent.parent
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else base / "config" / "config.json"
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else base / "rendered"
    cfg = json.loads(cfg_path.read_text())

    root = os.path.expanduser(cfg.get("market_intel_root", "~/.dsh/market_intel"))
    feishu = cfg.get("feishu", {})
    port = cfg.get("portfolio", {})
    reports = cfg.get("reports", {})
    vars_ = {
        "SKILL_DIR": str(base),
        "SCRIPTS_DIR": str(base / "scripts"),
        "MARKET_INTEL_ROOT": root,
        "CASH": port.get("cash_equivalent", "?"),
        "EXPIRES": cfg.get("decision_expires_days", 30),
        "DELIVER_CHAT_IDS": ",".join(feishu.get("deliver_chat_ids", [])),
        "APP_ID_ENV": feishu.get("app_id_env", "FEISHU_APP_ID"),
        "APP_SECRET_ENV": feishu.get("app_secret_env", "FEISHU_APP_SECRET"),
        "FEISHU_DOMAIN": feishu.get("domain", "https://open.feishu.cn"),
    }
    out_dir.mkdir(exist_ok=True)
    for tpl in sorted((base / "report_prompts").glob("*.txt")):
        text = tpl.read_text()
        for k, v in vars_.items():
            text = text.replace("{{" + k + "}}", str(v))
        (out_dir / tpl.name).write_text(text)
        print("rendered:", out_dir / tpl.name)

if __name__ == "__main__":
    main()
