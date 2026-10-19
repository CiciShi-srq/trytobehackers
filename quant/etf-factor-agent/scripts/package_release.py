"""Create a reproducible source + synthetic-demo release; stdlib only.

Uses an allowlist: private data, custom research results, caches and credentials
are excluded. Refuses to package a demo whose metadata is not synthetic.
"""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path


SOURCE_FILES = (
    "agent.py", "config.json", "VERSION", "README.md", "CHANGELOG.md",
    "RELEASE_NOTES.md", "requirements-data.txt", "run_demo.bat", ".gitignore",
    "项目经历与答辩.md", "scripts/fetch_etf.py", "scripts/plot_results.py",
    "scripts/package_release.py", "tests/test_agent.py",
)
DEMO_FILES = (
    "report.html", "summary.json", "model.json", "agent_log.json", "factor_audit.csv",
    "trades.csv", "equity.csv", "benchmark_equity.csv", "pending_orders.csv",
    "synthetic_prices.csv", "synthetic_prices.meta.json",
)


def package(root, dest):
    root, dest = Path(root).resolve(), Path(dest).resolve()
    version = (root/"VERSION").read_text(encoding="utf-8").strip()
    if not version or any(c not in "0123456789." for c in version):
        raise ValueError("Invalid version")
    demo = root/"results/demo"
    for name in ("summary.json", "synthetic_prices.meta.json"):
        if json.loads((demo/name).read_text(encoding="utf-8-sig")).get("synthetic") is not True:
            raise ValueError("Only explicitly synthetic demo data can be released")
    names = list(SOURCE_FILES) + ["results/demo/"+n for n in DEMO_FILES]
    missing = [n for n in names if not (root/n).is_file()]
    if missing:
        raise ValueError(f"Missing release files: {missing}")
    dest.mkdir(parents=True, exist_ok=True)
    target = dest/f"etf-factor-agent-{version}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(names):
            info = zipfile.ZipInfo("etf-factor-agent/"+name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, (root/name).read_bytes())
    with zipfile.ZipFile(target) as z:
        if z.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (dest/"SHA256SUMS").write_text(f"{digest}  {target.name}\n", encoding="ascii")
    return target, digest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default="dist")
    args = p.parse_args()
    target, digest = package(Path(__file__).resolve().parents[1], args.out)
    print(f"{target}\nSHA256 {digest}")


if __name__ == "__main__":
    main()
