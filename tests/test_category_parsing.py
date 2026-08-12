import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_data  # noqa: E402
from config import INDICATORS  # noqa: E402


CATEGORY_TABLE = """
<p>表3：2026年6月70个大中城市新建商品住宅销售价格分类指数（一）</p>
<table>
  <tr><td>城市</td><td>90m2及以下</td><td>90-144m2</td><td>144m2以上</td></tr>
  <tr><td>环比</td><td>同比</td><td>1-6月平均</td><td>环比</td><td>同比</td><td>1-6月平均</td><td>环比</td><td>同比</td><td>1-6月平均</td></tr>
  <tr><td>上月=100</td><td>上年同月=100</td><td>上年同期=100</td><td>上月=100</td><td>上年同月=100</td><td>上年同期=100</td><td>上月=100</td><td>上年同月=100</td><td>上年同期=100</td></tr>
  <tr><td>北　　京</td><td>99.4</td><td>96.7</td><td>96.7</td><td>99.6</td><td>97.1</td><td>97.0</td><td>99.9</td><td>99.3</td><td>99.1</td></tr>
  <tr><td>银　　川</td><td>100.0</td><td>98.8</td><td>98.2</td><td>100.2</td><td>98.2</td><td>97.2</td><td>100.1</td><td>97.0</td><td>96.4</td></tr>
  <tr><td>乌鲁木齐</td><td>100.3</td><td>99.9</td><td>100.4</td><td>100.1</td><td>99.3</td><td>99.9</td><td>100.3</td><td>99.4</td><td>99.9</td></tr>
</table>
"""

CATEGORY_PAGE = f"""
<html>
  <body>
    <div class="trs_editor_view">
      {CATEGORY_TABLE}
    </div>
  </body>
</html>
""".encode("utf-8")


@unittest.skipUnless(fetch_data.DEPS_AVAILABLE, fetch_data.DEPS_ERROR or "缺少依赖")
class CategoryParsingTests(unittest.TestCase):
    def test_normalize_category_segment_variants(self):
        self.assertEqual(fetch_data.normalize_category_segment("90m2及以下"), "90m2及以下")
        self.assertEqual(fetch_data.normalize_category_segment("90平方米及以下"), "90m2及以下")
        self.assertEqual(fetch_data.normalize_category_segment("90㎡及以下"), "90m2及以下")
        self.assertEqual(fetch_data.normalize_category_segment("144m2以上"), "144m2以上")
        self.assertIsNone(fetch_data.normalize_category_segment("城市"))
        self.assertIsNone(fetch_data.normalize_category_segment("100.0"))

    def test_detect_indicator_prefers_category(self):
        soup = fetch_data.BeautifulSoup(CATEGORY_PAGE, "html.parser")
        table = soup.find("table")
        indicator = fetch_data.detect_indicator(table, ["表3：2026年6月70个大中城市新建商品住宅销售价格分类指数（一）"])
        self.assertEqual(indicator, INDICATORS["new_cat"])

    def test_parse_category_table_full_metrics(self):
        soup = fetch_data.BeautifulSoup(CATEGORY_PAGE, "html.parser")
        table = soup.find("table")

        records = fetch_data.parse_category_table(
            table, INDICATORS["new_cat"], "2026-06", "https://example.com/page"
        )

        self.assertEqual(len(records), 3)
        beijing = next(record for record in records if record["city"] == "北京")
        self.assertEqual(beijing["metrics"]["90m2及以下_环比"], 99.4)
        self.assertEqual(beijing["metrics"]["90-144m2_同比"], 97.1)
        self.assertEqual(beijing["metrics"]["144m2以上_累计平均"], 99.1)
        self.assertEqual(len(beijing["metrics"]), 9)

    def test_cumulative_avg_header_with_line_wrap_space(self):
        # 真实页面中表头换行会产生 "1-6月 平均" 的空格变体
        self.assertEqual(fetch_data.normalize_metric_name("1-6月 平均"), "累计平均")
        self.assertEqual(fetch_data.normalize_metric_name("1—12月平均"), "累计平均")

    def test_parse_category_table_filters_target_metrics(self):
        soup = fetch_data.BeautifulSoup(CATEGORY_PAGE, "html.parser")
        table = soup.find("table")

        records = fetch_data.parse_category_table(
            table, INDICATORS["new_cat"], "2026-06", "https://example.com/page",
            target_metrics=["环比"],
        )

        beijing = next(record for record in records if record["city"] == "北京")
        self.assertEqual(
            sorted(beijing["metrics"]),
            ["144m2以上_环比", "90-144m2_环比", "90m2及以下_环比"],
        )

    def test_parse_page_returns_category_record_for_target_city(self):
        records = fetch_data.parse_page(
            CATEGORY_PAGE,
            "2026-06",
            "乌鲁木齐",
            ["环比", "同比", "累计平均"],
            source_url="https://example.com/page",
        )

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["indicator"], INDICATORS["new_cat"])
        self.assertEqual(record["city"], "乌鲁木齐")
        self.assertEqual(record["metrics"]["90m2及以下_环比"], 100.3)

    def test_parse_page_skips_non_category_legacy_fixture(self):
        # 旧测试中的非标准分类表（列结构不符）不应产出记录
        legacy = """
        <html><body><div class="trs_editor_view">
          <p>2025年1月70个大中城市新建商品住宅销售价格分类指数</p>
          <table>
            <tr><th>城市</th><th>分类</th><th>环比</th></tr>
            <tr><td>武汉</td><td>90平方米及以下</td><td>100.0</td></tr>
          </table>
        </div></body></html>
        """.encode("utf-8")
        records = fetch_data.parse_page(
            legacy, "2025-01", "武汉", ["环比"], source_url="https://example.com/page"
        )
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
