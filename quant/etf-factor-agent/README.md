# ETF 多因子研究 Agent

[下载 0.1.0 研究演示版](https://github.com/CiciShi-srq/trytobehackers/releases/tag/etf-agent-v0.1.0) · [更新记录](CHANGELOG.md)

面向大二学生的可复现量化研究个人项目：数据审计 → 因子计算 → 训练期定方向 → 验证期选策略 → 模型冻结 → 独立测试 → 历史交易回放 → 研究报告。

这是**规则驱动、工具编排型 Research Agent**，不是接入大模型的自主交易机器人。核心完全使用 Python 标准库，无 API Key。策略是否盈利需另做真实行情验证。

## 立即查看

Release ZIP 内已生成 `results/demo/report.html`，双击打开即可查看。演示包含 **12 个虚拟标的、1,000 个合成工作日、6 个候选因子、7 个候选策略**。项目包含 15 项自动化测试；发布流程先运行测试、重新生成演示并校验 ZIP，再上传版本文件。源码仓库不跟踪生成结果，需要先运行 demo 命令。

全部演示标的使用 `DEMO_*` 编码，不冒充真实 ETF；日历只是周一到周五，**不是 A 股交易日历**。演示收益来自合成价格，不用于证明投资能力。

## 运行

安装 Python 3.10 或以上，Windows 双击 `run_demo.bat` 即可重新生成报告。也可在本项目目录执行：

```powershell
python agent.py demo --out results/demo
python -m unittest discover -s tests -v
```

核心无需 `pip install`。运行配置位于 `config.json`。`demo` 固定使用默认配置保证复现；使用自定义参数请对生成的 CSV 执行 `research --config`。

查看软件版本：`python agent.py --version`。源码用户可在生成演示后执行 `python scripts/package_release.py --out dist`，生成包含源码、中文报告、示例账本的发布 ZIP 及 `SHA256SUMS`。只打包明确列出的源码和合成演示，不包含用户真实行情或其他研究输出。

## 接入 A 股 ETF 真实历史行情

可选适配器依照 [AKShare 官方 ETF 历史行情文档](https://akshare.akfamily.xyz/data/fund/fund_public.html) 编写，使用 `fund_etf_hist_em` 的 `hfq` 后复权数据。下载入口已做离线字段映射测试；**本次交付没有安装 AKShare、没有联网下载或验证行情端点**，供应商变化、限流或依赖问题可能导致失败。

```powershell
python -m pip install -r requirements-data.txt
python scripts/fetch_etf.py --start 20200101 --end 20251231 --out data/etf_history.csv
python agent.py research --data data/etf_history.csv --out results/real
```

默认 10 只固定 ETF 只用于教学覆盖宽基和行业，不代表推荐：`510050,510300,510500,159915,159928,512010,512660,512880,512800,512690`。这不是历史动态投资池，存在存续与事后选择偏差。

可通过 `--symbols` 指定其他代码。下载器遇到空结果、字段变化、不完整日期或零成交量会报错，不会自动填补，也不会悄悄切换成合成数据。不要为得到漂亮结果而筛除不利日期。

真实数据采用统一后复权开盘/收盘价格，因此账户单位是**复权财富指数的可分割研究单位**。账本里的 `research_units` 不等于可下单 ETF 份额，`reference_open` 不等于真实成交价。分红影响由数据供应商复权口径承担，不能再重复加计现金分红。需先抽查分红日前后数据，再解释回测。

## 自带 CSV 的要求

```csv
date,symbol,open,close,volume
2023-01-03,510300,3.90,3.92,1000000
```

例子仅说明格式。实际需至少 300 个共同日期和 6 个标的；所有标的日期一致；价格与成交量为正；开盘、收盘必须同一复权口径。禁止重复 `(date,symbol)`。模型不做隐式补值；停牌与上市日期缺口需要明确的数据政策。

同名元数据文件必需，例如 `data/etf_history.meta.json`：

```json
{
  "source": "你的数据供应商与下载日期",
  "synthetic": false,
  "price_basis": "统一后复权价格，已检查分红口径"
}
```

也可用 `--meta` 指向其他 JSON。元数据属于来源记录，不能代替独立行情校验。

## 策略与检验口径

| 项目 | 实现 |
| --- | --- |
| 因子 | 20/60 日动量、5 日反转、20 日低波、20 日量能异常、60 日均线偏离 |
| 横截面处理 | 排名；相同值取平均名次；组合用等权有向排名 |
| 样本切分 | 60 日预热后，约 50% 训练 / 25% 验证 / 25% 独立测试 |
| 预测标签 | t 日收盘信号，t+1 开盘至 t+6 开盘的 5 区间收益 |
| 标签隔离 | 每段末尾 6 行不参与 IC 标签；每 5 个交易日取一次非重叠标签 |
| 方向选择 | 仅训练集原始 Rank IC 均值决定正负号 |
| 候选策略 | 6 个单因子，加训练集绝对 IC 前 3 因子等权组合，共 7 个 |
| 模型选择 | 验证集含成本 Sharpe 最大；收益再用于打破平局；测试前冻结 |
| 持仓 | 每 5 个交易日调仓、选前 3 只等权；初始虚拟资金 10 万，无融资和卖空 |
| 权重上限 | 默认在调仓时每只 1/3；期间价格漂移可使权重暂时超过该值 |
| 时间 | t-1 日收盘计算信号，t 日开盘交易，t+1 开盘计价 |
| 费用 | 假设单边手续费 3 bps、滑点 5 bps；买卖都扣；计入期末平仓 |
| 基准 | 同池等权，和策略使用相同时间、费用、调仓和平仓规则 |
| 年化指标 | 252 交易日；Sharpe 无风险利率设为 0；短窗口结果需谨慎解释 |

策略每个验证/测试片段独立从现金开始，入场和平仓均收费用。费用按成交金额计算，求解扣费后的目标资产净值；调仓间持有研究单位，权重自然漂移。滑点作为额外现金成本扣除，未修改参考开盘价，避免双重计费。

策略可能在验证、测试期均亏损；代码仍如实输出。方向筛选和验证集挑选不是有效性证明。当前没有横截面行业中性化、统计显著性校正、滚动 walk-forward 或不同市场状态稳健性验证。

## 冻结模型生成后续目标

```powershell
python agent.py pending --data data/etf_history.csv --model results/real/model.json --out results/real/pending_orders.csv
```

该命令不重新训练，只用最新收盘及过去行情算出目标权重，状态为 `UNFILLED_RESEARCH_TARGET`。它是“下次**若到调仓日**的目标”，不是成交订单、实时模拟账户或自动调仓计划；需补充未来开盘和持仓状态才可能成交。示例回放末尾已平仓，待执行目标与历史平仓分开记录。

## 结果文件

| 文件 | 用途 |
| --- | --- |
| `report.html` | 中文报告、测试期策略/基准曲线、因子审计、研究边界 |
| `model.json` | 冻结因子、方向、日期、参数、标的池、原数据 SHA256 |
| `summary.json` | 完整切分、候选验证结果、测试与基准指标 |
| `agent_log.json` | 各阶段决策与审计记录 |
| `factor_audit.csv` | 训练、验证、测试的原始方向 Rank IC |
| `trades.csv` | 买卖方向、参考开盘、研究单位、金额、手续费、滑点 |
| `equity.csv` | 策略每日净值、现金、收益、回撤 |
| `benchmark_equity.csv` | 同池等权基准净值 |
| `pending_orders.csv` | 最新收盘后未成交的研究目标 |

## 研究边界与后续方向

本版完成可审计的研究原型。它尚未实现券商接入、实时行情、真实 ETF 手数/T+1 约束、停牌/涨跌停排队、最低佣金、流动性约束、分红份额会计或订单拒绝。固定 ETF 池还存在选择偏差。不要把复权研究单位账本直接接到券商。

建议先验证真实数据与样本外稳定性，再加滚动训练、交易约束、持久化模拟账户；如需大模型，可让 LLM 提出研究假设和写报告，但计算、日期边界和风险约束仍交给确定性工具执行。

方法参考：[Qlib API：信号移位、开平仓费用与交易单位](https://qlib.readthedocs.io/en/stable/reference/api.html)，[AKShare：ETF 历史数据和复权说明](https://akshare.akfamily.xyz/data/fund/fund_public.html)。本项目未复制上述项目源码。

## 放到 GitHub

本交付已包含 `.gitignore` 和 GitHub Actions 工作流，打包内附带的演示结果可本地查看，默认不跟踪 `results/` 与真实行情 `data/`。

GitHub 项目目录为 `CiciShi-srq/trytobehackers` 的 `quant/etf-factor-agent/`。使用源码时先进入该目录；Release ZIP 解压后可以直接运行。根目录 `.github/workflows/etf-factor-agent.yml` 负责检查，`etf-factor-release.yml` 在主分支版本变更时测试、生成演示、打包并发布。工作流使用 GitHub 自带的临时 `GITHUB_TOKEN`，只在发布 job 授予 `contents: write`，无需填写个人令牌。

简历与面试材料见 `项目经历与答辩.md`。
