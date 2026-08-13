#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_pbc.py - 抓取央行个人住房贷款加权平均利率（季度序列）

数据源：https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/125838/5470606/index.html
栏目为静态列表（2024Q3 起，栏目新建较晚；更早历史需从货币政策执行报告补采）。
详情页正则提取「个人住房贷款加权平均利率为X.XX%」。

使用 --from-reports 可从货币政策执行报告列表页补采 2022Q4 起的利率历史
（2024Q1-Q2 仅存于 PDF 正文，HTML 摘要不可提取）。

说明：住户中长期贷款、M2/社融目前央行站点为动态加载页面，无静态列表可抓，
按 SKILL.md 兜底规则用 WebSearch 处理；本脚本只覆盖可静态解析的利率序列。

用法：
  python fetch_pbc.py [--output FILE]
  python fetch_pbc.py --from-reports [--output FILE]    # 补采历史利率
  python fetch_pbc.py --listing-html FILE --detail-html FILE --period 2026-Q2  # 离线

输出：JSON 格式数据到 stdout（或 --output 文件）
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

try:
    import requests  # noqa: F401 - 真实依赖：fetch_data.fetch_url 经 requests 抓取

    DEPS_AVAILABLE = True
    DEPS_ERROR = None
except ImportError as _exc:  # pragma: no cover - 依赖缺失环境
    requests = None
    DEPS_AVAILABLE = False
    DEPS_ERROR = f"缺少依赖包（{_exc}），请运行: pip install -r requirements.txt"

import fetch_data
from exceptions import NetworkError

PBC_RATE_URL = "https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/125838/5470606/index.html"

# 货币政策执行报告
PBC_REPORT_LIST = "https://www.pbc.gov.cn/zhengcehuobisi/125207/125227/125957/index.html"
REPORT_TITLE_KEY = "中国货币政策执行报告"
REPORT_PERIOD_RE = re.compile(r"(\d{4})\s*年\s*第\s*([一二三四1234])\s*季度")
REPORT_RATE_RE = re.compile(r"(?:个人住房贷款加权平均利率(?:分别)?为|住房贷款利率平均为)\s*(\d+(?:\.\d+)?)\s*[%％]")

RATE_LISTING_TITLE_KEY = "个人住房贷款加权平均利率"
QUARTER_RE = re.compile(r"(\d{4})\s*年\s*第\s*([一二三四1234])\s*季度")
RATE_VALUE_RE = re.compile(r"个人住房贷款加权平均利率为\s*(\d+(?:\.\d+)?)\s*[%％]")
PUBDATE_RE = re.compile(r'<meta[^>]*name="PubDate"[^>]*content="(\d{4})-(\d{1,2})-(\d{1,2})"', re.IGNORECASE)
DATE_RE = re.compile(r"(\d{4})\s*[-年/]\s*(\d{1,2})\s*[-月/]\s*(\d{1,2})")


def _valid_date(year: int, month: int, day: int) -> Optional[str]:
    """月/日范围校验，非法返回 None。"""
    import datetime as _dt

    try:
        _dt.date(year, month, day)
    except ValueError:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


QUARTER_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "1": 1, "2": 2, "3": 3, "4": 4}


def parse_quarter_period(title: str) -> Optional[str]:
    """「2026年第二季度全国新发放...」-> 2026-Q2。"""
    match = QUARTER_RE.search(title)
    if not match:
        return None
    year = int(match.group(1))
    quarter = QUARTER_NUM.get(match.group(2))
    if not quarter:
        return None
    return f"{year}-Q{quarter}"


def parse_rate_listing(html_bytes: bytes) -> List[Dict[str, str]]:
    """解析栏目列表页，返回 [{period, title, article_url}]（按期次升序）。

    栏目内链接前缀不完整（站点改版残留），按 href 尾部
    「{article_id}/index.html」与栏目基址重建完整 URL。
    """
    text = html_bytes.decode("utf-8", errors="ignore")
    base_dir = PBC_RATE_URL.rsplit("/", 1)[0]
    entries: Dict[str, Dict[str, str]] = {}

    for match in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*\stitle="([^"]*)"', text):
        href, title = match.group(1), match.group(2)
        if RATE_LISTING_TITLE_KEY not in title:
            continue

        period = parse_quarter_period(title)
        if not period:
            continue

        tail = re.search(r"/([^/]+)/index\.html$", href)
        if not tail:
            continue
        article_url = f"{base_dir}/{tail.group(1)}/index.html"
        entries.setdefault(period, {
            "period": period,
            "title": " ".join(title.split()),
            "article_url": article_url,
        })

    return [entries[period] for period in sorted(entries)]


