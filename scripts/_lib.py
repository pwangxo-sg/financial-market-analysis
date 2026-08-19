"""
共享库: market_intel 抓取 + 存储 + 调度
所有 P0/P1 抓取脚本 import 此模块
"""
import sqlite3
import json
import time
import hashlib
import logging
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager

# ============== Paths ==============
# 数据根目录：可用环境变量 MARKET_INTEL_ROOT 覆盖（便于部署到任意位置）
import os as _os
ROOT = Path(_os.environ.get("MARKET_INTEL_ROOT") or (Path.home() / ".dsh" / "market_intel")).expanduser()
DB_PATH = ROOT / "db" / "intel.db"
LOG_PATH = ROOT / "logs"
LOG_PATH.mkdir(parents=True, exist_ok=True)

# Beijing TZ
BJT = timezone(timedelta(hours=8))


# ============== Logging ==============
def get_logger(name):
    log_file = LOG_PATH / f"{name}.log"
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger


# ============== DB ==============
SCHEMA = """
CREATE TABLE IF NOT EXISTS intel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hash TEXT UNIQUE NOT NULL,           -- 去重 hash
    source TEXT NOT NULL,                -- 来源 (reuters/fed/sec/...)
    source_type TEXT NOT NULL,           -- 类型 (news/regulator/research/event/sentiment/commodity)
    title TEXT NOT NULL,
    content TEXT,
    url TEXT,
    author TEXT,                          -- 作者/发布方
    published_at TEXT,                    -- 发布时间 (ISO 8601)
    fetched_at TEXT NOT NULL,             -- 抓取时间
    tags TEXT,                            -- JSON 数组 (china/us/finance/...)
    severity INTEGER DEFAULT 1,           -- 严重度 1-5
    extra TEXT,                           -- 额外 JSON
    used_in_rule TEXT                     -- 被哪条规则引用
);

CREATE INDEX IF NOT EXISTS idx_source ON intel(source);
CREATE INDEX IF NOT EXISTS idx_type ON intel(source_type);
CREATE INDEX IF NOT EXISTS idx_published ON intel(published_at);
CREATE INDEX IF NOT EXISTS idx_fetched ON intel(fetched_at);
CREATE INDEX IF NOT EXISTS idx_severity ON intel(severity);

-- 持仓表
CREATE TABLE IF NOT EXISTS holdings (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT,                            -- fund/etf/stock
    amount_rmb REAL,                      -- 持仓金额
    shares REAL,                          -- 持有份额
    cost_basis REAL,                      -- 成本净值
    added_at TEXT
);

-- 信号表 (规则引擎输出)
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,                   -- 标的代码
    signal_type TEXT NOT NULL,            -- add/reduce/hold/observe
    direction TEXT,                       -- long/short/hedge
    confidence INTEGER,                   -- 0-100
    rule_id TEXT NOT NULL,                -- 触发的规则 ID
    evidence TEXT,                        -- JSON: 触发证据
    generated_at TEXT NOT NULL,
    expires_at TEXT,                      -- 信号失效时间
    verified_at TEXT,                     -- 实际验证时间
    actual_outcome TEXT,                  -- actual win/loss/neutral
    pnl_pct REAL                          -- 实际盈亏 %
);

CREATE INDEX IF NOT EXISTS idx_signal_code ON signals(code);
CREATE INDEX IF NOT EXISTS idx_signal_gen ON signals(generated_at);

-- 规则定义表
CREATE TABLE IF NOT EXISTS rules (
    rule_id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    scope TEXT,                           -- fund/asset-class/cross-asset
    target_codes TEXT,                    -- JSON 数组, 适用标的
    conditions TEXT NOT NULL,             -- JSON: 条件表达式
    expected_win_rate REAL,
    expected_hold_days INTEGER,
    enabled INTEGER DEFAULT 1,
    created_at TEXT,
    backtest_result TEXT                  -- JSON: 回测结果
);

-- 决策日志 (首席投资专家签字)
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision TEXT NOT NULL,               -- 决策摘要
    rationale TEXT,                       -- 理由
    sources TEXT,                         -- 引用的 intel ID 列表
    signal_ids TEXT,                      -- 引用的 signal ID 列表
    created_at TEXT NOT NULL,
    expires_at TEXT
);
"""


@contextmanager
def get_db():
    """SQLite 连接 context manager"""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """初始化 DB schema"""
    with get_db() as conn:
        conn.executescript(SCHEMA)
    print(f"✅ DB initialized: {DB_PATH}")


# ============== Intel 存储 ==============
def make_hash(source, title, url=""):
    """去重 hash"""
    raw = f"{source}|{title}|{url}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()


def save_intel(items, source, source_type):
    """
    items: list of dicts, each with:
      - title (required)
      - content
      - url
      - author
      - published_at (ISO 8601 string)
      - tags (list of str)
      - severity (1-5)
      - extra (dict)
    Returns: (saved_count, dup_count)
    """
    if not items:
        return 0, 0

    saved = 0
    dups = 0
    now = datetime.now(BJT).isoformat(timespec="seconds")

    with get_db() as conn:
        for item in items:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            url = item.get("url", "")
            h = make_hash(source, title, url)
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO intel
                    (hash, source, source_type, title, content, url, author,
                     published_at, fetched_at, tags, severity, extra)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        h, source, source_type, title,
                        (item.get("content") or "")[:5000],
                        url,
                        item.get("author", ""),
                        item.get("published_at", now),
                        now,
                        json.dumps(item.get("tags", []), ensure_ascii=False),
                        item.get("severity", 1),
                        json.dumps(item.get("extra", {}), ensure_ascii=False),
                    ),
                )
                if conn.total_changes:
                    saved += 1
                else:
                    dups += 1
            except Exception as e:
                print(f"⚠️ save_intel error: {e}")
    return saved, dups


def query_intel(source=None, source_type=None, since=None, limit=50):
    """查询 intel"""
    sql = "SELECT * FROM intel WHERE 1=1"
    params = []
    if source:
        sql += " AND source = ?"
        params.append(source)
    if source_type:
        sql += " AND source_type = ?"
        params.append(source_type)
    if since:
        sql += " AND published_at >= ?"
        params.append(since)
    sql += " ORDER BY published_at DESC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def stats_by_source(days=1):
    """统计各源抓取量"""
    cutoff = (datetime.now(BJT) - timedelta(days=days)).isoformat()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT source, source_type, COUNT(*) as n,
                      MAX(published_at) as latest
               FROM intel
               WHERE fetched_at >= ?
               GROUP BY source, source_type
               ORDER BY n DESC""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]


# ============== HTTP ==============
def safe_get(url, headers=None, timeout=15, retries=2):
    """带重试的 GET"""
    import requests
    default_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    if headers:
        default_headers.update(headers)
    for i in range(retries):
        try:
            r = requests.get(url, headers=default_headers, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            if i == retries - 1:
                print(f"⚠️ GET {url} failed: {e}")
                return None
            time.sleep(1)


# ============== 测试 ==============
if __name__ == "__main__":
    init_db()
    print("Schema ready. Tables:")
    with get_db() as conn:
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            print(f"  - {r['name']}")
