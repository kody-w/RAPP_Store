"""
Data Analyst Agent - Analyze datasets, generate insights, create visualizations

Part of the RAPP Store - https://github.com/kody-w/RAPP_Store
"""

from agents.basic_agent import BasicAgent
import logging


class DataAnalystAgent(BasicAgent):
    """
    Data analysis agent for statistical analysis, trend detection,
    data summarization, and visualization recommendations.
    """

    def __init__(self):
        self.name = 'DataAnalyst'
        self.metadata = {
            "name": self.name,
            "description": "Analyze datasets, generate statistical insights, detect trends, summarize data, and recommend visualizations. Provides code examples for pandas, numpy, and matplotlib.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action: 'describe' (statistical summary), 'analyze' (in-depth analysis), 'trends' (trend detection), 'visualize' (chart recommendations), 'clean' (data cleaning guidance), 'correlate' (correlation analysis)",
                        "enum": ["describe", "analyze", "trends", "visualize", "clean", "correlate"]
                    },
                    "data_description": {
                        "type": "string",
                        "description": "Description of the dataset (columns, types, size)"
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to data file (CSV, Excel, JSON)"
                    },
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific columns to analyze"
                    },
                    "analysis_goal": {
                        "type": "string",
                        "description": "What you want to learn from the data"
                    }
                },
                "required": ["action"]
            }
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        action = kwargs.get('action')

        try:
            if action == 'describe':
                return self._describe_data(kwargs)
            elif action == 'analyze':
                return self._analyze_data(kwargs)
            elif action == 'trends':
                return self._detect_trends(kwargs)
            elif action == 'visualize':
                return self._recommend_visualizations(kwargs)
            elif action == 'clean':
                return self._data_cleaning_guide(kwargs)
            elif action == 'correlate':
                return self._correlation_analysis(kwargs)
            else:
                return f"Error: Unknown action '{action}'"
        except Exception as e:
            logging.error(f"Error in DataAnalyst: {str(e)}")
            return f"Error: {str(e)}"

    def _describe_data(self, params):
        """Generate statistical summary code"""
        file_path = params.get('file_path', 'data.csv')
        columns = params.get('columns', [])

        cols_str = str(columns) if columns else "all columns"

        return f"""📊 Data Description

**File:** {file_path}
**Columns:** {cols_str}

**Code to Generate Statistical Summary:**

```python
import pandas as pd
import numpy as np

# Load data
df = pd.read_csv("{file_path}")

# Basic info
print("Dataset Shape:", df.shape)
print("\\nColumn Types:")
print(df.dtypes)

# Statistical summary
print("\\nStatistical Summary:")
print(df.describe())

# Missing values
print("\\nMissing Values:")
print(df.isnull().sum())

# Unique values per column
print("\\nUnique Values:")
for col in df.columns:
    print(f"  {{col}}: {{df[col].nunique()}} unique values")
```

**For specific columns:**

```python
columns = {columns if columns else "['column1', 'column2']"}
print(df[columns].describe())
```

**Memory usage:**

```python
print(f"Memory usage: {{df.memory_usage(deep=True).sum() / 1024**2:.2f}} MB")
```
"""

    def _analyze_data(self, params):
        """In-depth data analysis"""
        file_path = params.get('file_path', 'data.csv')
        analysis_goal = params.get('analysis_goal', 'general exploration')
        columns = params.get('columns', [])

        return f"""🔬 In-Depth Data Analysis

**File:** {file_path}
**Goal:** {analysis_goal}

**Comprehensive Analysis Code:**

```python
import pandas as pd
import numpy as np
from scipy import stats

# Load and inspect
df = pd.read_csv("{file_path}")

# 1. DISTRIBUTION ANALYSIS
print("=" * 50)
print("DISTRIBUTION ANALYSIS")
print("=" * 50)

for col in df.select_dtypes(include=[np.number]).columns:
    print(f"\\n{{col}}:")
    print(f"  Mean: {{df[col].mean():.2f}}")
    print(f"  Median: {{df[col].median():.2f}}")
    print(f"  Std Dev: {{df[col].std():.2f}}")
    print(f"  Skewness: {{df[col].skew():.2f}}")
    print(f"  Kurtosis: {{df[col].kurtosis():.2f}}")

# 2. CATEGORICAL ANALYSIS
print("\\n" + "=" * 50)
print("CATEGORICAL ANALYSIS")
print("=" * 50)

for col in df.select_dtypes(include=['object', 'category']).columns:
    print(f"\\n{{col}} - Top 5 values:")
    print(df[col].value_counts().head())

# 3. OUTLIER DETECTION
print("\\n" + "=" * 50)
print("OUTLIER DETECTION (IQR Method)")
print("=" * 50)

for col in df.select_dtypes(include=[np.number]).columns:
    Q1 = df[col].quantile(0.25)
    Q3 = df[col].quantile(0.75)
    IQR = Q3 - Q1
    outliers = df[(df[col] < Q1 - 1.5*IQR) | (df[col] > Q3 + 1.5*IQR)]
    print(f"{{col}}: {{len(outliers)}} outliers detected")

# 4. DATE ANALYSIS (if applicable)
date_cols = df.select_dtypes(include=['datetime64']).columns
if len(date_cols) > 0:
    print("\\n" + "=" * 50)
    print("DATE ANALYSIS")
    print("=" * 50)
    for col in date_cols:
        print(f"{{col}}: {{df[col].min()}} to {{df[col].max()}}")
```

**Segment Analysis:**

```python
# Group by analysis
if 'category_column' in df.columns:
    grouped = df.groupby('category_column').agg({{
        'numeric_col': ['mean', 'median', 'std', 'count']
    }})
    print(grouped)
```
"""

    def _detect_trends(self, params):
        """Trend detection analysis"""
        file_path = params.get('file_path', 'data.csv')
        columns = params.get('columns', [])

        return f"""📈 Trend Detection

**File:** {file_path}

**Time Series Trend Analysis:**

```python
import pandas as pd
import numpy as np
from scipy import stats

df = pd.read_csv("{file_path}")

# Ensure datetime index
df['date'] = pd.to_datetime(df['date_column'])
df = df.set_index('date').sort_index()

# 1. MOVING AVERAGES
value_col = 'value_column'  # Replace with your column

df['MA_7'] = df[value_col].rolling(window=7).mean()
df['MA_30'] = df[value_col].rolling(window=30).mean()

print("Moving Averages calculated")

# 2. TREND DIRECTION
def detect_trend(series, window=30):
    '''Detect if trend is up, down, or flat'''
    if len(series) < window:
        return "insufficient data"

    recent = series[-window:].mean()
    previous = series[-2*window:-window].mean() if len(series) >= 2*window else series[:window].mean()

    pct_change = (recent - previous) / previous * 100

    if pct_change > 5:
        return f"UPWARD (+{{pct_change:.1f}}%)"
    elif pct_change < -5:
        return f"DOWNWARD ({{pct_change:.1f}}%)"
    else:
        return f"FLAT ({{pct_change:.1f}}%)"

print(f"Trend: {{detect_trend(df[value_col])}}")

# 3. LINEAR REGRESSION TREND
x = np.arange(len(df))
y = df[value_col].values
slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)

print(f"\\nLinear Trend:")
print(f"  Slope: {{slope:.4f}} (change per period)")
print(f"  R-squared: {{r_value**2:.4f}}")
print(f"  P-value: {{p_value:.4f}}")

# 4. SEASONALITY CHECK
if len(df) >= 365:
    monthly = df[value_col].groupby(df.index.month).mean()
    print(f"\\nMonthly Seasonality:")
    print(monthly)
```

**Growth Rate Analysis:**

```python
# Period-over-period growth
df['pct_change'] = df[value_col].pct_change() * 100
df['yoy_growth'] = df[value_col].pct_change(periods=365) * 100

print("\\nGrowth Metrics:")
print(f"  Average daily change: {{df['pct_change'].mean():.2f}}%")
print(f"  Volatility (std): {{df['pct_change'].std():.2f}}%")
```
"""

    def _recommend_visualizations(self, params):
        """Recommend appropriate visualizations"""
        data_description = params.get('data_description', '')
        analysis_goal = params.get('analysis_goal', '')

        return f"""📊 Visualization Recommendations

**Data:** {data_description if data_description else 'General dataset'}
**Goal:** {analysis_goal if analysis_goal else 'Data exploration'}

**Visualization Code Templates:**

### 1. Distribution Analysis
```python
import matplotlib.pyplot as plt
import seaborn as sns

fig, axes = plt.subplots(2, 2, figsize=(12, 10))

# Histogram
axes[0, 0].hist(df['numeric_col'], bins=30, edgecolor='black')
axes[0, 0].set_title('Distribution')

# Box plot
axes[0, 1].boxplot(df['numeric_col'])
axes[0, 1].set_title('Box Plot')

# KDE plot
sns.kdeplot(data=df, x='numeric_col', ax=axes[1, 0])
axes[1, 0].set_title('Density Plot')

# Q-Q plot
from scipy import stats
stats.probplot(df['numeric_col'], dist="norm", plot=axes[1, 1])
axes[1, 1].set_title('Q-Q Plot')

plt.tight_layout()
plt.savefig('distribution.png', dpi=150)
plt.show()
```

### 2. Time Series
```python
fig, ax = plt.subplots(figsize=(14, 6))

ax.plot(df.index, df['value'], label='Actual', alpha=0.7)
ax.plot(df.index, df['MA_30'], label='30-day MA', linewidth=2)
ax.fill_between(df.index, df['lower_bound'], df['upper_bound'], alpha=0.2)

ax.set_title('Time Series with Moving Average')
ax.legend()
plt.savefig('timeseries.png', dpi=150)
```

### 3. Correlation Heatmap
```python
plt.figure(figsize=(10, 8))
correlation_matrix = df.select_dtypes(include=[np.number]).corr()
sns.heatmap(correlation_matrix, annot=True, cmap='coolwarm', center=0)
plt.title('Correlation Matrix')
plt.tight_layout()
plt.savefig('correlation.png', dpi=150)
```

### 4. Category Comparison
```python
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Bar chart
df.groupby('category')['value'].mean().plot(kind='bar', ax=axes[0])
axes[0].set_title('Average by Category')

# Grouped comparison
df.pivot_table(values='value', index='category', columns='subcategory').plot(kind='bar', ax=axes[1])
axes[1].set_title('Category vs Subcategory')

plt.tight_layout()
plt.savefig('categories.png', dpi=150)
```

### 5. Scatter with Regression
```python
fig, ax = plt.subplots(figsize=(10, 6))
sns.regplot(data=df, x='x_col', y='y_col', ax=ax)
ax.set_title('Scatter Plot with Regression Line')
plt.savefig('scatter.png', dpi=150)
```

**Chart Selection Guide:**

| Data Type | Best Chart |
|-----------|------------|
| Distribution | Histogram, KDE, Box plot |
| Time series | Line chart, Area chart |
| Comparison | Bar chart, Grouped bar |
| Relationship | Scatter, Pair plot |
| Composition | Pie, Stacked bar |
| Correlation | Heatmap, Scatter matrix |
"""

    def _data_cleaning_guide(self, params):
        """Data cleaning guidance"""
        file_path = params.get('file_path', 'data.csv')

        return f"""🧹 Data Cleaning Guide

**File:** {file_path}

**Comprehensive Cleaning Pipeline:**

```python
import pandas as pd
import numpy as np

df = pd.read_csv("{file_path}")
print(f"Original shape: {{df.shape}}")

# 1. HANDLE MISSING VALUES
print("\\n1. Missing Values:")
print(df.isnull().sum())

# Option A: Drop rows with missing values
df_dropped = df.dropna()

# Option B: Fill with statistics
df_filled = df.copy()
for col in df.select_dtypes(include=[np.number]).columns:
    df_filled[col].fillna(df_filled[col].median(), inplace=True)
for col in df.select_dtypes(include=['object']).columns:
    df_filled[col].fillna(df_filled[col].mode()[0], inplace=True)

# Option C: Forward/backward fill (time series)
df_ffill = df.fillna(method='ffill')

# 2. REMOVE DUPLICATES
print(f"\\n2. Duplicates: {{df.duplicated().sum()}}")
df = df.drop_duplicates()

# 3. FIX DATA TYPES
print("\\n3. Data Types:")
# Convert dates
if 'date_column' in df.columns:
    df['date_column'] = pd.to_datetime(df['date_column'], errors='coerce')

# Convert categories
if 'category_column' in df.columns:
    df['category_column'] = df['category_column'].astype('category')

# 4. HANDLE OUTLIERS
print("\\n4. Outlier Treatment:")
for col in df.select_dtypes(include=[np.number]).columns:
    Q1, Q3 = df[col].quantile([0.25, 0.75])
    IQR = Q3 - Q1

    # Option A: Cap outliers
    df[col] = df[col].clip(lower=Q1 - 1.5*IQR, upper=Q3 + 1.5*IQR)

    # Option B: Remove outliers (alternative)
    # df = df[(df[col] >= Q1 - 1.5*IQR) & (df[col] <= Q3 + 1.5*IQR)]

# 5. STANDARDIZE TEXT
print("\\n5. Text Standardization:")
for col in df.select_dtypes(include=['object']).columns:
    df[col] = df[col].str.strip().str.lower()

# 6. VALIDATE DATA
print("\\n6. Validation:")
# Check for negative values where not expected
# Check for future dates
# Check for impossible values

print(f"\\nCleaned shape: {{df.shape}}")
df.to_csv("cleaned_data.csv", index=False)
```
"""

    def _correlation_analysis(self, params):
        """Correlation analysis"""
        file_path = params.get('file_path', 'data.csv')
        columns = params.get('columns', [])

        return f"""🔗 Correlation Analysis

**File:** {file_path}

**Correlation Analysis Code:**

```python
import pandas as pd
import numpy as np
from scipy import stats

df = pd.read_csv("{file_path}")

# 1. PEARSON CORRELATION (linear relationships)
print("PEARSON CORRELATION")
print("=" * 50)
corr_matrix = df.select_dtypes(include=[np.number]).corr(method='pearson')
print(corr_matrix)

# 2. SPEARMAN CORRELATION (monotonic relationships)
print("\\nSPEARMAN CORRELATION")
print("=" * 50)
spearman_corr = df.select_dtypes(include=[np.number]).corr(method='spearman')
print(spearman_corr)

# 3. FIND STRONG CORRELATIONS
print("\\nSTRONG CORRELATIONS (|r| > 0.7):")
for i in range(len(corr_matrix.columns)):
    for j in range(i+1, len(corr_matrix.columns)):
        if abs(corr_matrix.iloc[i, j]) > 0.7:
            print(f"  {{corr_matrix.columns[i]}} <-> {{corr_matrix.columns[j]}}: {{corr_matrix.iloc[i, j]:.3f}}")

# 4. STATISTICAL SIGNIFICANCE
print("\\nSTATISTICAL SIGNIFICANCE:")
cols = df.select_dtypes(include=[np.number]).columns
for i in range(len(cols)):
    for j in range(i+1, len(cols)):
        r, p = stats.pearsonr(df[cols[i]].dropna(), df[cols[j]].dropna())
        if p < 0.05:
            sig = "***" if p < 0.001 else "**" if p < 0.01 else "*"
            print(f"  {{cols[i]}} <-> {{cols[j]}}: r={{r:.3f}}, p={{p:.4f}} {{sig}}")
```

**Interpretation Guide:**

| Correlation | Strength |
|-------------|----------|
| 0.9 - 1.0 | Very strong |
| 0.7 - 0.9 | Strong |
| 0.5 - 0.7 | Moderate |
| 0.3 - 0.5 | Weak |
| 0.0 - 0.3 | Very weak |

⚠️ **Remember:** Correlation ≠ Causation
"""
