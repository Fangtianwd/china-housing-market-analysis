#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_lpr.py - 抓取中国人民银行 LPR（贷款市场报价利率）全序列

数据源：https://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/3876551/index.html
（2019 年 8 月 LPR 改革以来所有期次；列表页静态 HTML，详情页正则可解析）

用法：
  python fetch_lpr.py [--limit N] [--since YYYY-MM] [--output FILE]
  python fetch_lpr.py --listing-html listing.html --detail-html detail.html   # 离线模式

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
    import requests

    DEPS_AVAILABLE = True
    DEPS_ERROR = None
except ImportError as _exc:  # pragma: no cover - 依赖缺失环境
    requests = None
    DEPS_AVAILABLE = False
    DEPS_ERROR = f"缺少依赖包（{_exc}），请运行: pip install -r requirements.txt"

import fetch_data
from config import LPR_URL, REQUEST_CONFIG
from exceptions import NetworkError

DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
LPR_1Y_RE = re.compile(r"1\s*年\s*期\s*LPR\s*为\s*(\d+(?:\.\d+)?)\s*[%％]")
LPR_5Y_RE = re.compile(r"5\s*年\s*期\s*以\s*上\s*LPR\s*为\s*(\d+(?:\.\d+)?)\s*[%％]")
NEXT_PAGE_RE = re.compile(r'tagname="(/[^"]+?)-2\.html"')
TOTAL_PAGE_RE = re.compile(r'totalpage="(\d+)"')
LISTING_TITLE_KEY = "贷款市场报价利率"


def _normalize_html_text(html_bytes: bytes) -> str:
    """去标签并归一化空白/全角，便于正则提取。"""
    text = html_bytes.decode("utf-8", errors="ignore")
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace(" ", " ").replace("　", " ")
    return " ".join(text.split())


def parse_lpr_listing(html_bytes: bytes, base_url: str) -> List[Dict[str, str]]:
    """解析 LPR 栏目列表页，返回 [{date, period, title, url}]（按日期降序）。"""
    entries = []
    text = html_bytes.decode("utf-8", errors="ignore")
    # href 可能是站点根路径（/zhengcehuobisi/...）或目录相对路径，分别按 origin / 目录拼接
    scheme_host = re.match(r"(https?://[^/]+)", base_url)
    origin = scheme_host.group(1) if scheme_host else ""
    base_dir = base_url.rsplit("/", 1)[0]

    for match in re.finditer(r'<a[^>]*href="([^"]+)"[^>]*\stitle="([^"]*)"', text):
        href, title = match.group(1), match.group(2)
        if LISTING_TITLE_KEY not in title:
            continue
        date_match = DATE_RE.search(title)
        if not date_match:
            continue

        year, month, day = (int(date_match.group(i)) for i in (1, 2, 3))
        if href.startswith("http"):
            url = href
        elif href.startswith("/"):
            url = f"{origin}{href}"
        else:
            url = f"{base_dir}/{href}"
        entries.append({
            "date": f"{year:04d}-{month:02d}-{day:02d}",
            "period": f"{year:04d}-{month:02d}",
            "title": " ".join(title.split()),
            "url": url,
        })

    entries.sort(key=lambda item: item["date"], reverse=True)
    return entries


def parse_lpr_detail(html_bytes: bytes) -> Dict[str, object]:
    """解析 LPR 公告详情页，返回 {date, lpr_1y, lpr_5y, warnings}。"""
    text = _normalize_html_text(html_bytes)
    warnings = []

    date_match = DATE_RE.search(text)
    date = None
    if date_match:
        year, month, day = (int(date_match.group(i)) for i in (1, 2, 3))
        date = f"{year:04d}-{month:02d}-{day:02d}"
    else:
        warnings.append("未能从详情页提取公告日期")

    lpr_1y_match = LPR_1Y_RE.search(text)
    lpr_5y_match = LPR_5Y_RE.search(text)
    if not lpr_1y_match:
        warnings.append("未能解析 1 年期 LPR")
    if not lpr_5y_match:
        warnings.append("未能解析 5 年期以上 LPR")

    return {
        "date": date,
        "lpr_1y": float(lpr_1y_match.group(1)) if lpr_1y_match else None,
        "lpr_5y": float(lpr_5y_match.group(1)) if lpr_5y_match else None,
        "warnings": warnings,
    }


def extract_pagination(html_text: str) -> Tuple[Optional[str], int]:
    """从列表页提取分页 URL 前缀（...-N.html 的 ...- 部分）与总页数。"""
    next_match = NEXT_PAGE_RE.search(html_text)
    total_match = TOTAL_PAGE_RE.search(html_text)
    prefix = next_match.group(1) if next_match else None
    total_pages = int(total_match.group(1)) if total_match else 1
    return prefix, total_pages


