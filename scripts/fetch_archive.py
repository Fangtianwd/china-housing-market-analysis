#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_archive.py - 从统计局归档页回溯 RSS 滚动窗口之外的 70 城价格指数期次

数据源：https://www.stats.gov.cn/sj/zxfb/ 分页归档（index.html, index_1.html...，
实测 67 页，最早公告约 2021-09-15（对应期次 2021-08））。RSS 窗口（约最近 30 期）之外的期次滚出后不再
出现在 RSS，本脚本逐页扫描归档，找到「70个大中城市商品住宅销售价格变动情况」
公告并用与 validate_full_data 相同的解析器产出数据集，供 history_store.py 沉淀。

已知缺口：2020-01 至 2021-07 超出归档覆盖（归档最早公告约 2021-09-15，对应期次 2021-08），
需 data.stats.gov.cn 在线查询或人工补采
（见 references/DATA_SOURCES.md）。

用法：
  python fetch_archive.py                          # 默认回溯 2021-08 至 2023-12
  python fetch_archive.py --since 2022-01 --until 2022-12
  python fetch_archive.py --output artifacts/archive-dataset.json

输出：与 validate_full_data --dataset-output 相同结构的数据集 JSON。
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import requests  # noqa: F401 - 真实依赖：fetch_data.fetch_url 经 requests 抓取

    DEPS_AVAILABLE = True
    DEPS_ERROR = None
except ImportError as _exc:  # pragma: no cover - 依赖缺失环境
    requests = None
    DEPS_AVAILABLE = False
    DEPS_ERROR = f"缺少依赖包（{_exc}），请运行: pip install -r requirements.txt"

import fetch_data
import validate_full_data
from config import TITLE_KEY
from exceptions import NetworkError

ARCHIVE_BASE = "https://www.stats.gov.cn/sj/zxfb/"
# 列表项按 <li> 块提取，避免导航锚点跨块与日期 span 错配
LI_BLOCK_RE = re.compile(r"<li[^>]*>(?:(?!</li>).)*?</li>", re.DOTALL)
ANCHOR_RE = re.compile(r"<a[^>]*href=['\"]([^'\"]+)['\"][^>]*title=['\"]([^'\"]*)['\"]")
DATE_SPAN_RE = re.compile(r"<span[^>]*>\s*(\d{4}-\d{2}-\d{2})\s*</span>")


def archive_page_url(page_index: int) -> str:
    if page_index <= 0:
        return f"{ARCHIVE_BASE}index.html"
    return f"{ARCHIVE_BASE}index_{page_index}.html"


def parse_archive_page(html_bytes: bytes) -> List[Dict[str, str]]:
    """解析归档列表页，返回 [{date, title, url}]（绝对 URL）。

    每个 <li> 内有 PC/移动等多份锚点副本，取第一份带 title 的锚点与该块
    内的日期 span 配对；跨块配对会导致导航锚点错配，故严格按块提取。
    """
    text = html_bytes.decode("utf-8", errors="ignore")
    base_dir = ARCHIVE_BASE.rstrip("/")
    scheme_host = re.match(r"(https?://[^/]+)", ARCHIVE_BASE).group(1)
    items = []

    for block_match in LI_BLOCK_RE.finditer(text):
        block = block_match.group(0)
        anchor_match = ANCHOR_RE.search(block)
        date_match = DATE_SPAN_RE.search(block)
        if not anchor_match or not date_match:
            continue

        href, title = anchor_match.group(1), anchor_match.group(2)
        title = fetch_data.normalize(title)
        if href.startswith("http"):
            url = href
        elif href.startswith("./"):
            url = f"{base_dir}/{href[2:]}"
        elif href.startswith("/"):
            url = f"{scheme_host}{href}"
        else:
            url = f"{base_dir}/{href}"
        items.append({"date": date_match.group(1), "title": title, "url": url})

    return items


