# ETF 多因子研究 Agent 0.1.0 · 研究演示版

提供可直接运行的 Python 量化研究项目：6 个固定因子、7 个候选策略，包含训练集方向选择、验证集选模、独立测试、双边交易费用、逐笔账本、净值与中文报告。

下载 `etf-factor-agent-0.1.0.zip` 并解压后，直接打开 `results/demo/report.html` 查看预生成报告。安装 Python 3.10+ 后，双击 `run_demo.bat`，或在目录中执行：

```bash
python agent.py demo --out results/demo
python -m unittest discover -s tests -v
```

核心不需要额外依赖或 API Key。另附 AKShare 数据适配器、简历与答辩材料。`SHA256SUMS` 用于核对 ZIP 完整性。

本版本使用 12 个虚拟标的和 1,000 个合成工作日演示。收益不代表真实市场业绩；真实行情在线端点尚未验证。Agent 为确定性规则流程，未连接 LLM、券商或实时模拟账户。复权研究单位不等于可直接交易的 ETF 份额。

发布工作流会先运行测试并重新生成演示，再创建下载包；任何一步失败都不会创建新版本。代码来自 `quant/etf-factor-agent/`。