def fetch_listing_pages(url: str, until_period: str, max_pages: int = 30) -> List[Dict[str, str]]:
    """抓取列表页及分页，直到条目早于 until_period、分页结束或 404。"""
    entries: List[Dict[str, str]] = []
    scheme_host = re.match(r"(https?://[^/]+)", url)
    origin = scheme_host.group(1) if scheme_host else ""

    content = fetch_data.fetch_url(url)
    page_entries = parse_lpr_listing(content, url)
    entries.extend(page_entries)

    if not page_entries or min(entry["period"] for entry in page_entries) < until_period:
        return entries

    prefix, total_pages = extract_pagination(content.decode("utf-8", errors="ignore"))
    if not prefix:
        return entries

    for page in range(2, min(total_pages, max_pages) + 1):
        # prefix 是站点根路径（/zhengcehuobisi/...），与 origin 拼接
        page_url = f"{origin}{prefix}-{page}.html"
        try:
            content = fetch_data.fetch_url(page_url)
        except NetworkError as exc:
            if exc.status_code == 404 and entries:
                break
            raise

        page_entries = parse_lpr_listing(content, page_url)
        if not page_entries:
            break
        entries.extend(page_entries)
        if min(entry["period"] for entry in page_entries) < until_period:
            break

    return entries


def build_output(
    records: List[Dict[str, object]],
    source_url: str,
    warnings: List[str],
) -> Dict[str, object]:
    """组装统一输出（对齐 full-dataset 风格）。"""
    return {
        "source_url": source_url,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "period_count": len(records),
        "period_range": (
            {"first": records[0]["period"], "last": records[-1]["period"]} if records else None
        ),
        "warnings": warnings,
        "records": records,
    }


def main() -> None:
    if not DEPS_AVAILABLE:
        print(json.dumps({"error": DEPS_ERROR}, ensure_ascii=False))
        sys.exit(1)

    parser = argparse.ArgumentParser(description="抓取央行 LPR 全序列（2019-08 改革以来）")
    parser.add_argument("--url", default=LPR_URL, help=f"列表页 URL（默认: {LPR_URL}）")
    parser.add_argument("--since", default="2019-08", help="起始期次 YYYY-MM（默认: 2019-08）")
    parser.add_argument("--limit", type=int, default=None, help="最多返回期数")
    parser.add_argument("--output", type=str, default=None, help="输出文件路径（默认 stdout）")
    parser.add_argument("--listing-html", type=str, default=None, help="离线模式：列表页 HTML 文件")
    parser.add_argument("--detail-html", type=str, default=None, help="离线模式：单条详情页 HTML 文件（跳过逐页抓取）")
    parser.add_argument("--no-cache", action="store_true", help="禁用缓存")
    args = parser.parse_args()

    if args.no_cache:
        fetch_data._cache = None

    warnings: List[str] = []
    records: List[Dict[str, object]] = []

    if args.detail_html:
        # 离线模式：解析单个详情页（配合测试或本地存档）
        detail_path = Path(args.detail_html).expanduser()
        if not detail_path.exists():
            print(json.dumps({"error": f"详情页文件不存在: {detail_path}"}, ensure_ascii=False))
            sys.exit(1)
        parsed = parse_lpr_detail(detail_path.read_bytes())
        warnings.extend(parsed.pop("warnings"))
        if parsed["date"]:
            parsed["period"] = parsed["date"][:7]
        else:
            parsed["period"] = None
        parsed["source_url"] = str(detail_path)
        records = [parsed]
    else:
        try:
            if args.listing_html:
                listing_path = Path(args.listing_html).expanduser()
                if not listing_path.exists():
                    print(json.dumps({"error": f"列表页文件不存在: {listing_path}"}, ensure_ascii=False))
                    sys.exit(1)
                entries = parse_lpr_listing(listing_path.read_bytes(), args.url)
            else:
                entries = fetch_listing_pages(args.url, until_period=args.since)
        except NetworkError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
            sys.exit(1)

        entries = [entry for entry in entries if entry["period"] >= args.since]
        if args.limit:
            entries = entries[: args.limit]

        # 按期次去重（同月多次公告取最早一条），按期次升序
        by_period: Dict[str, Dict[str, str]] = {}
        for entry in sorted(entries, key=lambda item: item["date"]):
            by_period.setdefault(entry["period"], entry)

        for period in sorted(by_period):
            entry = by_period[period]
            try:
                content = fetch_data.fetch_url(entry["url"])
            except NetworkError as exc:
                warnings.append(f"{period} 详情页抓取失败: {exc}")
                records.append({
                    "period": period,
                    "date": entry["date"],
                    "lpr_1y": None,
                    "lpr_5y": None,
                    "source_url": entry["url"],
                })
                continue

            parsed = parse_lpr_detail(content)
            warnings.extend(f"{period}: {warning}" for warning in parsed.pop("warnings"))
            records.append({
                "period": period,
                "date": parsed["date"] or entry["date"],
                "lpr_1y": parsed["lpr_1y"],
                "lpr_5y": parsed["lpr_5y"],
                "source_url": entry["url"],
            })

    output = build_output(records, args.url, warnings)
    payload = json.dumps(output, ensure_ascii=False, indent=2)

    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload)
        print(json.dumps({"output": str(output_path), "period_count": len(records)}, ensure_ascii=False))
    else:
        print(payload)


if __name__ == "__main__":
    main()