def parse_rate_detail(html_bytes: bytes) -> Dict[str, object]:
    """解析公告详情页，返回 {rate, date, warnings}。"""
    text = fetch_data.normalize(re.sub(r"<[^>]+>", " ", html_bytes.decode("utf-8", errors="ignore")))
    warnings: List[str] = []

    rate_match = RATE_VALUE_RE.search(text)
    if not rate_match:
        warnings.append("未能解析加权平均利率数值")

    # 公告日期：页面 meta PubDate 优先；正文没有「年月日」可读格式，
    # 此前仅用年月日正则导致全期次 date 为空
    date = None
    raw_text = html_bytes.decode("utf-8", errors="ignore")
    pubdate_match = PUBDATE_RE.search(raw_text)
    if pubdate_match:
        date = _valid_date(*(int(pubdate_match.group(i)) for i in (1, 2, 3)))
    if date is None:
        date_match = DATE_RE.search(text)
        if date_match:
            date = _valid_date(*(int(date_match.group(i)) for i in (1, 2, 3)))
    if date is None:
        warnings.append("未能解析公告日期（meta PubDate 与正文均未命中）")

    return {
        "rate": float(rate_match.group(1)) if rate_match else None,
        "date": date,
        "warnings": warnings,
    }


def build_output(records: List[dict], warnings: List[str]) -> dict:
    """..."""
    periods = [record["period"] for record in records]
    return {
        "source_url": PBC_RATE_URL,
        "series_id": "rate_房贷加权",
        "frequency": "quarterly",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "period_count": len(records),
        "period_range": {"first": periods[0], "last": periods[-1]} if periods else None,
        "warnings": warnings,
        "records": records,
    }


def parse_report_listing(html_bytes: bytes) -> Dict[str, Dict[str, str]]:
    """解析货币政策执行报告列表页，返回 {period: {title, url, article_id}}。

    href 前缀残缺（站点改版残留），按路径中「125957/」后的部分重建。
    """
    text = html_bytes.decode("utf-8", errors="ignore")
    base_dir = PBC_REPORT_LIST.rsplit("/", 1)[0]
    entries: Dict[str, Dict[str, str]] = {}

    for match in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*\stitle="([^"]*)"', text):
        href, title = match.group(1), match.group(2)
        if REPORT_TITLE_KEY not in title or "简介" in title:
            continue

        period_match = REPORT_PERIOD_RE.search(title)
        if not period_match:
            continue
        year = int(period_match.group(1))
        quarter = QUARTER_NUM.get(period_match.group(2))
        if not quarter:
            continue
        period = f"{year}-Q{quarter}"

        # 重建 URL：截取「125957/」后的路径部分
        if "125957/" in href:
            relative = href.split("125957/", 1)[1]
            url = f"{base_dir}/{relative}"
        elif href.startswith("/"):
            scheme_host = re.match(r"(https?://[^/]+)", PBC_REPORT_LIST).group(1)
            url = f"{scheme_host}{href}"
        elif href.startswith("http"):
            url = href
        else:
            # 取最后一段作为 article_id
            article_id = href.rstrip("/").rsplit("/", 1)[-1]
            url = f"{base_dir}/{article_id}/index.html"

        entries.setdefault(period, {"period": period, "title": " ".join(title.split()), "url": url})

    return entries


def parse_report_rate(html_bytes: bytes) -> Dict[str, object]:
    """从货币政策执行报告摘要页提取个人住房贷款加权平均利率。"""
    text = fetch_data.normalize(re.sub(r"<[^>]+>", " ", html_bytes.decode("utf-8", errors="ignore")))
    rate_match = REPORT_RATE_RE.search(text)
    if not rate_match:
        return {"rate": None, "warnings": ["未能解析个人住房贷款加权平均利率"]}
    return {"rate": float(rate_match.group(1)), "warnings": []}


