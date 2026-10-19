# trytobehackers

## A股 ETF 多因子研究 Agent

可运行的 Python 量化研究个人项目，包含 6 个候选因子、7 个候选策略、训练/验证/独立测试、双边交易费用、成交账本和中文研究报告。

- [项目说明与代码](quant/etf-factor-agent/README.md)
- [下载 0.1.0 研究演示版](https://github.com/CiciShi-srq/trytobehackers/releases/tag/etf-agent-v0.1.0)
- [更新记录](quant/etf-factor-agent/CHANGELOG.md)
- [项目经历与答辩](quant/etf-factor-agent/项目经历与答辩.md)

```bash
cd quant/etf-factor-agent
python agent.py demo --out results/demo
python -m unittest discover -s tests -v
```

打开 `results/demo/report.html` 查看报告。Release ZIP 附带生成好的演示报告，无需运行代码即可查看。

**当前版本为合成行情研究演示，收益不代表真实市场业绩。未连接大模型、券商或实时模拟账户。** 真实 ETF 行情适配器尚未在线验证。

仓库原有网页入口仍为 `index.html`。
