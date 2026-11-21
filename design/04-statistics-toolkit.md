# 04. 统计学工具库设计 (`src/quant_research_lab/stats/`)

## 1. 设计定位
本模块是全项目的**实证裁判与防过拟合防线**。AI 搜罗并复现的所有策略、因子或宏观模型, 都必须通过这里统一口径的统计学检验, 禁止各自临时手写不一致的指标计算。

---

## 2. 模块划分与核心工具清单 (草案)

### 2.1 横截面与因子检验 (`stats/factor.py`)
- **横截面预处理**：去极值 (MAD / Winsorization)、横截面标准化 (Z-Score / Rank)、行业与市值中性化 (WLS / OLS 残差)。
- **IC / RankIC 分析**：逐期 Spearman RankIC、IC 均值、ICIR、Newey-West 调整后的 t 统计量、IC 衰减曲线 (滞后 1~20 期)。
- **分组单调性与多空检验**：等权 / 市值加权分位数分组收益、单调性检验 (Patton-Timmermann MR 检验)、Fama-MacBeth 两步回归 (带 Newey-West 异方差自相关稳健标准误)。

### 2.2 时间序列、协整与状态建模 (`stats/timeseries.py`)
- **平稳性与单位根检验**：ADF、KPSS、PP 检验。
- **协整与均值回归 (服务 Stat Arb)**：Engle-Granger 两步法、Johansen 协整检验、OU 过程参数估计与半衰期 (Half-Life)计算、Hurst 指数。
- **波动率与相关性**：已实现波动率、EWMA、Ledoit-Wolf 协方差收缩、滚动主成分分析 (PCA)。
- **体制与结构断点**：CUSUM / Bai-Perron 结构断点检验、HMM 基础封装 (服务宏观体制研究)。

### 2.3 业绩评估与防过拟合审计 (`stats/validation.py`)⭐ 核心把关模块
- **稳健绩效指标**：年化收益、年化波动、Sharpe (含 Lo 自相关调整)、Sortino、Calmar、最大回撤及水下持续时间、换手率与盈亏平衡交易成本 (Break-even Cost)。
- **多重检验与数据窥探校正**：
  - **Deflated Sharpe Ratio (DSR)** & **Probabilistic Sharpe Ratio (PSR)** (Bailey & López de Prado)
  - **Benjamini-Hochberg (FDR)** / **Bonferroni** / **Holm** p 值校正 (防止搜罗 100 个因子挑出 5 个假阳性)
  - **White's Reality Check / Stationary Bootstrap** (块自助法检验超额收益是否来自运气)
- **防泄漏交叉验证**：
  - **Walk-Forward (滚动样本外)** 与 **Purged & Embargoed K-Fold CV** (严格隔离标签重叠期, 防止时间序列信息泄漏)。

### 2.4 事件研究工具 (`stats/event_study.py`)
- 专为 S&P 500 纳入/剔除、财报、极端冲击设计：
  - 正常收益基准模型 (市场模型 / 市场调整模型)
  - 异常收益 (AR)、累计异常收益 (CAR)、买入持有异常收益 (BHAR)
  - 横截面稳健显著性检验 (Boehmer-Musumeci-Poulsen / BMP 检验, 处理事件窗口期方差膨胀问题)。

---

## 3. 设计约束 (供把关确认)
1. **纯函数与统一输入契约**：所有统计函数只接受标准化的 DataFrame / Series / NumPy 数组 (对齐 `02-data-architecture` 契约), 不直接耦合 DuckDB 连接。
2. **显式输出置信区间与样本量**：禁止只返回一个孤立的 Sharpe 或 p 值; 所有检验函数统一返回结构化结果对象 (含估计值、标准误、p 值、样本量、假设警告)。
3. **单元测试兜底**：每个统计函数都用已知解析解或合成数据写单元测试, 确保数学实现零 Bug。
