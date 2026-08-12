#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_dev_stats.py - 抓取国家统计局「全国房地产市场基本情况」开发销售序列

数据源：国家统计局 RSS 中标题含「全国房地产市场基本情况」的公告页。
每期发布累计值与累计同比（投资/施工/新开工/竣工/销售/待售/到位资金，
分东中西部和东北）。注意：官方只发布累计口径，当月同比需差分推导，
且"按可比口径计算"期次基数会被回填修正——本脚本只采集官方发布的
累计值与累计同比，不做差分，避免口径陷阱（见 SKILL.md 口径注意事项）。

用法：
  python fetch_dev_stats.py --latest
  python fetch_dev_stats.py --limit 6
  python fetch_dev_stats.py --html-file page.html          # 离线模式（单页）
  python fetch_dev_stats.py --output artifacts/dev-stats.json

输出：JSON 格式数据到 stdout（或 --output 文件）
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from bs4 import BeautifulSoup

    DEPS_AVAILABLE = True
    DEPS_ERROR = None
except ImportError as _exc:  # pragma: no cover - 依赖缺失环境
    BeautifulSoup = None
    DEPS_AVAILABLE = False
    DEPS_ERROR = f"缺少依赖包（{_exc}），请运行: pip install -r requirements.txt"

import fetch_data
from config import DEV_TITLE_KEY, RSS_URL
from exceptions import NetworkError, RSSFeedError

DEV_PERIOD_RE = re.compile(r"(\d{4})\s*年\s*(?:1\s*[-—–]\s*)?(\d{1,2})\s*月(?:份)?")
DEV_HALFYEAR_RE = re.compile(r"(\d{4})\s*年\s*上半年")
DEV_YEAR_RE = re.compile(r"(\d{4})\s*年")
UNIT_RE = re.compile(r"（(亿元|万平方米)）")
REGION_INVEST_HEADERS = ("投资额", "同比增长")
REGION_SALES_HEADERS = ("销售面积", "销售额")
KNOWN_REGIONS = ("全国总计", "东部地区", "中部地区", "西部地区", "东北地区")


def fetch_dev_rss_items() -> Tuple[List[tuple], List[str]]:
    """获取 RSS 中开发销售公告条目，按期次升序，同期次保留最后一条。

    返回 ([(period, title, url)], warnings)。无法解析期次的条目记入
    warnings，禁止静默丢弃。
    """
    try:
        content = fetch_data.fetch_url(RSS_URL)
        import xml.etree.ElementTree as ET

        root = ET.fromstring(content)
    except Exception as exc:
        raise RSSFeedError(f"RSS 获取失败: {exc}", feed_url=RSS_URL) from exc

    warnings: List[str] = []
    by_period: Dict[str, tuple] = {}
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        if title_el is None or link_el is None:
            continue

        title = fetch_data.normalize(title_el.text or "")
        link = (link_el.text or "").strip()
        if DEV_TITLE_KEY not in title:
            continue

        period = parse_dev_period(title)
        if not period:
            warnings.append(f"RSS 条目无法解析期次，已跳过: {title}")
            continue
        if period in by_period:
            warnings.append(f"RSS 中期次 {period} 重复出现，保留较新链接: {title}")
        by_period[period] = (period, title, link)

    if not by_period:
        raise RSSFeedError("RSS 中未找到开发销售公告条目", feed_url=RSS_URL)

    items = [by_period[period] for period in sorted(by_period)]
    return items, warnings


def parse_dev_period(title: str) -> Optional[str]:
    """从标题提取累计期次终点。

    「2026年1—6月份...」-> 2026-06；「2025年上半年...」-> 2025-06；
    「2025年全国房地产市场基本情况」（全年期，标题无月份）-> 2025-12。
    """
    match = DEV_HALFYEAR_RE.search(title)
    if match:
        return f"{int(match.group(1)):04d}-06"

    match = DEV_PERIOD_RE.search(title)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"

    # 全年期：统计局以「XXXX年全国房地产市场基本情况」发布 12 月累计数据
    if DEV_TITLE_KEY in title:
        year_match = DEV_YEAR_RE.search(title)
        if year_match:
            return f"{int(year_match.group(1)):04d}-12"

    return None


def _number(cell: str) -> Optional[float]:
    return fetch_data.parse_number(cell)


