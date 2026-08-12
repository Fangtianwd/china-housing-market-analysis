import sys
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_data  # noqa: E402
from config import INDICATORS  # noqa: E402
from exceptions import NetworkError  # noqa: E402


SAMPLE_HTML = """
<html>
  <body>
    <div class="trs_editor_view">
      <p>2025年1月70个大中城市新建商品住宅销售价格指数</p>
      <table>
        <tr><th>城市</th><th>环比</th><th>同比</th><th>定基</th></tr>
        <tr><td>北京</td><td>100.1</td><td>101.0</td><td>99.9</td></tr>
        <tr><td>武汉</td><td>99.8</td><td>95.2</td><td>97.1</td></tr>
      </table>
      <p>2025年1月70个大中城市二手住宅销售价格指数</p>
      <table>
        <tr><th>城市</th><th>环比</th><th>同比</th><th>定基</th></tr>
        <tr><td>北京</td><td>99.9</td><td>96.2</td><td>94.0</td></tr>
        <tr><td>武汉</td><td>99.3</td><td>93.1</td><td>92.6</td></tr>
      </table>
      <p>2025年1月70个大中城市新建商品住宅销售价格分类指数</p>
      <table>
        <tr><th>城市</th><th>分类</th><th>环比</th></tr>
        <tr><td>武汉</td><td>90平方米及以下</td><td>100.0</td></tr>
      </table>
    </div>
  </body>
</html>
""".encode("utf-8")


@unittest.skipUnless(fetch_data.DEPS_AVAILABLE, fetch_data.DEPS_ERROR or "缺少依赖")
class FetchDataTests(unittest.TestCase):
    def test_normalize_metric_name(self):
        self.assertEqual(fetch_data.normalize_metric_name("MoM"), "环比")
        self.assertEqual(fetch_data.normalize_metric_name("同比指数"), "同比")
        self.assertEqual(fetch_data.normalize_metric_name("fixed-base"), "定基")
        self.assertEqual(fetch_data.normalize_metric_name("1-6月平均"), "累计平均")
        self.assertIsNone(fetch_data.normalize_metric_name("unknown"))

    def test_normalize_city_name(self):
        self.assertEqual(fetch_data.normalize_city_name(" 北京市 "), "北京")
        self.assertEqual(fetch_data.normalize_city_name("呼和浩特市"), "呼和浩特")
        self.assertEqual(fetch_data.normalize_city_name("武 汉"), "武汉")
        self.assertEqual(fetch_data.normalize_city_name("不存在的城市"), "不存在的城市")

    def test_parse_page_extracts_target_city_records(self):
        records = fetch_data.parse_page(
            SAMPLE_HTML,
            "2025-01",
            "武汉",
            ["环比", "同比", "定基"],
            source_url="https://example.com/page",
        )

        self.assertEqual(len(records), 2)
        indicators = {record["indicator"] for record in records}
        self.assertEqual(indicators, {INDICATORS["new"], INDICATORS["used"]})
        self.assertTrue(all(record["city"] == "武汉" for record in records))

        new_record = next(record for record in records if record["indicator"] == INDICATORS["new"])
        used_record = next(record for record in records if record["indicator"] == INDICATORS["used"])
        self.assertEqual(new_record["metrics"]["环比"], 99.8)
        self.assertEqual(used_record["metrics"]["同比"], 93.1)

    def test_build_chart_series_aligns_missing_values(self):
        records = [
            {
                "period": "2025-01",
                "city": "北京",
                "indicator": INDICATORS["new"],
                "metrics": {"环比": 100.1, "同比": 101.0},
                "source_url": "https://example.com/1",
            },
            {
                "period": "2025-02",
                "city": "北京",
                "indicator": INDICATORS["new"],
                "metrics": {"环比": 100.2, "同比": 100.5},
                "source_url": "https://example.com/2",
            },
            {
                "period": "2025-02",
                "city": "北京",
                "indicator": INDICATORS["used"],
                "metrics": {"环比": 99.8, "同比": 98.8},
                "source_url": "https://example.com/2",
            },
        ]

        chart_data = fetch_data.build_chart_series(records)
        self.assertEqual(chart_data["periods"], ["2025-01", "2025-02"])
        self.assertEqual(chart_data["series"][INDICATORS["new"]]["同比"], [101.0, 100.5])
        self.assertEqual(chart_data["series"][INDICATORS["used"]]["同比"], [None, 98.8])
        self.assertAlmostEqual(chart_data["gap"][1], 1.7)
        self.assertIsNone(chart_data["gap"][0])


