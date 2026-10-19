"""Offline, deterministic ETF factor research agent. Python 3.10+, stdlib only.

Prices must be on one consistent adjusted wealth-index basis. Simulated units
are research units, not exchange-traded shares. No broker or LLM is connected.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import random
import statistics as st
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

FACTORS = ("momentum_20", "momentum_60", "reversal_5", "low_vol_20",
           "volume_surprise_20", "trend_60")
FACTOR_NOTES = {
    "momentum_20": "close[t] / close[t-20] - 1",
    "momentum_60": "close[t] / close[t-60] - 1",
    "reversal_5": "-(close[t] / close[t-5] - 1)",
    "low_vol_20": "-stdev(last 20 close-to-close returns)",
    "volume_surprise_20": "volume[t] / mean(volume[t-20:t]) - 1",
    "trend_60": "close[t] / mean(close[t-59:t+1]) - 1",
}


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2,
                                   allow_nan=False), encoding="utf-8")


def write_csv(path, rows, fields=None):
    rows = list(rows)
    fields = fields or list(rows[0])
    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


@dataclass(frozen=True)
class Config:
    initial_cash: float = 100000.0
    top_k: int = 3
    rebalance: int = 5
    fee_bps: float = 3.0
    slippage_bps: float = 5.0
    warmup: int = 60
    horizon: int = 5
    seed: int = 42

    def validate(self):
        if self.warmup < 60 or self.horizon < 1:
            raise ValueError("warmup >=60 and horizon >=1 required")
        if self.initial_cash <= 0 or self.top_k < 3 or self.rebalance < 1:
            raise ValueError("initial_cash must be >0; top_k >=3; rebalance >=1")
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise ValueError("Costs must be nonnegative")
        if (self.fee_bps + self.slippage_bps) / 10000 >= .1:
            raise ValueError("Costs must be below 10% per side")


class Panel:
    def __init__(self, dates, symbols, opens, closes, volumes):
        self.dates, self.symbols = dates, symbols
        self.opens, self.closes, self.volumes = opens, closes, volumes

    @classmethod
    def load(cls, path):
        by_date, symbols, seen = {}, set(), set()
        with Path(path).open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not {"date", "symbol", "open", "close", "volume"} <= set(reader.fieldnames or []):
                raise ValueError("CSV requires date,symbol,open,close,volume")
            for row in reader:
                day = date.fromisoformat(row["date"]).isoformat()
                symbol = row["symbol"].strip()
                key = (day, symbol)
                if not symbol or key in seen:
                    raise ValueError(f"Empty symbol or duplicate date/symbol: {key}")
                seen.add(key)
                values = [float(row[k]) for k in ("open", "close", "volume")]
                if any(not math.isfinite(v) or v <= 0 for v in values):
                    raise ValueError(f"Nonpositive/nonfinite input (including zero-volume): {key}")
                by_date.setdefault(day, {})[symbol] = values
                symbols.add(symbol)
        dates, symbols = sorted(by_date), sorted(symbols)
        if len(dates) < 300 or len(symbols) < 6:
            raise ValueError("Need >=300 dates and >=6 symbols for this teaching workflow")
        # Never silently forward-fill suspension/missing quotes or select intersection dates.
        for d in dates:
            if set(by_date[d]) != set(symbols):
                raise ValueError(f"Unbalanced panel on {d}; resolve listing/suspension gaps explicitly")
        arrays = [[[by_date[d][s][k] for s in symbols] for d in dates] for k in range(3)]
        return cls(dates, symbols, *arrays)


def make_demo(path, seed=42, days=1000):
    """Synthetic prices, including synthetic weekday calendar. No real ETF codes."""
    rng = random.Random(seed)
    day, closes, rows = date(2021, 1, 4), [2 + j * .25 for j in range(12)], []
    persistent = [0.0] * 12
    for t in range(days):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        market = rng.gauss(.00015, .007)
        for j, prev in enumerate(closes):
            persistent[j] = .94 * persistent[j] + rng.gauss(0, .0004)
            overnight = rng.gauss(0, .002)
            op = prev * math.exp(overnight)
            cl = op * math.exp(market + persistent[j] + rng.gauss(.0001, .008))
            closes[j] = cl
            rows.append(dict(date=day.isoformat(), symbol=f"DEMO_{j+1:02d}",
                             open=round(op, 8), close=round(cl, 8),
                             volume=int(1e6 * math.exp(rng.gauss(0, .3)))))
        day += timedelta(days=1)
    write_csv(path, rows)
    dump(Path(path).with_suffix(".meta.json"), {
        "source": "synthetic_demo", "synthetic": True, "seed": seed,
        "price_basis": "synthetic wealth-index units", "calendar": "weekdays; NOT exchange calendar",
        "warning": "合成行情仅验证代码流程，所有收益均非真实市场业绩。"})


def ranks(values):
    result = [0.0] * len(values)
    idx = sorted(range(len(values)), key=lambda i: values[i])
    a = 0
    while a < len(idx):
        b = a + 1
        while b < len(idx) and values[idx[b]] == values[idx[a]]:
            b += 1
        rank = (a + b - 1) / 2
        for i in idx[a:b]:
            result[i] = rank
        a = b
    return result


def correlation(a, b):
    ma, mb = st.mean(a), st.mean(b)
    va, vb = sum((x-ma)**2 for x in a), sum((x-mb)**2 for x in b)
    if va == 0 or vb == 0:
        return 0.0
    return sum((x-ma)*(y-mb) for x, y in zip(a, b)) / math.sqrt(va*vb)


def factor_at(panel, t):
    if t < 60:
        raise ValueError("60 observations of warmup required")
    result = {f: [] for f in FACTORS}
    for j in range(len(panel.symbols)):
        closes = [r[j] for r in panel.closes[t-60:t+1]]
        rets = [closes[k]/closes[k-1]-1 for k in range(41, 61)]
        vols = [r[j] for r in panel.volumes[t-20:t]]
        values = (closes[-1]/closes[-21]-1, closes[-1]/closes[0]-1,
                  -(closes[-1]/closes[-6]-1), -st.stdev(rets),
                  panel.volumes[t][j]/st.mean(vols)-1,
                  closes[-1]/st.mean(closes[1:])-1)
        for name, value in zip(FACTORS, values):
            result[name].append(value)
    return result


def all_factors(panel):
    return {t: factor_at(panel, t) for t in range(60, len(panel.dates))}


def ic_summary(panel, features, name, start, end, horizon=5):
    # Label uses next open -> open five trading intervals later. Entire label
    # must end BEFORE partition boundary; last six rows are thus purged.
    vals = []
    for t in range(start, end-horizon-1, horizon):
        future = [b/a-1 for a, b in zip(panel.opens[t+1], panel.opens[t+1+horizon])]
        vals.append(correlation(ranks(features[t][name]), ranks(future)))
    mean = st.mean(vals) if vals else 0.0
    sd = st.stdev(vals) if len(vals) > 1 else 0.0
    return {"mean_rank_ic": mean, "ic_ir": mean/sd if sd else None,
            "nonoverlap_samples": len(vals), "positive_fraction":
            sum(x > 0 for x in vals)/len(vals) if vals else 0.0}


def target_at(features, t, factors, signs, k, n):
    score = [0.0] * n
    for f in factors:
        rank = ranks(features[t][f])
        for j in range(n):
            score[j] += signs[f] * (rank[j] / (n-1) - .5) / len(factors)
    chosen = sorted(range(n), key=lambda j: (-score[j], j))[:k]
    weights = [1/k if j in chosen else 0.0 for j in range(n)]
    return weights, score


def rebalance_account(cash, units, prices, targets, cfg, symbols, day, signal_day):
    """Solve post-fee target NAV; conserve cash including both-side costs."""
    before = cash + sum(q*p for q, p in zip(units, prices))
    current = [q*p for q, p in zip(units, prices)]
    cost_rate = (cfg.fee_bps + cfg.slippage_bps) / 10000
    lo, hi = 0.0, before
    for _ in range(70):
        nav = (lo+hi)/2
        residual = nav + cost_rate*sum(abs(w*nav-v) for w, v in zip(targets, current)) - before
        if residual > 0:
            hi = nav
        else:
            lo = nav
    nav = (lo+hi)/2
    new = [nav*w/p for w, p in zip(targets, prices)]
    ledger, costs = [], 0.0
    for j, (old, qty, px) in enumerate(zip(units, new, prices)):
        delta = qty-old
        if abs(delta*px) < 1e-8:
            continue
        amount = abs(delta*px)
        fee, slip = amount*cfg.fee_bps/10000, amount*cfg.slippage_bps/10000
        costs += fee+slip
        ledger.append(dict(date=day, signal_date=signal_day, symbol=symbols[j],
                           side="BUY" if delta > 0 else "SELL", research_units=abs(delta),
                           reference_open=px, notional=amount, fee=fee,
                           slippage_cost=slip, target_weight=targets[j]))
    new_cash = before - sum(q*p for q, p in zip(new, prices)) - costs
    if new_cash < -1e-6:
        raise ArithmeticError("Cash conservation failed")
    return max(new_cash, 0.0), new, ledger, costs


def metrics(returns):
    nav, peak, drawdown = 1.0, 1.0, 0.0
    for r in returns:
        nav *= 1+r
        peak = max(peak, nav)
        drawdown = min(drawdown, nav/peak-1)
    vol = st.stdev(returns) if len(returns) > 1 else 0.0
    return dict(total_return=nav-1, annualized_return=nav**(252/len(returns))-1 if returns else 0.,
                annualized_vol=vol*math.sqrt(252),
                sharpe=st.mean(returns)/vol*math.sqrt(252) if vol else None,
                max_drawdown=drawdown, intervals=len(returns))


def backtest(panel, features, factors, signs, start, end, cfg, benchmark=False):
    """Segment is [start,end); signal t-1, transact t open, mark t+1 open.

    Each segment starts with cash, pays entry and terminal exit costs. Units
    drift between trades. Benchmark is same-universe equal-weight, same costs
    and rebalance calendar. Final equity includes explicit liquidation cost.
    """
    n = len(panel.symbols)
    units, cash = [0.0]*n, cfg.initial_cash
    returns, equity, trades = [], [], []
    total_cost, peak = 0.0, cfg.initial_cash
    for t in range(start, end-1):
        before = cash + sum(q*p for q, p in zip(units, panel.opens[t]))
        if (t-start) % cfg.rebalance == 0:
            weights = [1/n]*n if benchmark else target_at(
                features, t-1, factors, signs, cfg.top_k, n)[0]
            cash, units, ledger, cost = rebalance_account(cash, units, panel.opens[t], weights,
                                                        cfg, panel.symbols, panel.dates[t], panel.dates[t-1])
            trades.extend(ledger)
            total_cost += cost
        after = cash + sum(q*p for q, p in zip(units, panel.opens[t+1]))
        if t == end-2:
            cash, units, ledger, cost = rebalance_account(cash, units, panel.opens[t+1], [0.0]*n,
                                                        cfg, panel.symbols, panel.dates[t+1], "TERMINAL_EXIT")
            trades.extend(ledger)
            total_cost += cost
            after = cash
        returns.append(after/before-1)
        peak = max(peak, after)
        equity.append(dict(date=panel.dates[t+1], nav=after/cfg.initial_cash,
                           equity=after, cash=cash, daily_return=returns[-1],
                           drawdown=after/peak-1))
    return {"metrics": {**metrics(returns), "total_cost": total_cost,
                         "trade_count": len(trades)}, "equity": equity, "trades": trades}


def svg_chart(strategy, benchmark, title):
    s, b = [1.0]+[r["nav"] for r in strategy], [1.0]+[r["nav"] for r in benchmark]
    lo, hi = min(s+b), max(s+b)
    span = hi-lo or .01
    def points(vals):
        return " ".join(f"{60+i*860/(len(vals)-1):.1f},{270-(v-lo)/span*210:.1f}" for i,v in enumerate(vals))
    ticks = "".join(f'<text x="8" y="{275-i*70}">{lo+i*span/3:.2f}</text>' for i in range(4))
    return f'''<svg viewBox="0 0 960 330" role="img" aria-label="{html.escape(title)}">
    <rect x="0" y="0" width="960" height="330" fill="#0e1929"/>{ticks}
    <path d="M60 55 V270 H920" fill="none" stroke="#40516a"/>
    <polyline points="{points(b)}" fill="none" stroke="#8195b3" stroke-width="2"/>
    <polyline points="{points(s)}" fill="none" stroke="#4be2b0" stroke-width="3"/>
    <text x="60" y="315">策略净值（绿） / 同池等权基准（灰）；均含成本与末期平仓</text></svg>'''


def report(path, summary, test, bench):
    m, bm = test["metrics"], bench["metrics"]
    pct = lambda x: f"{x:.2%}"
    num = lambda x: "N/A" if x is None else f"{x:.2f}"
    rows = "".join(f'<tr><td>{html.escape(r["factor"])}</td><td>{r["direction"]:+d}</td>'
                   f'<td>{r["train"]["mean_rank_ic"]:.3f}</td><td>{r["valid"]["mean_rank_ic"]:.3f}</td>'
                   f'<td>{r["test"]["mean_rank_ic"]:.3f}</td></tr>' for r in summary["factor_audit"])
    source_label = "合成数据演示 · 非真实业绩" if summary["synthetic"] else "用户提供/下载历史数据 · 未经独立校验"
    cards = [("测试期收益（含费用）", pct(m["total_return"])), ("同池等权基准", pct(bm["total_return"])),
             ("最大回撤", pct(m["max_drawdown"])), ("Sharpe（无风险利率=0）", num(m["sharpe"]))]
    card_html = "".join(f'<div class="card"><small>{k}</small><strong>{v}</strong></div>' for k,v in cards)
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>ETF 因子研究报告</title>
    <style>body{{background:#08111f;color:#e3edf8;font:16px/1.7 system-ui,"Microsoft YaHei",sans-serif;margin:0}}
    main{{max-width:1080px;margin:48px auto;padding:0 24px}}h1{{font-size:38px;margin:8px 0}}h2{{margin-top:36px}}
    .tag{{color:#4be2b0;letter-spacing:2px}}.notice{{background:#302717;border:1px solid #8f7039;padding:16px;border-radius:12px}}
    .cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:16px;margin:24px 0}}
    .card{{background:#122137;border-radius:12px;padding:20px}}strong{{display:block;font-size:30px}}small,p{{color:#aebfd3}}
    svg{{width:100%;border-radius:12px}}svg text{{fill:#aebfd3;font-size:14px}}table{{border-collapse:collapse;width:100%;font-size:14px}}
    td,th{{border-bottom:1px solid #26354a;padding:10px;text-align:left}}code{{color:#4be2b0}}a{{color:#79c8ff}}</style>
    <main><div class="tag">FACTOR LAB / UNDERGRADUATE RESEARCH</div><h1>ETF 多因子研究 Agent</h1>
    <div class="notice">{source_label}。本项目为规则驱动研究 Agent，历史回放采用可分割的复权财富指数单位；未连接券商或实时订单。</div>
    <p>数据：{summary['dates'][0]} → {summary['dates'][-1]} ｜ 标的 {summary['universe_size']} 个 ｜ 候选因子 6 个 ｜ 候选策略 {len(summary['validation_candidates'])} 个</p>
    <div class="cards">{card_html}</div><h2>独立测试集净值</h2>
    <p>{summary['split']['test'][0]} → {summary['split']['test'][1]}。只展示验证集选定的策略：<code>{html.escape(summary['selected_name'])}</code>。</p>
    {svg_chart(test['equity'], bench['equity'], '独立测试集策略与基准净值')}
    <h2>因子审计</h2><p>训练集确定正负方向；表中 IC 为原始因子方向，测试集 IC 只用于事后报告。5 期标签使用下一开盘至第 6 日开盘，跨分割边界标签剔除。</p>
    <table><tr><th>因子</th><th>训练方向</th><th>训练 Rank IC</th><th>验证 Rank IC</th><th>测试 Rank IC</th></tr>{rows}</table>
    <h2>交易与复现</h2><p>收盘后计算信号，下一交易日开盘成交；每 {summary['config']['rebalance']} 个交易日调仓。
    单边手续费 {summary['config']['fee_bps']} bps + 滑点 {summary['config']['slippage_bps']} bps（均为研究假设）。
    测试期账本 {m['trade_count']} 条，累计费用 {m['total_cost']:.2f}，末期已平仓。</p>
    <p>同池等权基准采用相同日期、调仓周期和成本。年化按 252 日，无风险利率为 0；短测试窗口年化不稳定。</p>
    <p>文件：<a href="trades.csv">成交账本</a> · <a href="equity.csv">每日净值</a> · <a href="summary.json">完整审计</a> · <a href="model.json">冻结模型</a> · <a href="pending_orders.csv">下一开盘目标（未成交）</a></p>
    <h2>研究边界</h2><p>小样本 ETF 横截面 IC 仅作探索；7 个候选的验证集比较仍存在多重检验风险。
    固定存续 ETF 池存在选择偏差，未处理历史成份调整。复权研究单位不等于可执行份额；未模拟最小交易单位、涨跌停排队、停牌、最低佣金和市场冲击。
    真实行情下载仅为接口适配，必须检查复权、分红与数据授权后再研究。当前结果不构成可交易盈利证据。</p>
    <p>方法参考：<a href="https://qlib.readthedocs.io/en/stable/reference/api.html">Qlib 的信号移位与交易费用接口</a>；
    <a href="https://akshare.akfamily.xyz/data/fund/fund_public.html">AKShare ETF 历史行情与复权说明</a>。</p></main></html>'''
    Path(path).write_text(page, encoding="utf-8")


def research(data, out, cfg, meta_path=None):
    cfg.validate()
    panel = Panel.load(data)
    if cfg.top_k > len(panel.symbols):
        raise ValueError("top_k exceeds universe")
    meta_path = Path(meta_path) if meta_path else Path(data).with_suffix(".meta.json")
    if not meta_path.exists():
        raise ValueError("Metadata JSON required; explicitly identify source, synthetic flag and price_basis")
    meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    if type(meta.get("synthetic")) is not bool or not meta.get("source") or not meta.get("price_basis"):
        raise ValueError("Metadata requires boolean synthetic, nonempty source and price_basis")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    features = all_factors(panel)
    first, n = cfg.warmup+1, len(panel.dates)
    train_end = first + int((n-first)*.50)
    valid_end = first + int((n-first)*.75)
    bounds = {"train": (first, train_end), "valid": (train_end, valid_end), "test": (valid_end, n)}
    signs, audit = {}, []
    # Research policy and candidate family fixed in code before opening test outcomes.
    for f in FACTORS:
        train = ic_summary(panel, features, f, first, train_end, cfg.horizon)
        signs[f] = 1 if train["mean_rank_ic"] >= 0 else -1
        audit.append(dict(factor=f, definition=FACTOR_NOTES[f], direction=signs[f], train=train))
    ranked = sorted(audit, key=lambda r: (-abs(r["train"]["mean_rank_ic"]), r["factor"]))
    ensemble = [r["factor"] for r in ranked[:3]]
    candidates = [(f, [f]) for f in FACTORS] + [("ensemble_train_top3", ensemble)]
    valid_results = []
    for name, fs in candidates:
        bt = backtest(panel, features, fs, signs, train_end, valid_end, cfg)
        valid_results.append(dict(name=name, factors=fs, metrics=bt["metrics"]))
    selected = max(valid_results, key=lambda r: (
        r["metrics"]["sharpe"] if r["metrics"]["sharpe"] is not None else -1e99,
        r["metrics"]["total_return"], r["name"]))
    source_hash = hashlib.sha256(Path(data).read_bytes()).hexdigest()
    model = dict(version=1, selected_name=selected["name"], factors=selected["factors"],
                 directions=signs, config=asdict(cfg), symbols=panel.symbols,
                 frozen_after=panel.dates[valid_end-1], data_sha256=source_hash,
                 selection="train signed IC; validation net Sharpe; frozen before test")
    dump(out/"model.json", model)
    # Only now run untouched test partition and collect post-selection diagnostics.
    test = backtest(panel, features, model["factors"], signs, valid_end, n, cfg)
    bench = backtest(panel, features, [], {}, valid_end, n, cfg, benchmark=True)
    for row in audit:
        for partition in ("valid", "test"):
            row[partition] = ic_summary(panel, features, row["factor"], *bounds[partition], cfg.horizon)
    summary = dict(synthetic=meta["synthetic"], data_metadata=meta, data_sha256=source_hash,
                   dates=panel.dates, universe_size=len(panel.symbols), config=asdict(cfg),
                   split={k: [panel.dates[a], panel.dates[b-1]] for k,(a,b) in bounds.items()},
                   selected_name=selected["name"], validation_candidates=valid_results,
                   factor_audit=audit, test=test["metrics"], benchmark=bench["metrics"])
    dump(out/"summary.json", summary)
    write_csv(out/"factor_audit.csv", [dict(factor=r["factor"], direction=r["direction"],
              **{p+"_ic": r[p]["mean_rank_ic"] for p in bounds}) for r in audit])
    write_csv(out/"trades.csv", test["trades"], ["date", "signal_date", "symbol", "side", "research_units",
                                               "reference_open", "notional", "fee", "slippage_cost", "target_weight"])
    write_csv(out/"equity.csv", test["equity"])
    write_csv(out/"benchmark_equity.csv", bench["equity"])
    pending(panel, model, out/"pending_orders.csv")
    dump(out/"agent_log.json", [
        {"stage": "data_audit", "rows": len(panel.dates)*len(panel.symbols), "source": meta},
        {"stage": "hypotheses", "fixed_factor_family": FACTOR_NOTES},
        {"stage": "training", "directions": signs, "purged_horizon": cfg.horizon+1},
        {"stage": "validation_selection", "selected": selected},
        {"stage": "freeze", "model": "model.json"},
        {"stage": "test_once", "metrics": test["metrics"]},
        {"stage": "pending_next_open", "status": "UNFILLED_RESEARCH_TARGETS"}])
    report(out/"report.html", summary, test, bench)
    return summary


def pending(panel, model, path):
    if panel.symbols != model["symbols"]:
        raise ValueError("Universe differs from frozen model")
    if panel.dates[-1] <= model["frozen_after"]:
        raise ValueError("Pending targets require data later than model freeze")
    cfg = Config(**model["config"])
    t = len(panel.dates)-1
    weights, scores = target_at({t: factor_at(panel, t)}, t, model["factors"], model["directions"],
                                cfg.top_k, len(panel.symbols))
    write_csv(path, [dict(signal_date=panel.dates[t], symbol=s, target_weight=w, score=score,
                         status="UNFILLED_RESEARCH_TARGET", execute="NEXT_AVAILABLE_OPEN_IF_SCHEDULED")
                     for s,w,score in zip(panel.symbols, weights, scores)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="Generate labeled synthetic data and execute the whole workflow")
    demo.add_argument("--out", default="results/demo")
    run = sub.add_parser("research", help="Research an adjusted-price balanced CSV")
    run.add_argument("--data", required=True)
    run.add_argument("--meta")
    run.add_argument("--out", default="results/research")
    run.add_argument("--config", default="config.json")
    orders = sub.add_parser("pending", help="Apply frozen model; create unfilled research targets only")
    orders.add_argument("--data", required=True)
    orders.add_argument("--model", required=True)
    orders.add_argument("--out", default="pending_orders.csv")
    args = parser.parse_args()
    if args.command == "demo":
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        data = out/"synthetic_prices.csv"
        make_demo(data)
        summary = research(data, out, Config())
    elif args.command == "research":
        cfg = Config(**json.loads(Path(args.config).read_text(encoding="utf-8-sig")))
        summary = research(args.data, args.out, cfg, args.meta)
    else:
        panel = Panel.load(args.data)
        model = json.loads(Path(args.model).read_text(encoding="utf-8-sig"))
        pending(panel, model, args.out)
        print("Unfilled research targets:", args.out)
        return
    print(json.dumps({"synthetic": summary["synthetic"], "selected": summary["selected_name"],
                      "test": summary["test"], "report": str(Path(args.out)/"report.html")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