def collect_target_entries(
    since: str, until: str, max_pages: int, warnings: List[str]
) -> Dict[str, Dict[str, str]]:
    """逐页扫描归档，收集期次在 [since, until] 内的价格指数公告。

    归档按期次降序排列；整页最新日期早于 since 时停止。按期次去重。
    """
    entries: Dict[str, Dict[str, str]] = {}
    since_month = since[:7]
    until_month = until[:7]

    for page_index in range(max_pages):
        page_url = archive_page_url(page_index)
        try:
            content = fetch_data.fetch_url(page_url)
        except NetworkError as exc:
            warnings.append(f"归档页第 {page_index} 页抓取失败: {exc}")
            break

        items = parse_archive_page(content)
        if not items:
            warnings.append(f"归档页第 {page_index} 页无列表项，停止扫描")
            break

        if max(item["date"] for item in items) < since_month + "-01":
            break

        for item in items:
            if TITLE_KEY not in item["title"]:
                continue
            period = fetch_data.parse_period(item["title"])
            if not period:
                warnings.append(f"归档条目无法解析期次: {item['title']}")
                continue
            if since_month <= period <= until_month:
                entries.setdefault(period, item)
    else:
        warnings.append(
            f"已达 max-pages={max_pages} 上限但未触及停止条件，更早期次未扫描；"
            "如需更早数据请增大 --max-pages"
        )

    return entries


def main() -> None:
    if not DEPS_AVAILABLE:
        print(json.dumps({"error": DEPS_ERROR}, ensure_ascii=False))
        sys.exit(1)

    parser = argparse.ArgumentParser(description="从统计局归档页回溯 RSS 窗口外的 70 城价格指数期次")
    parser.add_argument("--since", default="2021-08", help="起始期次 YYYY-MM（默认 2021-08，归档可覆盖的最早期次）")
    parser.add_argument("--until", default="2023-12", help="结束期次 YYYY-MM（默认 2023-12，RSS 窗口起点前）")
    parser.add_argument("--max-pages", type=int, default=70, help="最多扫描归档页数（默认 70）")
    parser.add_argument("--output", default=None, help="数据集输出路径（默认 stdout 摘要 + artifacts/archive-dataset.json）")
    parser.add_argument("--no-cache", action="store_true", help="禁用缓存")
    args = parser.parse_args()

    period_re = re.compile(r"^\d{4}-\d{2}$")
    if not period_re.match(args.since) or not period_re.match(args.until):
        print(json.dumps({"error": f"--since/--until 格式应为 YYYY-MM: {args.since} / {args.until}"}, ensure_ascii=False))
        sys.exit(1)
    if args.since > args.until:
        print(json.dumps({"error": f"--since 晚于 --until: {args.since} > {args.until}"}, ensure_ascii=False))
        sys.exit(1)

    if args.no_cache:
        fetch_data._cache = None

    warnings: List[str] = []
    entries = collect_target_entries(args.since, args.until, args.max_pages, warnings)

    all_records: List[dict] = []
    fetch_failures: List[dict] = []
    pages_ok = 0

    for period in sorted(entries):
        entry = entries[period]
        try:
            content = fetch_data.fetch_url(entry["url"], cache_permanent=True)
        except NetworkError as exc:
            fetch_failures.append({"period": period, "source_url": entry["url"], "error": str(exc)})
            continue

        records = validate_full_data.parse_full_page(content, period, entry["url"])
        for record in records:
            issues = validate_full_data.validate_record_schema(record)
            if issues:
                warnings.append(f"{period} 记录 schema 问题: {issues[:3]}")
        if len(records) < len(validate_full_data.TARGET_INDICATORS) * 35:
            warnings.append(f"{period} 记录数偏少（{len(records)}），旧页面结构可能不同，请人工抽查")
        all_records.extend(records)
        pages_ok += 1

    periods = sorted({record["period"] for record in all_records})
    dataset = {
        "source": "stats.gov.cn archive backtrack",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "requested_range": {"since": args.since, "until": args.until},
        "pages_fetched": pages_ok,
        "period_range": {"first": periods[0], "last": periods[-1]} if periods else None,
        "latest_period": periods[-1] if periods else None,
        "fetch_failures": fetch_failures,
        "warnings": warnings,
        "record_count": len(all_records),
        "indicators": list(validate_full_data.TARGET_INDICATORS),
        "records": all_records,
    }

    output_path = Path(args.output) if args.output else (
        Path(__file__).resolve().parent.parent / "artifacts" / "archive-dataset.json"
    )
    output_path = output_path.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "output": str(output_path),
        "period_count": len(periods),
        "period_range": dataset["period_range"],
        "record_count": len(all_records),
        "fetch_failures": len(fetch_failures),
        "warnings": warnings,
        "next_step": "python3 scripts/history_store.py --from " + str(output_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
