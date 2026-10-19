"""Optional exportable research figure. Requires matplotlib, outside core runtime."""
import argparse
import csv
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results", default="results/demo")
    args = p.parse_args()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as md
    from datetime import date
    root = Path(args.results)
    summary = json.loads((root/"summary.json").read_text(encoding="utf-8"))
    def read(name):
        with (root/name).open(encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    strategy, benchmark = read("equity.csv"), read("benchmark_equity.csv")
    dates = [date.fromisoformat(summary["split"]["test"][0])] + [date.fromisoformat(r["date"]) for r in strategy]
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1]}, layout="constrained")
    for rows, label, color in [(strategy, "Selected strategy", "#008b75"),
                                (benchmark, "Same-universe equal weight", "#738299")]:
        navs = [1.] + [float(r["nav"]) for r in rows]
        peak, dd = 1., []
        for nav in navs:
            peak = max(peak, nav)
            dd.append((nav/peak-1)*100)
        axes[0].plot(dates, navs, label=label, color=color, linewidth=1.8)
        axes[1].plot(dates, dd, color=color, linewidth=1.3)
    axes[0].set_ylabel("Net asset value (start = 1)")
    axes[0].legend(loc="upper left", frameon=False)
    axes[1].set_ylabel("Drawdown (%)")
    axes[1].xaxis.set_major_locator(md.MonthLocator(interval=2))
    axes[1].xaxis.set_major_formatter(md.DateFormatter("%Y-%m"))
    for ax in axes:
        ax.grid(alpha=.2)
    source = "SYNTHETIC DATA | NOT REAL MARKET PERFORMANCE" if summary["synthetic"] else "HISTORICAL DATA | RESEARCH SIMULATION"
    fig.suptitle("ETF Factor Research Agent — Independent Test\n" + source,
                 fontsize=14, fontweight="bold")
    axes[0].set_title("Costs included: 3 bps commission + 5 bps slippage per side; terminal exit included", fontsize=9, color="#59616b")
    fig.savefig(root/"overview.png", dpi=180)
    plt.close(fig)
    print(root/"overview.png")


if __name__ == "__main__":
    main()
