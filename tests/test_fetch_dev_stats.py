import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_dev_stats  # noqa: E402


DEV_PAGE = """
<html><body><div class="trs_editor_view">
<p>2026年1—6月份全国房地产市场基本情况</p>
<table>
  <tr><td>指标</td><td>绝对量</td><td>同比增长（%）</td></tr>
  <tr><td>房地产开发投资（亿元）</td><td>38074</td><td>-18.0</td></tr>
  <tr><td>其中：住宅</td><td>29300</td><td>-17.8</td></tr>
  <tr><td>办公楼</td><td>1411</td><td>-20.4</td></tr>
  <tr><td>新建商品房销售额（亿元）</td><td>37945</td><td>-13.6</td></tr>
  <tr><td>其中：住宅</td><td>33270</td><td>-13.7</td></tr>
  <tr><td>房地产开发企业本年到位资金（亿元）</td><td>40233</td><td>-20.2</td></tr>
  <tr><td>其中：国内贷款</td><td>5716</td><td>-31.7</td></tr>
  <tr><td>定金及预收款</td><td>12442</td><td>-15.8</td></tr>
</table>
<table>
  <tr><td>地 区</td><td>投资额</td><td></td><td>同比增长</td><td></td></tr>
  <tr><td>（亿元）</td><td>住 宅</td><td>（%）</td><td>住 宅</td></tr>
  <tr><td>全国总计</td><td>38074</td><td>29300</td><td>-18.0</td><td>-17.8</td></tr>
  <tr><td>东北地区</td><td>641</td><td>497</td><td>-31.7</td><td>-32.3</td></tr>
</table>
<table>
  <tr><td>地 区</td><td>新建商品房销售面积</td><td></td><td>新建商品房销售额</td><td></td></tr>
  <tr><td>绝对数</td><td>同比增长</td><td>绝对数</td><td>同比增长</td></tr>
  <tr><td>全国总计</td><td>40140</td><td>-11.6</td><td>37945</td><td>-13.6</td></tr>
</table>
</div></body></html>
""".encode("utf-8")


