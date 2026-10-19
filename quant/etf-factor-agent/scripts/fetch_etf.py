"""Optional AKShare adapter. Internet and optional dependency are required.

Daily HFQ prices represent adjusted wealth-index units, NOT executable prices.
Documentation: https://akshare.akfamily.xyz/data/fund/fund_public.html
"""
import argparse
import importlib.metadata
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import Panel, write_csv


def fetch(ak, symbols, start, end):
    rows = []
    for symbol in symbols:
        frame = ak.fund_etf_hist_em(symbol=symbol, period="daily", start_date=start,
                                    end_date=end, adjust="hfq")
        required = {"日期", "开盘", "收盘", "成交量"}
        if frame.empty or not required <= set(frame.columns):
            raise ValueError(f"Empty/changed upstream schema for {symbol}; no synthetic fallback")
        for _, row in frame.iterrows():
            rows.append(dict(date=str(row["日期"])[:10], symbol=symbol,
                             open=float(row["开盘"]), close=float(row["收盘"]),
                             volume=float(row["成交量"])))
    return sorted(rows, key=lambda r: (r["date"], r["symbol"]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbols", default="510050,510300,510500,159915,159928,512010,512660,512880,512800,512690")
    p.add_argument("--start", default="20200101")
    p.add_argument("--end", default="20251231")
    p.add_argument("--out", default="data/etf_history.csv")
    args = p.parse_args()
    try:
        import akshare as ak
    except ImportError:
        raise SystemExit("Install optional adapter: python -m pip install -r requirements-data.txt")
    symbols = args.symbols.split(",")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = fetch(ak, symbols, args.start, args.end)
    # Validate complete panel BEFORE publishing any CSV. Missing quotes are fatal.
    with tempfile.TemporaryDirectory(dir=out.parent) as tmp:
        candidate = Path(tmp)/"prices.csv"
        write_csv(candidate, rows)
        Panel.load(candidate)
        content = candidate.read_bytes()
    out.write_bytes(content)
    out.with_suffix(".meta.json").write_text(json.dumps({
        "source": "AKShare fund_etf_hist_em / Eastmoney", "synthetic": False,
        "price_basis": "hfq adjusted wealth-index units; not executable raw share prices",
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "akshare_version": importlib.metadata.version("akshare"),
        "symbols": symbols, "start": args.start, "end": args.end,
        "universe_policy": "fixed ex-post surviving ETF pool; selection/survivorship bias remains",
        "license_note": "Check upstream data terms; adapter grants no redistribution rights",
        "documentation": "https://akshare.akfamily.xyz/data/fund/fund_public.html"
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(rows)} rows to {out}. Review data before research.")


if __name__ == "__main__":
    main()
