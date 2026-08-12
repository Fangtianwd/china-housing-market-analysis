import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_policies  # noqa: E402


HOME_HTML = """
<html><body>
<a href="/gongkai/zc/xzgfxwjk/art/2026/art_2063777831.html">住房城乡建设部关于做好住房保障工作的通知</a>
<a href="/gongkai/zc/xzgfxwjk/art/2026/art_2063777831.html">住房城乡建设部关于做好住房保障工作的通知</a>
<a href="/xinwen/jsyw/art/2026/art_41a4475aa5b0477.html">城市更新工作座谈会在上海召开</a>
<a href="/other/page.html">非文章链接不应出现</a>
</body></html>
""".encode("utf-8")


class PolicyScraperTests(unittest.TestCase):
    def test_parse_policy_links_dedupes_and_filters(self):
        links = fetch_policies.parse_policy_links(HOME_HTML)

        self.assertEqual(len(links), 2)
        self.assertTrue(all(link["url"].startswith("https://www.mohurd.gov.cn/") for link in links))
        self.assertIn("住房保障", links[0]["title"])

    def test_tag_keywords(self):
        self.assertEqual(
            fetch_policies.tag_keywords("关于促进房地产市场平稳健康发展的通知"),
            ["房地产"],
        )
        tags = fetch_policies.tag_keywords("保障性住房与公积金支持城市更新")
        self.assertIn("保障性", tags)
        self.assertIn("公积金", tags)
        self.assertIn("城市更新", tags)
        self.assertEqual(fetch_policies.tag_keywords("无关标题"), [])

    def test_parse_policy_detail_date_formats(self):
        html = "<html><body>发布时间：2026-03-25 来源</body></html>".encode("utf-8")
        self.assertEqual(fetch_policies.parse_policy_detail_date(html), "2026-03-25")

        html_cn = "<html><body>发布日期 2026年3月5日</body></html>".encode("utf-8")
        self.assertEqual(fetch_policies.parse_policy_detail_date(html_cn), "2026-03-05")

        self.assertEqual(fetch_policies.parse_policy_detail_date(b"<html></html>"), "")

    def test_build_output_shape(self):
        policies = [
            {"title": "a", "url": "u1", "date": "2026-07-01", "source": "住建部", "keywords": []},
            {"title": "b", "url": "u2", "date": "", "source": "住建部", "keywords": []},
        ]
        output = fetch_policies.build_output(policies, [])
        self.assertEqual(output["policy_count"], 2)
        self.assertEqual(output["date_range"], {"first": "2026-07-01", "last": "2026-07-01"})


if __name__ == "__main__":
    unittest.main()
