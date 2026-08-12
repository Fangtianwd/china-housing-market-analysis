import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_pbc  # noqa: E402


LISTING_HTML = """
<html><body>
<a href="5440/125838/5470606/2026073117132450967/index.html"
   title="2026年第二季度全国新发放商业性个人住房贷款加权平均利率" istitle="true">公告</a>
<a href="07/125213/125440/125838/5470606/5795573/index.html"
   title="2025年第二季度全国新发放商业性个人住房贷款加权平均利率">公告</a>
<a href="/zhengcehuobisi/other/index.html" title="2026年第二季度其他公告">无关</a>
</body></html>
""".encode("utf-8")

DETAIL_HTML = """
<html><head>
<meta name="PubDate" content="2026-07-31">
</head><body>
<p>2026年第二季度全国新发放商业性个人住房贷款加权平均利率为3.06%。</p>
</body></html>
""".encode("utf-8")


class PbcRateTests(unittest.TestCase):
    def test_parse_quarter_period_variants(self):
        self.assertEqual(fetch_pbc.parse_quarter_period("2026年第二季度全国新发放商业性个人住房贷款加权平均利率"), "2026-Q2")
        self.assertEqual(fetch_pbc.parse_quarter_period("2025年第四季度全国新发放商业性个人住房贷款加权平均利率"), "2025-Q4")
        self.assertEqual(fetch_pbc.parse_quarter_period("2024年 第 一 季度 公告"), "2024-Q1")
        self.assertIsNone(fetch_pbc.parse_quarter_period("不含季度的标题"))

    def test_parse_rate_listing_rebuilds_urls_and_filters(self):
        entries = fetch_pbc.parse_rate_listing(LISTING_HTML)

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["period"], "2025-Q2")
        self.assertEqual(entries[1]["period"], "2026-Q2")
        # 链接前缀残缺，应按栏目基址 + 文章目录重建
        self.assertTrue(entries[0]["article_url"].endswith("/5470606/5795573/index.html"))
        self.assertTrue(entries[0]["article_url"].startswith("https://www.pbc.gov.cn/"))
        self.assertTrue(entries[1]["article_url"].endswith("/5470606/2026073117132450967/index.html"))

    def test_parse_rate_detail_extracts_value(self):
        parsed = fetch_pbc.parse_rate_detail(DETAIL_HTML)
        self.assertEqual(parsed["rate"], 3.06)
        self.assertEqual(parsed["date"], "2026-07-31")
        self.assertEqual(parsed["warnings"], [])

    def test_parse_rate_detail_warns_on_missing_value(self):
        parsed = fetch_pbc.parse_rate_detail("<html><body><p>无数据</p></body></html>".encode("utf-8"))
        self.assertIsNone(parsed["rate"])
        self.assertTrue(parsed["warnings"])

    def test_parse_rate_detail_rejects_invalid_date(self):
        html = "<html><body><p>2026年13月45日 个人住房贷款加权平均利率为3.06%。</p></body></html>".encode("utf-8")
        parsed = fetch_pbc.parse_rate_detail(html)
        self.assertIsNone(parsed["date"])
        self.assertTrue(any("日期" in warning for warning in parsed["warnings"]))

    def test_build_output_shape(self):
        records = [
            {"period": "2025-Q2", "date": None, "rate": 3.09, "source_url": "u1"},
            {"period": "2026-Q2", "date": None, "rate": 3.06, "source_url": "u2"},
        ]
        output = fetch_pbc.build_output(records, [])
        self.assertEqual(output["period_count"], 2)
        self.assertEqual(output["period_range"], {"first": "2025-Q2", "last": "2026-Q2"})
        self.assertEqual(output["frequency"], "quarterly")


if __name__ == "__main__":
    unittest.main()
