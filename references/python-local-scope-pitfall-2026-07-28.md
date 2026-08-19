# Python 局部作用域坑 (2026-07-28) — 已知 LSP 误报 vs 实际 UnboundLocalError

## 现象
`evaluate_today.py` 顶部有 `import csv`, 函数内用 `csv.DictReader(...)`, 但运行时抛:

```
UnboundLocalError: local variable 'csv' referenced before assignment
```

LSP (Pyright) 同时报:
```
ERROR: "csv" is unbound [reportUndefinedVariable]
ERROR: Cannot access attribute "DictReader" for class "Unbound" [reportAttributeType]
```

## 根因 (Python 3.9+ 行为)

Python 3 看到函数内**任意位置**对 `csv` **赋值** (哪怕 `import csv` 在函数外), 就**把 `csv` 视为函数 local 变量**。**整个函数**内访问 `csv` 都触发 UnboundLocalError 直到该赋值语句执行前。

**触发条件** (任一即可):
1. 函数内 `csv = something` (赋值)
2. 函数内 `import csv` (Python 视 `import x` 为隐式赋值)
3. 函数内有 `for csv in ...` / `with csv.open(...)` 等隐式赋值

**evaluate_today.py 实际触发**: 函数内有:
```python
# 老 evaluate_today.py 第 35-36 行
for line in treasury_data.text.split("\n"):
    ...
    reader = csv.DictReader(...)  # 第一次用 csv
```

但**`from _lib import safe_get` 在函数内** (line 27 `from _lib import safe_get as _safe_get` + `global safe_get; safe_get = _safe_get`) — 触发 Python 3 的 import-as-local 推断, **连带让 `csv` 也被当 local**。

## 修复 (3 选 1)

### 修法 1: import 移进函数内 (推荐)
```python
def fetch_indicators():
    import csv  # 显式在函数内
    import io
    ...
    reader = csv.DictReader(io.StringIO(treasury_data.text))  # OK
```
**优点**: Python 立刻将 `csv` 识别为 local, 不会触发推断
**缺点**: 函数每次调用都 import (但 Python 缓存, 实际 0 成本)

### 修法 2: 顶层 import 改用 import as
```python
# 顶层
import csv as _csv
# 函数内
reader = _csv.DictReader(...)  # 用别名
```
**优点**: 顶层 import 不会被推断
**缺点**: 改所有 csv. 引用, 工程量大

### 修法 3: 删除所有"触发推断"的赋值
```python
# 不要在函数内:
import csv              # ❌ 触发
csv = something        # ❌ 触发
for csv in iterable    # ❌ 触发
with csv.open(...)      # ❌ 触发

# 改为:
import csv              # ✅ 顶层一次性
reader = csv.DictReader()  # 函数内只用不写
```
**优点**: 最干净
**缺点**: 复杂代码难改全

## 经验法则 (防类似坑)

1. **函数内 import = local 推断** (Python 3 行为)
2. **模块顶层 import + 函数内赋值 = local 推断**
3. **LSP 报 "unbound" 但代码看着对 → 99% 是这个坑**
4. **快速诊断**:
   ```python
   def test():
       print(csv)  # UnboundLocalError
       import csv  # ← 这行让 print 之前就 local
   ```
5. **修复优先级**: 修法 1 > 修法 2 > 修法 3

## evaluate_today.py 实际修复 (2026-07-28)

```python
# 修复前 (line 23):
def fetch_indicators():
    indicators = {}
    today = datetime.now(BJT).isoformat(...)
    from _lib import safe_get as _safe_get
    global safe_get
    safe_get = _safe_get
    ...

# 修复后:
def fetch_indicators():
    import csv  # ← 新增
    import io  # ← 新增
    indicators = {}
    today = datetime.now(BJT).isoformat(...)
    from _lib import safe_get as _safe_get
    global safe_get
    safe_get = _safe_get
    ...
```

修后跑通, 0 报错。

## 相关坑 (类似)

| 坑 | 触发 | 修复 |
|---|---|---|
| `import csv` 在函数内 | UnboundLocalError | 顶层 import |
| `from xxx import yyy` 函数内 | UnboundLocalError (y 是 local) | 顶层 import |
| `for i in range()` 函数内 (i 是 local) | 后续 `i` 用法失效 | rename 或 `nonlocal` |
| `def foo(): x = 1` (没 global) | 后续 `x` 是 local | `global x` |

## PaVisa 教训

- ❌ **LSP 报 "unbound" 第一反应**: "导入路径错了" 或 "模块没装" — 错的
- ✅ **真正原因**: 80% 是 Python 局部作用域推断
- **调试顺序**: UnboundLocalError → 看函数内是否有 `=` / `import` / `for` → 移到顶层

**触发这个坑的具体动作**: 修 6 个新数据源时, 给 evaluate_today.py 加 `from _lib import safe_get` 强制 re-import (LSP 警告 "偶发"), 但副作用把 `csv` 推断为 local → 整个 Treasury 解析块 fail。

**实际影响**: Treasury CSV parse 走 except, 跳过 → **8 条 rule 的 `us10y` 永远是硬编码 fallback**。因为 patch 没动, 真实 Treasury 数据从未被 use。

## 相关 SKILL 关联

- `pavisa-evolver` - 评估 SKILL body 是否一致
- `incremental-implementation` - 增量改 vs 一次性大改
- 整个 v1.7.14 升级报告见 `v1.7.14-upgrade-report.md`