def parse_main_indicator_table(table) -> List[Dict[str, object]]:
    """解析主指标表（指标 | 绝对量 | 同比增长），返回指标记录列表。

    分组规则：含单位（亿元/万平方米）的行为组起点；其后的
    「其中：XXX」或无单位行（办公楼/国内贷款等）为该组的子项。
    """
    records: List[Dict[str, object]] = []
    current_group: Optional[str] = None
    current_unit: Optional[str] = None

    for tr in table.find_all("tr"):
        row = fetch_data.extract_row(tr)
        if not row:
            continue
        name_cell = fetch_data.normalize(row[0])
        if re.match(r"^注[：:]", name_cell):
            # 注记行（常为单格）：显式跳过并终止当前组，防止后续无单位行误归组
            current_group = None
            continue
        if len(row) < 3:
            continue
        if not name_cell or name_cell == "指标":
            continue

        unit_match = UNIT_RE.search(name_cell)
        if unit_match:
            current_group = fetch_data.normalize(name_cell.split("（")[0])
            current_unit = unit_match.group(1)
            sub_item = None
        elif current_group is None:
            continue
        else:
            sub_item = re.sub(r"^其中[：:]", "", name_cell).strip()

        value = _number(row[1])
        yoy = _number(row[2])
        if value is None and yoy is None:
            continue

        records.append({
            "indicator": current_group,
            "sub_item": sub_item,
            "unit": current_unit,
            "value": value,
            "yoy": yoy,
        })

    return records


def _find_region_table(table, header_keywords: tuple) -> bool:
    """判断表格是否为指定类型的分区表（依据前两行表头）。"""
    rows = [fetch_data.extract_row(tr) for tr in table.find_all("tr")[:3]]
    head_text = fetch_data.compact(" ".join(" ".join(row) for row in rows))
    return all(fetch_data.compact(keyword) in head_text for keyword in header_keywords)


def parse_regional_table(table, kind: str) -> List[Dict[str, object]]:
    """解析分区表。kind='invest' -> 投资额/住宅/同比；kind='sales' -> 销售面积/销售额及同比。"""
    records: List[Dict[str, object]] = []
    for tr in table.find_all("tr"):
        row = fetch_data.extract_row(tr)
        if not row:
            continue
        region = fetch_data.normalize(row[0])
        if region not in KNOWN_REGIONS:
            continue

        if kind == "invest" and len(row) >= 5:
            records.append({
                "region": region,
                "value": _number(row[1]),
                "residential": _number(row[2]),
                "yoy": _number(row[3]),
                "residential_yoy": _number(row[4]),
            })
        elif kind == "sales" and len(row) >= 5:
            records.append({
                "region": region,
                "area": _number(row[1]),
                "area_yoy": _number(row[2]),
                "amount": _number(row[3]),
                "amount_yoy": _number(row[4]),
            })
    return records


def parse_dev_page(html_bytes: bytes) -> Dict[str, object]:
    """解析单期开发销售公告页（三张表，每页渲染两遍，自动去重）。"""
    soup = BeautifulSoup(html_bytes, "html.parser")
    tables = soup.find_all("table")

    main_records: List[Dict[str, object]] = []
    regional_invest: List[Dict[str, object]] = []
    regional_sales: List[Dict[str, object]] = []

    for table in tables:
        header_row = fetch_data.extract_row(table.find("tr")) if table.find("tr") else []
        # compact 比较：部分期次表头为「指 标」（字符间含空格）
        if header_row and fetch_data.compact(header_row[0]) == "指标":
            parsed = parse_main_indicator_table(table)
            if len(parsed) > len(main_records):
                main_records = parsed
        elif _find_region_table(table, REGION_INVEST_HEADERS):
            parsed_regions = parse_regional_table(table, "invest")
            if len(parsed_regions) > len(regional_invest):
                regional_invest = parsed_regions
        elif _find_region_table(table, REGION_SALES_HEADERS):
            parsed_regions = parse_regional_table(table, "sales")
            if len(parsed_regions) > len(regional_sales):
                regional_sales = parsed_regions

    return {
        "indicators": main_records,
        "regional_investment": regional_invest,
        "regional_sales": regional_sales,
    }


