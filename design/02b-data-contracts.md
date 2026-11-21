# 02b. 函数边界与内存数据格式契约 (In-Memory Data Contracts)

## 1. 设计目标
项目由 AI 驱动编写研究、因子、统计检验与回测代码。为了防止不同模块之间出现“列名不统一、索引乱序、时区混用、隐式前视偏差 (Look-ahead Bias)”等致命问题, **所有模块函数之间的输入/输出必须严格遵守以下 6 种标准内存数据格式**, 并通过运行时校验器强拦截。

---

## 2. 六大标准数据对象契约

### 2.1 `PanelFrame` (核心面板数据 — 原始数据与多特征标准入口)
用于：`prices` 原始行情、Point-in-Time 基本面宽表、多因子特征矩阵。

- **类型**：`pandas.DataFrame`
- **索引 (强制)**：`pd.MultiIndex`, 严格两级：
  - Level 0：`name="date"`, dtype=`datetime64[ns]`, **无时区 (tz-naive)**, 代表美股交易日。
  - Level 1：`name="ticker"`, dtype=`string` (或 `object/str`), 对应 `lab.duckdb` 中的分段 `ticker`。
- **结构约束**：
  - 必须满足 `df.index.is_monotonic_increasing == True` (按 `(date, ticker)` 升序排列); 
  - 必须满足 `df.index.has_duplicates == False` (严禁重复 `(date, ticker)`); 
  - 数值列统一 `float64` (`volume` 允许 `int64` 或 `float64`), 禁止混入字符串或 `inf/-inf`。
- **标准列命名约定**：
  - 原始价量入口函数必须且只能接受以下标准列子集：`open`, `high`, `low`, `close`, `adj_close`, `volume` (按需声明 `required_cols`)。

### 2.2 `SignalSeries` (单信号 / 单因子输出)
用于：所有因子构造、模型预测、残差 Alpha 函数的标准输出。

- **类型**：`pandas.Series` (或单列 `PanelFrame`)
- **索引 (强制)**：与 `PanelFrame` 完全一致的 `MultiIndex(names=["date", "ticker"])`, 已排序、无重复。
- **值类型**：`float64`, 允许 `NaN` (代表该日无信号/停牌/样本不足), 严禁 `±inf`。
- **时间戳语义契约 (防前视偏差铁律)**：
  - 索引日期 `date = t` 的信号值, **必须只使用 `t` 日收盘及之前公开可得的信息**; 
  - 该信号默认用于预测 `t -> t+1` (或 `t -> t+h`)的未来收益, **禁止**在信号函数内部提前 `shift(-1)`。

### 2.3 `WeightFrame` (组合目标权重)
用于：组合构建器输出 → 回测引擎 / 换手率与成本分析输入。

- **类型**：`pandas.Series` (`MultiIndex(date, ticker)`, 值 `float64`)**或** 宽表 `pandas.DataFrame` (`DatetimeIndex(name="date")` × `columns=ticker`)。
  - **推荐默认使用 `MultiIndex(date, ticker)` 的 `Series`** (与 `PanelFrame` 统一, 且对 500 成分股动态进出更稀疏省内存; 仅在协方差矩阵乘法等线性代数步骤内部临时 `.unstack()`)。
- **语义与约束**：
  - `date = t` 处的权重代表在 `t` 日收盘 (或 `t+1` 日开盘, 由执行口径参数显式声明)建立的持仓权重; 
  - 可选校验：非零权重标的必须属于当日 `universe` (防幸存者偏差)、单票权重上限、总杠杆 `sum(|w|)` 与净敞口 `sum(w)` 边界。

### 2.4 `TimeSeriesFrame` (市场 / 组合 / 宏观时间序列)
用于：组合日收益与净值、基准 (`SPY` / `VIX`)、Fama-French 因子、市场广度、宏观经济指标与体制概率。

- **类型**：`pandas.DataFrame` 或 `pandas.Series`
- **索引 (强制)**：`pd.DatetimeIndex(name="date")`, tz-naive, 严格升序, 无重复。
- **宏观数据对齐铁律**：
  - 宏观指标进入模型前, 必须先经过 `align_macro_to_calendar(macro_raw, calendar)`, 严格按 **`release_date` (真实发布日)** 向前填充 (`ffill`)到交易日历 `calendar`, 绝不允许用 `obs_date` (观测期)直接对齐。

### 2.5 `EventTable` (事件研究标准表)
用于：S&P 500 纳入/剔除、财报日、极端回撤冲击、FOMC 会议等事件研究。

- **类型**：`pandas.DataFrame` (默认 `RangeIndex`)
- **必含列**：
  - `event_id` (`str` / `int`, 唯一)
  - `event_date` (`datetime64[ns]`, tz-naive, 映射到首个可交易日)
  - `ticker` (`str`, 宏观事件可为 `"SPY"` 或 `None`)
  - `event_type` (`str`, 如 `"sp500_add"`, `"sp500_drop"`, `"earnings"`)

### 2.6 `StatResult` (统计学工具库统一返回契约)
用于：`stats/` 下所有检验函数的标准返回, 拒绝只返回一个裸浮点数。

```python
@dataclass(frozen=True)
class StatResult:
    name: str                      # 检验/指标名称, 如 "Fama-MacBeth t-stat"
    estimate: float                # 点估计值
    se: float | None = None        # 标准误
    t_stat: float | None = None    # t 统计量
    p_value: float | None = None   # p 值
    ci_low: float | None = None    # 置信区间下界
    ci_high: float | None = None   # 置信区间上界
    n_obs: int = 0                 # 有效样本量
    meta: dict[str, Any] = field(default_factory=dict)  # 附加诊断信息
    warnings: tuple[str, ...] = () # 假设违背或样本不足警告
```

---

## 3. DuckDB → `PanelFrame` 标准入口约定

所有从 `lab.duckdb` 加载行情或基本面的读取器 (`src/quant_research_lab/data/loader.py`), **统一返回标准 `PanelFrame`**, 避免各处手写 `.set_index()` 导致口径漂移：

```python
# 示例接口签名 (动工后实现)
def load_prices(
    start_date: str | None = None,
    end_date: str | None = None,
    sp500_only: bool = True,      # 默认按 PIT universe 过滤, 避免全市场 2.4 万只股票爆内存
    columns: Sequence[str] = ("open", "high", "low", "close", "adj_close", "volume"),
) -> pd.DataFrame:                 # 保证返回 MultiIndex(date, ticker) 的 PanelFrame
    ...
```

---

## 4. 运行时契约校验机制 (防 AI 写坏数据流)

动工后提供轻量校验模块 `src/quant_research_lab/data/contracts.py`：
- `validate_panel(df, required_cols=..., allow_na=True, allow_inf=False)`
- `validate_signal(s)`
- `validate_timeseries(df, required_cols=...)`
- 装饰器 `@require_panel(arg="prices", required_cols=("close", "adj_close"))`, 直接挂在因子函数、统计函数与回测函数入口上; 一旦格式不合规范立刻抛出 `DataContractError` 并指出具体违规项 (例如索引未排序、level 名写反、含 `inf`、存在重复键)。