@unittest.skipUnless(fetch_data.DEPS_AVAILABLE, fetch_data.DEPS_ERROR or "缺少依赖")
class FetchUrlRetryTests(unittest.TestCase):
    def _http_error(self, status_code: int):
        error = Exception(f"{status_code} Client Error")
        response = mock.Mock()
        response.status_code = status_code
        error.response = response
        return error

    def test_fetch_url_4xx_fails_fast_without_retry(self):
        with mock.patch.object(fetch_data, "_cache", None):
            with mock.patch("requests.get", side_effect=self._http_error(404)) as get_mock:
                with self.assertRaises(NetworkError) as ctx:
                    fetch_data.fetch_url("https://example.com/missing")

        self.assertEqual(get_mock.call_count, 1)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_fetch_url_retries_on_5xx(self):
        with mock.patch.object(fetch_data, "_cache", None):
            with mock.patch("requests.get", side_effect=self._http_error(500)) as get_mock:
                with mock.patch("time.sleep"):
                    with self.assertRaises(NetworkError):
                        fetch_data.fetch_url("https://example.com/error")

        self.assertEqual(get_mock.call_count, fetch_data.REQUEST_CONFIG["max_attempts"])


@unittest.skipUnless(fetch_data.DEPS_AVAILABLE, fetch_data.DEPS_ERROR or "缺少依赖")
class EdgeCaseTests(unittest.TestCase):
    def test_parse_number_boundaries(self):
        self.assertIsNone(fetch_data.parse_number("-"))
        self.assertIsNone(fetch_data.parse_number("--"))
        self.assertIsNone(fetch_data.parse_number(""))
        self.assertIsNone(fetch_data.parse_number("无法解析"))
        self.assertEqual(fetch_data.parse_number("1,234.5"), 1234.5)
        self.assertEqual(fetch_data.parse_number("1，234.5"), 1234.5)
        self.assertEqual(fetch_data.parse_number("99.9%"), 99.9)
        self.assertEqual(fetch_data.parse_number("-18.0"), -18.0)

    def test_parse_period_variants(self):
        self.assertEqual(fetch_data.parse_period("2025年12月份70个大中城市商品住宅销售价格变动情况"), "2025-12")
        self.assertEqual(fetch_data.parse_period("2025年1月70个大中城市商品住宅销售价格变动情况"), "2025-01")
        self.assertEqual(fetch_data.parse_period("2025 年 12 月 份"), "2025-12")
        self.assertIsNone(fetch_data.parse_period("标题中没有期次"))

    def test_validate_params_error_branches(self):
        _, _, error = fetch_data.validate_params("不存在的城", ["环比"], 10)
        self.assertIn("未在70个大中城市列表中", error)

        _, _, error = fetch_data.validate_params("北京", ["无效指标"], 10)
        self.assertIn("无效指标", error)

        _, _, error = fetch_data.validate_params("北京", [], 10)
        self.assertIn("至少需要一个有效指标", error)

        _, _, error = fetch_data.validate_params("北京", ["环比"], 0)
        self.assertIn("limit", error)

    def test_cli_invalid_city_returns_json_error_offline(self):
        # 参数校验发生在任何网络请求之前，离线可端到端测试
        script = Path(__file__).resolve().parents[1] / "scripts" / "fetch_data.py"
        result = subprocess.run(
            [sys.executable, str(script), "--city", "不存在的城", "--metrics", "环比"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertIn("error", payload)
        self.assertIn("hint", payload)


if __name__ == "__main__":
    unittest.main()
