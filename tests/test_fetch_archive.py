import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import fetch_archive  # noqa: E402
import fetch_data  # noqa: E402
from exceptions import NetworkError  # noqa: E402


# 真实页面结构：导航区锚点带 title 属性且在列表之前，若跨块配对会错吃列表项的日期
ARCHIVE_HTML = """
<html><body>
<div class="nav">
  <a href="https://www.stats.gov.cn/znwd/" title='AI问'>AI问</a>
</div>
<div class="list-content"><ul>
  <li>
    <a class="fl pc_1600" href="./202302/t20230203_1901390.html" target="_blank" title='2022年1月份70个大中城市商品住宅销售价格变动情况'>
      2022年1月份70个大中城市商品住宅销售价格变动情况
    </a>
    <a class="fl mhide pc1200" href="./202302/t20230203_1901390.html" target="_blank" title='2022年1月份70个大中城市商品住宅销售价格变动情况'>dup</a>
    <span>
      2022-02-21
    </span>
  </li>
  <li class="odd">
    <a href='./202302/t20230203_1901367.html' title='2022年1月份居民消费价格同比上涨0.9%'>价格</a>
    <span class="fr">2022-02-16</span>
  </li>
  <li>
    <a href="./no-date-item.html" title='没有日期的条目'>无日期</a>
  </li>
</ul></div>
</body></html>
""".encode("utf-8")

URL_BRANCH_HTML = """
<html><body><ul>
  <li><a href="https://other.example.cn/a.html" title="2023年1月份70个大中城市商品住宅销售价格变动情况">绝对</a><span>2023-02-15</span></li>
  <li><a href="/sj/zxfb/b.html" title="2023年2月份70个大中城市商品住宅销售价格变动情况">根路径</a><span>2023-03-16</span></li>
  <li><a href="c.html" title="2023年3月份70个大中城市商品住宅销售价格变动情况">裸相对</a><span>2023-04-18</span></li>
</ul></body></html>
""".encode("utf-8")


def make_listing_page(periods):
    """构造只含价格指数条目的归档页 HTML。"""
    items = []
    for i, period in enumerate(periods):
        year, month = period.split("-")
        pub_date = f"{year}-{int(month) + 1 if int(month) < 12 else 1:02d}-15"
        items.append(
            f"<li><a href='./{i}.html' title='{year}年{int(month)}月份70个大中城市商品住宅销售价格变动情况'>t</a>"
            f"<span>{pub_date}</span></li>"
        )
    return ("<html><body><ul>" + "".join(items) + "</ul></body></html>").encode("utf-8")


class ArchiveParsingTests(unittest.TestCase):
    def test_parse_archive_page_pairs_within_li_blocks(self):
        items = fetch_archive.parse_archive_page(ARCHIVE_HTML)

        self.assertEqual(len(items), 2)  # 无日期的 li 被跳过
        first = items[0]
        # 回归点：导航锚点不得吃掉列表项的日期 span
        self.assertEqual(first["title"], "2022年1月份70个大中城市商品住宅销售价格变动情况")
        self.assertEqual(first["date"], "2022-02-21")
        self.assertEqual(first["url"], "https://www.stats.gov.cn/sj/zxfb/202302/t20230203_1901390.html")

    def test_parse_archive_page_handles_li_and_span_attributes(self):
        items = fetch_archive.parse_archive_page(ARCHIVE_HTML)
        second = next(i for i in items if "消费价格" in i["title"])
        # <li class="odd"> 与 <span class="fr"> 均需兼容
        self.assertEqual(second["date"], "2022-02-16")
        self.assertTrue(second["url"].endswith("/202302/t20230203_1901367.html"))

    def test_parse_archive_page_url_branches(self):
        items = fetch_archive.parse_archive_page(URL_BRANCH_HTML)
        by_month = {item["title"][5:7]: item for item in items}  # 「月份」前两位 = 01/02/03
        self.assertEqual(by_month["1月"]["url"], "https://other.example.cn/a.html")
        self.assertEqual(by_month["2月"]["url"], "https://www.stats.gov.cn/sj/zxfb/b.html")
        self.assertEqual(by_month["3月"]["url"], "https://www.stats.gov.cn/sj/zxfb/c.html")

    def test_archive_page_url_numbering(self):
        self.assertEqual(fetch_archive.archive_page_url(0), "https://www.stats.gov.cn/sj/zxfb/index.html")
        self.assertEqual(fetch_archive.archive_page_url(5), "https://www.stats.gov.cn/sj/zxfb/index_5.html")


class CollectTargetEntriesTests(unittest.TestCase):
    def _run(self, pages, since="2023-01", until="2023-12", max_pages=10):
        warnings = []
        url_to_page = {fetch_archive.archive_page_url(i): page for i, page in enumerate(pages)}

        def fetch(url, **kwargs):
            if url not in url_to_page:
                raise NetworkError("404", url=url, status_code=404)
            return url_to_page[url]

        with mock.patch.object(fetch_data, "fetch_url", side_effect=fetch):
            entries = fetch_archive.collect_target_entries(since, until, max_pages, warnings)
        return entries, warnings

    def test_filters_period_range_and_title(self):
        pages = [make_listing_page(["2023-06", "2023-05"])]
        entries, warnings = self._run(pages, since="2023-05", until="2023-05")
        self.assertEqual(list(entries), ["2023-05"])

    def test_stops_when_page_older_than_since(self):
        pages = [
            make_listing_page(["2023-06"]),
            make_listing_page(["2023-05"]),
            make_listing_page(["2022-12"]),  # 整页早于 since -> 应在此停止
            make_listing_page(["2022-11"]),  # 不应被访问
        ]
        warnings = []
        url_to_page = {fetch_archive.archive_page_url(i): page for i, page in enumerate(pages)}
        visited = []

        def fetch(url, **kwargs):
            visited.append(url)
            if url not in url_to_page:
                raise NetworkError("404", url=url, status_code=404)
            return url_to_page[url]

        with mock.patch.object(fetch_data, "fetch_url", side_effect=fetch):
            entries = fetch_archive.collect_target_entries("2023-01", "2023-12", 10, warnings)

        self.assertEqual(sorted(entries), ["2023-05", "2023-06"])
        self.assertEqual(len(visited), 3)  # 第 4 页不应被访问
        self.assertEqual(warnings, [])

    def test_dedupes_period_across_pages(self):
        pages = [make_listing_page(["2023-06"]), make_listing_page(["2023-06"])]
        entries, warnings = self._run(pages)
        self.assertEqual(list(entries), ["2023-06"])

    def test_max_pages_exhaustion_warns(self):
        pages = [make_listing_page(["2023-06"]), make_listing_page(["2023-05"])]
        entries, warnings = self._run(pages, max_pages=2)
        self.assertTrue(any("max-pages" in warning for warning in warnings))

    def test_fetch_failure_warns_and_stops(self):
        warnings = []

        def fetch(url, **kwargs):
            raise NetworkError("boom", url=url)

        with mock.patch.object(fetch_data, "fetch_url", side_effect=fetch):
            entries = fetch_archive.collect_target_entries("2023-01", "2023-12", 3, warnings)

        self.assertEqual(entries, {})
        self.assertTrue(any("抓取失败" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
