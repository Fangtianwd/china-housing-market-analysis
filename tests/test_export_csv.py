import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import export_csv  # noqa: E402
from config import INDICATORS  # noqa: E402


def make_dataset():
    return {
        "generated_at": "2026-08-12T10:00:00+08:00",
        "record_count": 2,
        "records": [
            {
                "period": "2026-06",
                "city": "北京",
                "indicator": INDICATORS["new"],
                "metrics": {"环比": 99.4, "同比": 96.7, "累计平均": 96.7},
                "source_url": "https://example.com/1",
            },
            {
                "period": "2026-06",
                "city": "北京",
                "indicator": INDICATORS["new_cat"],
                "metrics": {
                    "90m2及以下_环比": 99.1,
                    "90m2及以下_同比": 96.2,
                    "90-144m2_环比": 99.6,
                    "144m2以上_环比": 99.9,
                },
                "source_url": "https://example.com/1",
            },
        ],
    }


class ExportCsvTests(unittest.TestCase):
    def test_record_to_rows_main_record(self):
        rows = export_csv.record_to_rows(make_dataset()["records"][0])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][:4], ["北京", "2026-06", "新建商品住宅", "全部"])
        self.assertEqual(rows[0][4], 99.4)

    def test_record_to_rows_category_record_expands_segments(self):
        rows = export_csv.record_to_rows(make_dataset()["records"][1])

        self.assertEqual(len(rows), 3)
        segments = {row[3] for row in rows}
        self.assertEqual(segments, {"90m2及以下", "90-144m2", "144m2以上"})
        small = next(row for row in rows if row[3] == "90m2及以下")
        self.assertEqual(small[4], 99.1)
        self.assertEqual(small[5], 96.2)

    def test_export_writes_utf8_bom(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "out.csv"
            summary = export_csv.export(make_dataset(), output_path)

            raw = output_path.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
            self.assertEqual(summary["row_count"], 4)
            self.assertEqual(summary["period_range"], {"first": "2026-06", "last": "2026-06"})

            lines = raw.decode("utf-8-sig").strip().splitlines()
            self.assertEqual(lines[0], ",".join(export_csv.CSV_HEADER))


if __name__ == "__main__":
    unittest.main()
