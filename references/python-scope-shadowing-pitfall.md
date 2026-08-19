># Python 3.9 局部作用域 shadowing 坑 (v1.7.15, 2026-07-28)

## 症状

```python
import csv  # 模块顶部 import

def fetch_indicators():
    global safe_get  # 改函数全局变量
    safe_get = _safe_get
    # ...
    reader = csv.DictReader(...)  # ❌ UnboundLocalError: local variable 'csv' referenced before assignment
```

## 根因

`global safe_get` 改函数局部 `safe_get` 时, Python 把**整个函数**里**所有出现的** `safe_get` 和 `csv` 都视为**函数局部** (`LOCAL`).

**`import csv`** 在**模块顶层** = 全局, 但函数内 `csv.DictReader()` 时:
- Python 见 `csv` 在**函数内**没赋值 → 报 "unbound"
- 错误信息 "local variable 'csv' referenced before assignment" **误导** (csv 不是函数赋值, 是 shadowing)

## 修复

**方案 1** (推荐): 函数顶部 import
```python
def fetch_indicators():
    import csv
    import io
    # 现在 csv 是函数 local, 函数内用没问题
    reader = csv.DictReader(...)
```

**方案 2**: 模块顶部 + 函数内不用 csv
```python
import csv
import io
def fetch_indicators():
    global safe_get
    safe_get = ...
    # 用 io.StringIO + 手动 parse, 不调 csv
```

**方案 3** (硬核): `nonlocal` 或 `import csv as _csv`
```python
import csv
def fetch():
    global safe_get
    safe_get = ...
    import csv as _csv  # 强制 local 绑定
    _csv.DictReader(...)
```

## 实测触发 (v1.7.15)

`evaluate_today.py:23-32` 原版:
```python
def fetch_indicators():
    indicators = {}
    today = datetime.now(BJT).isoformat(timespec="seconds")
    from _lib import safe_get as _safe_get
    global safe_get
    safe_get = _safe_get  # ← 这行让 Python 把整个函数视为有 local
    # 后面 line 76 的 csv.DictReader 报错
```

**修复**: 把 `import csv; import io` 移到函数顶部.

## 检测工具

```python
import ast
import inspect

def check_function(func):
    """检查函数内是否 module-imported name 被 shadow"""
    src = inspect.getsource(func)
    tree = ast.parse(src)
    assigned = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigned.add(t.id)
    # import csv / from X import Y 在函数外
    # 但函数内有 safe_get = X → Python 把模块 import 也视 local
    return assigned

# 用法
import evaluate_today
problematic = check_function(evaluate_today.fetch_indicators)
print('函数内赋值:', problematic)
# 提示: 'csv', 'io', 'json' 等若在赋值列表, 几乎肯定 shadowing
```

## 同类问题 (Python 3 通用)

```python
# ❌ 函数内有 from X import Y 也不安全
def f():
    from os import path
    json = "string"  # 错! json 视 local
    return json

# ❌ nonlocal 在 nested function 错误顺序
def outer():
    def inner():
        nonlocal x
        x = 1  # 报: nonlocal x not defined yet
    x = 0
    inner()
```

## paVisa 教训

**v1.7.15 实测**: `evaluate_today.py` 加 `global safe_get` 立即触发, 花了 20 分钟调试"local variable 'csv' referenced before assignment" 才定位.

**未来**:
- 加 `global` 前 → AST 静态扫描函数, 列出所有 name 引用
- 若 import 过的 name 在函数内出现 → 函数顶部也 import
- 或 import 写成 `from X import Y as Z` (Z 是 local)
