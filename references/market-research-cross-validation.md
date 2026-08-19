# Market Research Data Cross-Validation (from archived `market-research-analysis`)

## When This Applies

用户 sends an Excel file + a PPT file and says "对比数据" / "交叉验证" / "比较数据" / "数据一致性".

## Step-by-Step Process

### Step 1: Read Both Files

**Excel:**
```python
import pandas as pd
xl = pd.ExcelFile('filename.xlsx')
print(xl.sheet_names)  # find the right sheet
df = xl.parse('Sheet1')
```

**PPT:**
```python
from pptx import Presentation
prs = Presentation('filename.pptx')
for slide in prs.slides:
    for shape in slide.shapes:
        if hasattr(shape, 'text'):
            print(shape.text)
```

### Step 2: Identify Three口径 Differences FIRST

Before comparing, explicitly identify:
1. **TAM definition**: Life only vs Life+P+C+Health+Re — these are fundamentally different scopes
2. **Time range**: Annual TAM vs 3-year cumulative TAM — not comparable without normalization
3. **Geography**: APAC vs APJ, whether South Korea is in ASEAN — these have different market sizes

### Step 3: Comparison Table

| 维度 | Excel | PPT | 一致性 |
|------|-------|-----|--------|
| TAM定义 | Life only | Life+P+C+Health+Re | ⚠️ 有差异 |
| 时间范围 | 2026年度 | 2028三年累计 | ❌ 不可比 |
| 地理口径 | APAC | APJ | ⚠️ 有差异 |

### Step 4: Root-Cause Analysis

For each ⚠️/❌:
- **TAM定义差异**: Explain which segments are included/excluded in each
- **时间范围差异**: Calculate normalized figures if possible (e.g., 3-year / 3 = annualized)
- **地理口径差异**: Note which countries are in/out for each definition

### Step 5: Verdict

Give 用户 a clear conclusion:
- ✅ **可信**: 数据源一致或差异可解释
- ⚠️ **可并用但需注意**: 部分维度可比，部分需调整
- ❌ **不可比**: 定义差异太大，需重新对齐基准

## 用户's Preferences

- Say "给我对比结果报告" → only conclusion + key差异 explanation, no raw data dumps
- Simple, clear, highlights the important parts
- Do not over-explain — 用户 wants actionable insight, not a methodology lesson