@unittest.skipUnless(fetch_dev_stats.DEPS_AVAILABLE, fetch_dev_stats.DEPS_ERROR or "缺少依赖")
class DevStatsTests(unittest.TestCase):
    def test_parse_dev_period_variants(self):
        self.assertEqual(fetch_dev_stats.parse_dev_period("2026年1—6月份全国房地产市场基本情况"), "2026-06")
        self.assertEqual(fetch_dev_stats.parse_dev_period("2026年1-2月份全国房地产市场基本情况"), "2026-02")
        self.assertEqual(fetch_dev_stats.parse_dev_period("2025年12月份全国房地产市场基本情况"), "2025-12")
        self.assertEqual(fetch_dev_stats.parse_dev_period("2025年全国房地产市场基本情况"), "2025-12")
        self.assertEqual(fetch_dev_stats.parse_dev_period("2024年全国房地产市场基本情况"), "2024-12")
        self.assertEqual(fetch_dev_stats.parse_dev_period("2025年上半年全国房地产市场基本情况"), "2025-06")
        self.assertIsNone(fetch_dev_stats.parse_dev_period("不含期次的标题"))

    def test_positive_int_rejects_zero_and_negative(self):
        import argparse as _argparse
        self.assertEqual(fetch_dev_stats.positive_int("6"), 6)
        with self.assertRaises(_argparse.ArgumentTypeError):
            fetch_dev_stats.positive_int("0")
        with self.assertRaises(_argparse.ArgumentTypeError):
            fetch_dev_stats.positive_int("-3")

    def test_regional_records_carry_unit(self):
        parsed = fetch_dev_stats.parse_dev_page(DEV_PAGE)
        records = fetch_dev_stats.to_series_records(parsed, "2026-06", "https://example.com/page")

        by_id = {record["series_id"]: record for record in records}
        self.assertEqual(by_id["dev_region_全国总计_投资额_累计值"]["unit"], "亿元")
        self.assertEqual(by_id["dev_region_全国总计_销售面积_累计值"]["unit"], "万平方米")
        self.assertEqual(by_id["dev_region_全国总计_销售额_累计同比"]["unit"], "%")

    def test_header_cell_with_inner_space(self):
        # 真实页面变体：部分期次表头为「指 标」（字符间含空格）
        html = DEV_PAGE.decode("utf-8").replace(
            "<tr><td>指标</td>", "<tr><td>指 标</td>", 1
        ).encode("utf-8")
        parsed = fetch_dev_stats.parse_dev_page(html)
        self.assertTrue(parsed["indicators"])

    def test_notes_row_terminates_group(self):
        html = """
        <html><body><table>
          <tr><td>指标</td><td>绝对量</td><td>同比增长（%）</td></tr>
          <tr><td>房地产开发投资（亿元）</td><td>100</td><td>-5.0</td></tr>
          <tr><td>注：本表数据为累计值。</td><td></td><td></td></tr>
          <tr><td>办公楼</td><td>999</td><td>9.9</td></tr>
        </table></body></html>
        """
        soup = fetch_dev_stats.BeautifulSoup(html.encode("utf-8"), "html.parser")
        records = fetch_dev_stats.parse_main_indicator_table(soup.find("table"))

        # 注记行之后的无单位行不应归入上一组的子项
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["indicator"], "房地产开发投资")
        self.assertIsNone(fetch_dev_stats.parse_dev_period("2026年13月份异常标题"))

    def test_parse_main_indicator_grouping(self):
        parsed = fetch_dev_stats.parse_dev_page(DEV_PAGE)
        indicators = parsed["indicators"]

        by_key = {(item["indicator"], item["sub_item"]): item for item in indicators}
        self.assertEqual(by_key[("房地产开发投资", None)]["value"], 38074)
        self.assertEqual(by_key[("房地产开发投资", None)]["unit"], "亿元")
        self.assertEqual(by_key[("房地产开发投资", "住宅")]["yoy"], -17.8)
        self.assertEqual(by_key[("房地产开发投资", "办公楼")]["value"], 1411)
        self.assertEqual(by_key[("新建商品房销售额", "住宅")]["value"], 33270)
        self.assertEqual(by_key[("房地产开发企业本年到位资金", "国内贷款")]["yoy"], -31.7)
        self.assertEqual(by_key[("房地产开发企业本年到位资金", "定金及预收款")]["value"], 12442)

    def test_parse_regional_tables(self):
        parsed = fetch_dev_stats.parse_dev_page(DEV_PAGE)

        invest = {item["region"]: item for item in parsed["regional_investment"]}
        self.assertEqual(invest["全国总计"]["value"], 38074)
        self.assertEqual(invest["东北地区"]["residential_yoy"], -32.3)

        sales = {item["region"]: item for item in parsed["regional_sales"]}
        self.assertEqual(sales["全国总计"]["area_yoy"], -11.6)
        self.assertEqual(sales["全国总计"]["amount"], 37945)

    def test_to_series_records_contract(self):
        parsed = fetch_dev_stats.parse_dev_page(DEV_PAGE)
        records = fetch_dev_stats.to_series_records(parsed, "2026-06", "https://example.com/page")

        by_id = {record["series_id"]: record for record in records}
        self.assertIn("dev_房地产开发投资_累计值", by_id)
        self.assertIn("dev_房地产开发投资_住宅_累计同比", by_id)
        self.assertIn("dev_region_东北地区_投资额_住宅_累计同比", by_id)
        self.assertEqual(by_id["dev_新建商品房销售额_累计值"]["value"], 37945)
        self.assertTrue(all(record["period"] == "2026-06" for record in records))
        self.assertTrue(all(record["source_url"] == "https://example.com/page" for record in records))

    def test_parse_dev_page_dedupes_double_rendered_tables(self):
        # 真实页面每张表渲染两遍：拼接双份表格，结果不应膨胀
        tables_html = "".join(
            f"<table>{chunk}" for chunk in DEV_PAGE.decode("utf-8").split("<table>")[1:]
        )
        single = DEV_PAGE
        doubled = (
            "<html><body><div class=\"trs_editor_view\">"
            + tables_html + tables_html
            + "</div></body></html>"
        ).encode("utf-8")

        parsed_single = fetch_dev_stats.parse_dev_page(single)
        parsed_doubled = fetch_dev_stats.parse_dev_page(doubled)

        self.assertEqual(len(parsed_doubled["indicators"]), len(parsed_single["indicators"]))
        self.assertEqual(
            len(parsed_doubled["regional_investment"]), len(parsed_single["regional_investment"])
        )
        self.assertEqual(
            len(parsed_doubled["regional_sales"]), len(parsed_single["regional_sales"])
        )


if __name__ == "__main__":
    unittest.main()
