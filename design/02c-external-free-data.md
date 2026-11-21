# 02c. 现有数据缺口分析与免费权威数据源清单

## 1. 现有 `lab.duckdb` 能力盘点 (已具备、无需重复找)
经过只读核验, 你本地的 `lab.duckdb` 已经覆盖了大量高价值数据：
- ✅ **全市场日频价量** (`prices`, 2011~2026, 含 24,366 个分段 ticker)
- ✅ **主要跨资产与行业 ETF** (已在 `prices` 中：`SPY`, `QQQ`, `GLD`, `TLT`, `IEF`, `SHY`, `HYG`, `LQD`, `XLK`, `XLF`, `XLE` 等全周期 4,000 个交易日)
- ✅ **S&P 500 PIT 历史成分股 + 行业分类** (`universe`, 含 `cik`, `exchange`, `sic`, `sub_industry`)
- ✅ **SEC EDGAR PIT 财报与股本数** (`fundamental_instant` / `fundamental_period`, 含 `filed` 真实申报日, 且包含 `CommonStockSharesOutstanding` / `EntityCommonStockSharesOutstanding`, 可直接推算 PIT 市值)

---

## 2. 缺失数据清单与免费权威数据源 (按优先级排序)

为了完整支撑 **S&P 500 深度量化 + 宏观体制研究 + 严谨统计学审计**, 以下是真正缺失、且有**完全免费、官方权威、适合程序化拉取**的数据源：

### P0：立刻需要补齐 (做严肃实证绕不开的基准)

| 缺失数据 | 用途 | 免费权威数据源 | 获取方式与注意点 |
| :--- | :--- | :--- | :--- |
| **1. 无风险利率 `RF` & 学术因子基准 (FF3 / FF5 / Mom / ST_Rev / LT_Rev)** | 计算超额收益 $r_{i,t} - r_{f,t}$、Sharpe Ratio、**Residual Momentum 残差回归**、策略 Alpha 归因 | **Kenneth French Data Library** (达特茅斯官方, 永久免费) | 官方 ZIP/CSV 直链下载 (日频 & 月频全覆盖); 零反爬、学术界唯一金标准 |
| **2. 隐含波动率与期限结构 (`VIX`, `VIX3M`, `VVIX`, `SKEW`)** | 波动率体制切换、尾部风险预警、Volatility Targeting、VIX 期限结构择时 (`VIX / VIX3M`) | **CBOE 官方历史 CSV** + **FRED (`VIXCLS`)** | CBOE 官网直接提供 `VIX_History.csv` / `VIX3M_History.csv` / `SKEW_History.csv` 直链, 免费无需 Key |
| **3. 经典业界因子对照 (`BAB`, `QMJ`, `TSMOM`, `HML Devil`)** | 检验自研质量/低波/趋势因子是否只是已知公开因子的翻版 | **AQR Data Sets** (官方免费公开) | 官网直接提供定期更新的 Excel/CSV 文件 |

---

### P1：宏观经济模块核心 (解锁 `macro_regime` 与宏观择时)

| 缺失数据 | 核心指标示例 | 免费权威数据源 | 获取方式与注意点 |
| :--- | :--- | :--- | :--- |
| **4. 美国宏观与金融条件全套指标 (带历史修正版本)** | 收益率曲线 (`DGS3MO`, `DGS2`, `DGS10`, `T10Y2Y`)、实际利率 (`DFII10`)、盈亏平衡通胀 (`T10YIE`)、信用利差 (`BAMLH0A0HYM2`, `BAMLC0A0CM`)、金融条件 (`NFCI`, `STLFSI4`)、通胀与就业 (`CPIAUCSL`, `PCEPI`, `UNRATE`, `ICSA`, `INDPRO`) | **FRED & ALFRED** (圣路易斯联储, 完全免费) | 日频市场利率/利差可直接用 FRED CSV 或免费 API Key; **月频/季频宏观公布值 (CPI/GDP/非农)务必走 ALFRED 拉取真实 `vintage/release_date`**, 杜绝宏观前视偏差！ |
| **5. 政策与地缘风险指数 (`EPU`, `GPR`)** | 美国每日/每月经济政策不确定性指数 (Baker-Bloom-Davis)、地缘政治风险指数 (Caldara-Iacoviello) | **policyuncertainty.com** & **matteoiacoviello.com/gpr.htm** | 学者官网永久免费直下 CSV/Excel, 回溯至 1985 年, 非常适合做宏观避险过滤器 |
| **6. NBER 经济衰退官方区间 & FOMC 议息日程** | 衰退期标注 (用于宏观体制回测对照)、FOMC 公告日 (用于 Pre-FOMC Drift 事件研究) | **FRED (`USREC`)** + **美联储官网 FOMC Calendar** | 完全免费公开, 体量极小 (几十到几百行) |

---

### P2：进阶事件驱动与另类信号 (后续按需扩展, 不急于 v1.0)

| 缺失数据 | 用途 | 免费权威数据源 | 获取方式与注意点 |
| :--- | :--- | :--- | :--- |
| **7. S&P 500 纳入/剔除公告日 (Announcement Date)** | 目前 `universe` 记录的是生效日; 补上公告日可完整研究“公告日→生效日”抢跑效应与生效后反转 | S&P Dow Jones Indices Press Releases / Wikipedia 变更历史整理 | 几百条记录, 一次整理好即可锁版本 |
| **8. SEC 内部人交易 (Form 4)与重大事件 (8-K)日期** | 内部人集群买入异象、重大事件后漂移, 且可直接通过 `cik` 关联你现有的 `universe` | **SEC EDGAR 官方免费 Bulk Data / JSON API** | 完全免费 (仅需在 HTTP Header 带 `User-Agent: Name Email` 遵守 10 req/s 限速) |
| **9. 期货持仓情绪 (COT 报告)** | S&P 500 期货 (E-mini)机构 vs 投机者净多头拥挤度 | **CFTC 官方免费历史压缩包** | 周频发布, 官网直链免费下载 |

---

## 3. 建议的入库版本规划 (保持 `v1.0.0` 纯净)
- **`v1.0.0` (当前)**：先只把现有 `lab.duckdb` 里的 7 张核心基表推上 Hugging Face 锁死, **不要等外部数据补齐再发版**。
- **`v1.1.0` (P0 补齐)**：新增 `ff_factors_daily` (Ken French 日频因子 + `RF`)与 `vol_indices_daily` (CBOE `VIX/VIX3M/SKEW`)两张小表——体量总共不到 5MB, 却能立刻解锁超额收益、残差动量、Alpha 归因和波动率体制研究。
- **`v1.2.0` (P1 宏观包)**：新增 `macro_series` (严格带 `obs_date` 与 `release_date` 的长表), 统一收纳 FRED/ALFRED、EPU、GPR、FOMC 日程。
