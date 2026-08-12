import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_lpr  # noqa: E402


LISTING_HTML = """
<html><body>
<a href="/zhengcehuobisi/125207/125213/125440/3876551/2026072008093186869/index.html"
   onclick="void(0)" title="2026年7月20日全国银行间同业拆借中心受权公布贷款市场报价利率（LPR）公告" istitle="true">公告</a>
<a href="/zhengcehuobisi/125207/125213/125440/3876551/2026062208495122562/index.html"
   title="2026年6月22日全国银行间同业拆借中心受权公布贷款市场报价利率（LPR）公告">公告</a>
<a href="/zhengcehuobisi/other/index.html" istitle="true" title="其他公告">无关条目</a>
</body></html>
""".encode("utf-8")

DETAIL_HTML = """
<html><body>
<p>2026年7月20日全国银行间同业拆借中心受权公布贷款市场报价利率（LPR）公告</p>
<p>1年期LPR为3.0%，5年期以上LPR为3.5%。以上LPR在下一次发布LPR之前有效。</p>
</body></html>
""".encode("utf-8")

DETAIL_HTML_VARIANTS = """
<html><body>
<p>2024年10月21日公告</p>
<p>1 年 期 LPR 为 3.10 %，5 年 期 以 上 LPR 为 3.60％。</p>
</body></html>
""".encode("utf-8")

DETAIL_HTML_MISSING_5Y = """
<html><body>
<p>2025年5月20日公告</p>
<p>1年期LPR为3.0%。</p>
</body></html>
""".encode("utf-8")


class LprParsingTests(unittest.TestCase):
    def test_parse_listing_extracts_entries_and_joins_urls(self):
        entries = fetch_lpr.parse_lpr_listing(
            LISTING_HTML, "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/3876551/index.html"
        )

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["period"], "2026-07")
        self.assertEqual(entries[0]["date"], "2026-07-20")
        self.assertTrue(entries[0]["url"].startswith("https://www.pbc.gov.cn/zhengcehuobisi/125207"))
        self.assertEqual(entries[1]["period"], "2026-06")

    def test_parse_detail_extracts_rates_and_date(self):
        parsed = fetch_lpr.parse_lpr_detail(DETAIL_HTML)

        self.assertEqual(parsed["date"], "2026-07-20")
        self.assertEqual(parsed["lpr_1y"], 3.0)
        self.assertEqual(parsed["lpr_5y"], 3.5)
        self.assertEqual(parsed["warnings"], [])

    def test_parse_detail_handles_whitespace_and_fullwidth_percent(self):
        parsed = fetch_lpr.parse_lpr_detail(DETAIL_HTML_VARIANTS)

        self.assertEqual(parsed["date"], "2024-10-21")
        self.assertEqual(parsed["lpr_1y"], 3.10)
        self.assertEqual(parsed["lpr_5y"], 3.60)
        self.assertEqual(parsed["warnings"], [])

    def test_parse_detail_warns_on_missing_5y(self):
        parsed = fetch_lpr.parse_lpr_detail(DETAIL_HTML_MISSING_5Y)

        self.assertIsNone(parsed["lpr_5y"])
        self.assertEqual(parsed["lpr_1y"], 3.0)
        self.assertTrue(any("5 年期" in warning for warning in parsed["warnings"]))

    def test_extract_pagination_reads_prefix_and_total(self):
        html = '<a tagname="/zhengcehuobisi/125207/125213/125440/3876551/de24575c-2.html">下一页</a><input totalpage="5">'
        prefix, total = fetch_lpr.extract_pagination(html)
        self.assertEqual(prefix, "/zhengcehuobisi/125207/125213/125440/3876551/de24575c")
        self.assertEqual(total, 5)

    def test_extract_pagination_absent(self):
        prefix, total = fetch_lpr.extract_pagination("<html></html>")
        self.assertIsNone(prefix)
        self.assertEqual(total, 1)

    def test_build_output_shape(self):
        records = [
            {"period": "2026-06", "date": "2026-06-22", "lpr_1y": 3.0, "lpr_5y": 3.5, "source_url": "u1"},
            {"period": "2026-07", "date": "2026-07-20", "lpr_1y": 3.0, "lpr_5y": 3.5, "source_url": "u2"},
        ]
        output = fetch_lpr.build_output(records, "https://example.com/index.html", [])

        self.assertEqual(output["period_count"], 2)
        self.assertEqual(output["period_range"], {"first": "2026-06", "last": "2026-07"})


if __name__ == "__main__":
    unittest.main()
