import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path

from agent import (Config, Panel, all_factors, backtest, ic_summary, make_demo,
                   ranks, rebalance_account, research)
from scripts.fetch_etf import fetch
from scripts.package_release import package


class AgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = Path(__file__).resolve().parents[1]
        cls.tmp = tempfile.TemporaryDirectory(dir=cls.project)
        cls.root = Path(cls.tmp.name)
        cls.data = cls.root/"prices.csv"
        make_demo(cls.data, days=400)
        cls.panel = Panel.load(cls.data)
        cls.features = all_factors(cls.panel)

    @classmethod
    def tearDownClass(cls):
        assert Path(cls.tmp.name).resolve().is_relative_to(cls.project)
        cls.tmp.cleanup()

    def test_tied_ranks(self):
        self.assertEqual(ranks([3, 1, 1, 4]), [2, .5, .5, 3])

    def test_nonfinite_or_boolean_financial_parameters_rejected(self):
        for field in ("initial_cash", "fee_bps", "slippage_bps"):
            for value in (float("nan"), float("inf"), True, "3"):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    Config(**{field: value}).validate()

    def test_integer_parameters_reject_floats_and_booleans(self):
        for field in ("top_k", "rebalance", "warmup", "horizon", "seed"):
            for value in (3.5, True):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    Config(**{field: value}).validate()

    def test_oversized_warmup_rejected_before_split(self):
        with self.assertRaisesRegex(ValueError, "Too few"):
            research(self.data, self.root/"bad_warmup", Config(warmup=400))

    def test_pending_rejects_unknown_factors_or_invalid_directions(self):
        from agent import pending
        base = dict(symbols=self.panel.symbols, frozen_after=self.panel.dates[100],
                    config=vars(Config()), factors=["unknown"], directions={})
        with self.assertRaisesRegex(ValueError, "unknown"):
            pending(self.panel, base, self.root/"bad_pending.csv")
        base.update(factors=["momentum_20"], directions={"momentum_20": 0})
        with self.assertRaisesRegex(ValueError, "directions"):
            pending(self.panel, base, self.root/"bad_pending.csv")

    def test_custom_horizon_is_reflected_in_report(self):
        out = self.root/"horizon_three"
        research(self.data, out, Config(horizon=3))
        page = (out/"report.html").read_text(encoding="utf-8")
        self.assertIn("3 期标签使用下一开盘至第 4 日开盘", page)

    def test_release_packager_refuses_real_data(self):
        root = self.root/"unsafe_release"
        demo = root/"results/demo"
        demo.mkdir(parents=True)
        (root/"VERSION").write_text("0.1.0", encoding="utf-8")
        (demo/"summary.json").write_text('{"synthetic":false}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "synthetic"):
            package(root, root/"dist")

    def test_cash_units_and_cost_conservation(self):
        cfg = Config(fee_bps=20, slippage_bps=30)
        cash, units, ledger, cost = rebalance_account(100000, [0]*3, [10]*3,
                    [1/3]*3, cfg, ["a", "b", "c"], "t", "t-1")
        self.assertGreaterEqual(cash, 0)
        self.assertAlmostEqual(cash+sum(q*10 for q in units)+cost, 100000, places=7)
        self.assertAlmostEqual(cost, sum(r["fee"]+r["slippage_cost"] for r in ledger))
        final, flat, _, exit_cost = rebalance_account(cash, units, [10]*3, [0]*3,
                     cfg, ["a", "b", "c"], "t+1", "exit")
        self.assertEqual(flat, [0]*3)
        self.assertAlmostEqual(final+cost+exit_cost, 100000, places=7)

    def test_factor_inputs_never_use_future(self):
        changed = copy.deepcopy(self.panel)
        changed.closes[151] = [x*10 for x in changed.closes[151]]
        from agent import factor_at
        self.assertEqual(factor_at(self.panel, 150), factor_at(changed, 150))

    def test_same_day_close_cannot_change_open_orders(self):
        changed = copy.deepcopy(self.features)
        changed[201] = {f: list(reversed(v)) for f,v in changed[201].items()}
        args = (["momentum_20"], {"momentum_20": 1}, 201, 207, Config())
        before = backtest(self.panel, self.features, *args)
        after = backtest(self.panel, changed, *args)
        first_day = self.panel.dates[201]
        self.assertEqual([r for r in before["trades"] if r["date"] == first_day],
                         [r for r in after["trades"] if r["date"] == first_day])
        self.assertTrue(all(r["signal_date"] < r["date"] for r in before["trades"]
                            if r["signal_date"] != "TERMINAL_EXIT"))

    def test_ic_labels_purged_at_boundary(self):
        changed = copy.deepcopy(self.panel)
        for t in range(200, 400):
            changed.opens[t] = [x*(j+1)*10 for j,x in enumerate(changed.opens[t])]
        self.assertEqual(ic_summary(self.panel, self.features, "momentum_20", 61, 200),
                         ic_summary(changed, self.features, "momentum_20", 61, 200))

    def test_constant_prices_have_only_round_trip_cost(self):
        constant = copy.deepcopy(self.panel)
        constant.opens = [[10.]*12 for _ in constant.dates]
        cfg = Config(rebalance=1000, fee_bps=10, slippage_bps=0)
        bt = backtest(constant, self.features, ["momentum_20"], {"momentum_20": 1}, 201, 220, cfg)
        self.assertAlmostEqual(bt["metrics"]["total_return"], .999/1.001-1, places=10)
        self.assertAlmostEqual(bt["equity"][-1]["cash"], bt["equity"][-1]["equity"])

    def test_duplicate_or_missing_quotes_rejected(self):
        with self.data.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        from agent import write_csv
        for label, data in [("duplicate", rows+[rows[0]]), ("missing", rows[1:])]:
            bad = self.root/(label+".csv")
            write_csv(bad, data)
            with self.assertRaises(ValueError):
                Panel.load(bad)

    def test_model_selection_unaffected_by_test_data(self):
        first = research(self.data, self.root/"run1", Config())
        test_start = first["split"]["test"][0]
        mutated = self.root/"changed.csv"
        with self.data.open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            if row["date"] >= test_start:
                scale = 1 + int(row["symbol"][-2:])*.1
                row["open"] = float(row["open"])*scale
                row["close"] = float(row["close"])*scale
        from agent import write_csv
        write_csv(mutated, rows)
        mutated.with_suffix(".meta.json").write_bytes(self.data.with_suffix(".meta.json").read_bytes())
        second = research(mutated, self.root/"run2", Config())
        m1 = json.loads((self.root/"run1/model.json").read_text(encoding="utf-8"))
        m2 = json.loads((self.root/"run2/model.json").read_text(encoding="utf-8"))
        for key in ("factors", "directions", "frozen_after", "selected_name"):
            self.assertEqual(m1[key], m2[key])
        self.assertEqual(first["validation_candidates"], second["validation_candidates"])
        self.assertNotEqual(first["test"]["total_return"], second["test"]["total_return"])

    def test_adapter_schema_mapping_with_fixture(self):
        # Offline schema contract; does NOT assert live API availability.
        class Frame:
            empty = False
            columns = ["日期", "开盘", "收盘", "成交量"]
            def iterrows(self):
                yield 0, {"日期": "2025-01-02", "开盘": 2, "收盘": 2.1, "成交量": 100}
        class FakeAk:
            def fund_etf_hist_em(self, **kwargs):
                assert kwargs["adjust"] == "hfq"
                return Frame()
        rows = fetch(FakeAk(), ["510300"], "20250101", "20250103")
        self.assertEqual(rows[0]["symbol"], "510300")
        self.assertEqual(rows[0]["close"], 2.1)


if __name__ == "__main__":
    unittest.main()
