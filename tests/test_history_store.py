import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import history_store  # noqa: E402


def make_dataset(periods):
    records = []
    for period in periods:
        records.append({
            "period": period,
            "city": "北京",
            "indicator": "新建商品住宅销售价格指数",
            "metrics": {"环比": 100.0},
            "source_url": f"https://example.com/{period}",
        })
    return {"records": records}


class HistoryStoreTests(unittest.TestCase):
    def test_merge_new_periods(self):
        store = {}
        summary = history_store.merge(store, make_dataset(["2024-01", "2024-02"]))

        self.assertEqual(summary["new"], ["2024-01", "2024-02"])
        self.assertEqual(summary["total_in_store"], 2)
        self.assertIn("first_fetched_at", store["periods"]["2024-01"])

    def test_merge_unchanged_period_updates_last_fetched_only(self):
        store = {}
        history_store.merge(store, make_dataset(["2024-01"]))
        summary = history_store.merge(store, make_dataset(["2024-01"]))

        self.assertEqual(summary["unchanged"], ["2024-01"])
        self.assertEqual(summary["new"], [])
        self.assertEqual(store["periods"]["2024-01"]["revisions"], [])

    def test_merge_revised_period_keeps_old_version(self):
        store = {}
        history_store.merge(store, make_dataset(["2024-01"]))

        revised = make_dataset(["2024-01"])
        revised["records"][0]["metrics"]["环比"] = 99.9
        summary = history_store.merge(store, revised)

        self.assertEqual(summary["revised"], ["2024-01"])
        entry = store["periods"]["2024-01"]
        self.assertEqual(entry["records"][0]["metrics"]["环比"], 99.9)
        self.assertEqual(len(entry["revisions"]), 1)
        self.assertEqual(entry["revisions"][0]["records"][0]["metrics"]["环比"], 100.0)

    def test_revisions_capped_at_max(self):
        store = {}
        history_store.merge(store, make_dataset(["2024-01"]))

        for value in (99.1, 99.2, 99.3):
            dataset = make_dataset(["2024-01"])
            dataset["records"][0]["metrics"]["环比"] = value
            history_store.merge(store, dataset)

        entry = store["periods"]["2024-01"]
        self.assertEqual(len(entry["revisions"]), history_store.MAX_REVISIONS)
        self.assertEqual(entry["records"][0]["metrics"]["环比"], 99.3)

    def test_merge_unchanged_when_only_source_url_differs(self):
        store = {}
        history_store.merge(store, make_dataset(["2024-01"]))

        url_changed = make_dataset(["2024-01"])
        url_changed["records"][0]["source_url"] = "https://example.com/rewritten-url"
        summary = history_store.merge(store, url_changed)

        self.assertEqual(summary["unchanged"], ["2024-01"])
        self.assertEqual(summary["revised"], [])
        self.assertEqual(store["periods"]["2024-01"]["revisions"], [])

    def test_merge_rejects_degraded_period_without_force(self):
        store = {}
        full = make_dataset(["2024-01"])
        full["records"] = [
            {"period": "2024-01", "city": f"城市{i}", "indicator": "x", "metrics": {"环比": 100.0}, "source_url": "u"}
            for i in range(10)
        ]
        history_store.merge(store, full)

        degraded = make_dataset(["2024-01"])  # 只有 1 条记录 < 50%
        summary = history_store.merge(store, degraded)
        self.assertEqual(len(summary["rejected"]), 1)
        self.assertEqual(store["periods"]["2024-01"]["record_count"], 10)

        forced = history_store.merge(store, degraded, force=True)
        self.assertEqual(forced["revised"], ["2024-01"])
        self.assertEqual(store["periods"]["2024-01"]["record_count"], 1)

    def test_store_metadata(self):
        store = {}
        history_store.merge(store, make_dataset(["2024-01", "2024-03"]))
        history_store.store_metadata(store)

        self.assertEqual(store["period_count"], 2)
        self.assertEqual(store["period_range"], {"first": "2024-01", "last": "2024-03"})
        self.assertEqual(store["latest_period"], "2024-03")

    def test_group_by_period_skips_missing_period(self):
        grouped = history_store.group_by_period([
            {"period": "2024-01", "city": "北京"},
            {"city": "北京"},
        ])
        self.assertEqual(list(grouped), ["2024-01"])


if __name__ == "__main__":
    unittest.main()