def to_series_records(parsed: Dict[str, object], period: str, source_url: str) -> List[Dict[str, object]]:
    """将解析结果转为数据契约的长格式记录（命名规则与 SKILL.md 数据契约一致）。"""
    records: List[Dict[str, object]] = []

    for item in parsed["indicators"]:
        base_id = f"dev_{item['indicator']}"
        if item["sub_item"]:
            base_id = f"{base_id}_{item['sub_item']}"
        if item["value"] is not None:
            records.append({
                "series_id": f"{base_id}_累计值",
                "period": period,
                "value": item["value"],
                "unit": item["unit"],
                "source_url": source_url,
            })
        if item["yoy"] is not None:
            records.append({
                "series_id": f"{base_id}_累计同比",
                "period": period,
                "value": item["yoy"],
                "unit": "%",
                "source_url": source_url,
            })

    for item in parsed["regional_investment"]:
        region = item["region"]
        for suffix, value, unit in (
            ("投资额_累计值", item["value"], "亿元"),
            ("投资额_住宅_累计值", item["residential"], "亿元"),
            ("投资额_累计同比", item["yoy"], "%"),
            ("投资额_住宅_累计同比", item["residential_yoy"], "%"),
        ):
            if value is not None:
                records.append({
                    "series_id": f"dev_region_{region}_{suffix}",
                    "period": period,
                    "value": value,
                    "unit": unit,
                    "source_url": source_url,
                })

    for item in parsed["regional_sales"]:
        region = item["region"]
        for suffix, value, unit in (
            ("销售面积_累计值", item["area"], "万平方米"),
            ("销售面积_累计同比", item["area_yoy"], "%"),
            ("销售额_累计值", item["amount"], "亿元"),
            ("销售额_累计同比", item["amount_yoy"], "%"),
        ):
            if value is not None:
                records.append({
                    "series_id": f"dev_region_{region}_{suffix}",
                    "period": period,
                    "value": value,
                    "unit": unit,
                    "source_url": source_url,
                })

    return records


def build_output(
    records: List[Dict[str, object]],
    warnings: List[str],
    periods_fetched: int,
) -> Dict[str, object]:
    periods = sorted({record["period"] for record in records})
    return {
        "source": DEV_TITLE_KEY,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "periods_fetched": periods_fetched,
        "period_count": len(periods),
        "period_range": {"first": periods[0], "last": periods[-1]} if periods else None,
        "warnings": warnings,
        "records": records,
    }


def positive_int(text: str) -> int:
    """argparse 类型校验：正整数。"""
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"必须是整数: {text}") from exc
    if value < 1:
        raise argparse.ArgumentTypeError(f"必须 ≥1: {value}")
    return value


def main() -> None:
    if not DEPS_AVAILABLE:
        print(json.dumps({"error": DEPS_ERROR}, ensure_ascii=False))
        sys.exit(1)

    parser = argparse.ArgumentParser(description="抓取全国房地产市场基本情况（开发销售累计序列）")
    parser.add_argument("--latest", action="store_true", help="只抓最新一期")
    parser.add_argument("--limit", type=positive_int, default=None, help="最多抓取期数（≥1）")
    parser.add_argument("--output", type=str, default=None, help="输出文件路径（默认 stdout）")
    parser.add_argument("--html-file", type=str, default=None, help="离线模式：单页 HTML 文件（需配合 --period）")
    parser.add_argument("--period", type=str, default=None, help="离线模式下的期次 YYYY-MM")
    parser.add_argument("--no-cache", action="store_true", help="禁用缓存")
    args = parser.parse_args()

    if args.no_cache:
        fetch_data._cache = None

    warnings: List[str] = []
    all_records: List[Dict[str, object]] = []
    periods_fetched = 0

    if args.html_file:
        html_path = Path(args.html_file).expanduser()
        if not html_path.exists():
            print(json.dumps({"error": f"HTML 文件不存在: {html_path}"}, ensure_ascii=False))
            sys.exit(1)
        if not args.period:
            print(json.dumps({"error": "离线模式需同时指定 --period YYYY-MM"}, ensure_ascii=False))
            sys.exit(1)
        if not re.match(r"^\d{4}-\d{2}$", args.period):
            print(json.dumps({"error": f"--period 格式应为 YYYY-MM: {args.period}"}, ensure_ascii=False))
            sys.exit(1)
        parsed = parse_dev_page(html_path.read_bytes())
        all_records = to_series_records(parsed, args.period, str(html_path))
        periods_fetched = 1
    else:
        try:
            rss_items, rss_warnings = fetch_dev_rss_items()
        except (RSSFeedError, NetworkError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
            sys.exit(1)
        warnings.extend(rss_warnings)

        selected = rss_items[-1:] if args.latest else (
            rss_items[-args.limit:] if args.limit else rss_items
        )

        for period, title, url in selected:
            try:
                content = fetch_data.fetch_url(url, cache_permanent=True)
            except NetworkError as exc:
                warnings.append(f"{period} 抓取失败: {exc}")
                continue

            parsed = parse_dev_page(content)
            if not parsed["indicators"]:
                warnings.append(f"{period} 主指标表解析为空（页面结构可能变化）")
                continue
            all_records.extend(to_series_records(parsed, period, url))
            periods_fetched += 1

    output = build_output(all_records, warnings, periods_fetched)
    payload = json.dumps(output, ensure_ascii=False, indent=2)

    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
        print(json.dumps({
            "output": str(output_path),
            "period_count": output["period_count"],
            "record_count": len(all_records),
        }, ensure_ascii=False))
    else:
        print(payload)


if __name__ == "__main__":
    main()