def main() -> None:
    if not DEPS_AVAILABLE:
        print(json.dumps({"error": DEPS_ERROR}, ensure_ascii=False))
        sys.exit(1)

    parser = argparse.ArgumentParser(description="抓取央行个人住房贷款加权平均利率季度序列")
    parser.add_argument("--output", type=str, default=None, help="输出文件路径（默认 stdout）")
    offline_group = parser.add_mutually_exclusive_group()
    offline_group.add_argument("--listing-html", type=str, default=None, help="离线模式：列表页 HTML 文件（仍在线抓详情页）")
    offline_group.add_argument("--detail-html", type=str, default=None, help="离线模式：详情页 HTML 文件（配合 --period）")
    parser.add_argument("--period", type=str, default=None, help="离线详情页的期次（格式 YYYY-Q[1-4]）")
    parser.add_argument("--from-reports", action="store_true", help="从货币政策执行报告补采历史利率（2022Q4 起 HTML 可提取）")
    parser.add_argument("--report-listing-html", type=str, default=None, help="离线模式：报告列表页 HTML 文件")
    parser.add_argument("--no-cache", action="store_true", help="禁用缓存")
    args = parser.parse_args()

    if args.period and not re.match(r"^\d{4}-Q[1-4]$", args.period):
        print(json.dumps({"error": f"--period 格式应为 YYYY-Q[1-4]: {args.period}"}, ensure_ascii=False))
        sys.exit(1)

    if args.no_cache:
        fetch_data._cache = None

    warnings: List[str] = []
    records: List[dict] = []

    if args.from_reports:
        try:
            if args.report_listing_html:
                listing_path = Path(args.report_listing_html).expanduser()
                if not listing_path.exists():
                    print(json.dumps({"error": f"报告列表页文件不存在: {listing_path}"}, ensure_ascii=False))
                    sys.exit(1)
                content = listing_path.read_bytes()
            else:
                content = fetch_data.fetch_url(PBC_REPORT_LIST)
            entries = parse_report_listing(content)
        except NetworkError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
            sys.exit(1)

        for period in sorted(entries):
            y, q = int(period[:4]), int(period[-1])
            if y < 2022 or (y == 2022 and q < 4):
                continue
            entry = entries[period]
            try:
                content = fetch_data.fetch_url(entry["url"], cache_permanent=True)
            except NetworkError as exc:
                warnings.append(f"{period} 报告抓取失败: {exc}")
                records.append({"period": period, "date": None, "rate": None, "source_url": entry["url"]})
                continue
            parsed = parse_report_rate(content)
            warnings.extend(f"{period}: {warning}" for warning in parsed.pop("warnings"))
            records.append({"period": period, "date": None, "rate": parsed["rate"], "source_url": entry["url"]})

    elif args.detail_html:
        detail_path = Path(args.detail_html).expanduser()
        if not detail_path.exists():
            print(json.dumps({"error": f"详情页文件不存在: {detail_path}"}, ensure_ascii=False))
            sys.exit(1)
        if not args.period:
            print(json.dumps({"error": "离线模式需同时指定 --period（如 2026-Q2）"}, ensure_ascii=False))
            sys.exit(1)
        parsed = parse_rate_detail(detail_path.read_bytes())
        warnings.extend(parsed.pop("warnings"))
        records = [{
            "period": args.period,
            "date": parsed["date"],
            "rate": parsed["rate"],
            "source_url": "",
            "input_file": str(detail_path),
        }]
    else:
        try:
            if args.listing_html:
                listing_path = Path(args.listing_html).expanduser()
                if not listing_path.exists():
                    print(json.dumps({"error": f"列表页文件不存在: {listing_path}"}, ensure_ascii=False))
                    sys.exit(1)
                entries = parse_rate_listing(listing_path.read_bytes())
            else:
                entries = parse_rate_listing(fetch_data.fetch_url(PBC_RATE_URL))
        except NetworkError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
            sys.exit(1)

        if not entries:
            warnings.append("列表页未解析到任何利率公告（页面结构可能变化）")

        for entry in entries:
            try:
                content = fetch_data.fetch_url(entry["article_url"], cache_permanent=True)
            except NetworkError as exc:
                warnings.append(f"{entry['period']} 详情页抓取失败: {exc}")
                records.append({
                    "period": entry["period"],
                    "date": None,
                    "rate": None,
                    "source_url": entry["article_url"],
                })
                continue

            parsed = parse_rate_detail(content)
            warnings.extend(f"{entry['period']}: {warning}" for warning in parsed.pop("warnings"))
            records.append({
                "period": entry["period"],
                "date": parsed["date"],
                "rate": parsed["rate"],
                "source_url": entry["article_url"],
            })

    output = build_output(records, warnings)
    payload = json.dumps(output, ensure_ascii=False, indent=2)

    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
        print(json.dumps({
            "output": str(output_path),
            "period_count": len(records),
        }, ensure_ascii=False))
    else:
        print(payload)


if __name__ == "__main__":
    main()
