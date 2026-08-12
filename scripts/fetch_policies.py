#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_policies.py - 住建部最新政策清单结构化抓取

数据源：住建部首页（服务端渲染，含各栏目最新文章链接）+ 文章详情页（静态，
可提取发布时间）。栏目列表页为 JS 动态加载不可静态抓取，故以首页快照为源。

范围说明：
- 本脚本只覆盖住建部站点；中国政府网政策库直抓返回 403，国务院层面政策
  按 SKILL.md 兜底规则用 WebSearch 补采，不在本脚本范围。
- 首页快照含近期文章与少量置顶旧文，且混有非政策新闻（外事活动等）。
  消费方必须按 date 窗口（近 30 天）与 keywords 非空过滤后使用。

用法：
  python fetch_policies.py [--max-details 15] [--output FILE] [--home-html FILE]

输出：JSON 政策清单（title/url/date/source/keywords）
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

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

MOHURD_HOME = "https://www.mohurd.gov.cn/"
ART_LINK_RE = re.compile(r"<a[^>]*href=\"(/[^\"]*art_[^\"]*\.html)\"[^>]*>([^<]{6,120})</a>")
# 只认「发布时间/发布日期」整词，避免被「截止日期」等其它"…日期"截胡
DETAIL_DATE_RE = re.compile(r"发布(?:时间|日期)[^0-9]{0,12}(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})")
POLICY_KEYWORDS = (
    "房地产", "住房", "保障性", "保障房", "租赁", "公积金", "城市更新",
    "物业", "楼市", "商品房", "预售", "收储", "房贷", "限购", "城中村",
)


def parse_policy_links(html_bytes: bytes) -> List[Dict[str, str]]:
    """从首页提取文章链接（art_*.html），按 URL 去重保留首次出现的标题。"""
    text = html_bytes.decode("utf-8", errors="ignore")
    seen: Dict[str, Dict[str, str]] = {}
    for match in ART_LINK_RE.finditer(text):
        path, title = match.group(1), match.group(2)
        title = fetch_data.normalize(title)
        if path not in seen and title:
            seen[path] = {"title": title, "url": f"{MOHURD_HOME.rstrip('/')}{path}"}
    return list(seen.values())


def tag_keywords(title: str) -> List[str]:
    """按标题打政策关键词标签。"""
    return [keyword for keyword in POLICY_KEYWORDS if keyword in title]


def parse_policy_detail_date(html_bytes: bytes) -> str:
    """从文章详情页提取发布日期（找不到或非法返回空串）。"""
    import datetime as _dt

    text = re.sub(r"<[^>]+>", " ", html_bytes.decode("utf-8", errors="ignore"))
    match = DETAIL_DATE_RE.search(text)
    if not match:
        return ""
    year, month, day = (int(match.group(i)) for i in (1, 2, 3))
    try:
        _dt.date(year, month, day)
    except ValueError:
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def build_output(policies: List[dict], warnings: List[str]) -> dict:
    dates = [policy["date"] for policy in policies if policy.get("date")]
    return {
        "source": "住建部首页快照",
        "source_url": MOHURD_HOME,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "policy_count": len(policies),
        "date_range": {"first": min(dates), "last": max(dates)} if dates else None,
        "warnings": warnings,
        "note": "中国政府网政策库直抓 403，国务院层面政策需按 SKILL.md 用 WebSearch 补采；"
                "本清单混有非政策新闻与置顶旧文，消费方按 date 窗口与 keywords 过滤",
        "policies": policies,
    }


def main() -> None:
    if not DEPS_AVAILABLE:
        print(json.dumps({"error": DEPS_ERROR}, ensure_ascii=False))
        sys.exit(1)

    parser = argparse.ArgumentParser(description="住建部最新政策清单结构化抓取")
    parser.add_argument("--max-details", type=int, default=15, help="最多抓取详情页数量（默认 15）")
    parser.add_argument("--output", type=str, default=None, help="输出文件路径（默认 stdout）")
    parser.add_argument("--home-html", type=str, default=None, help="离线模式：首页 HTML 文件（跳过详情页抓取）")
    parser.add_argument("--no-cache", action="store_true", help="禁用缓存")
    args = parser.parse_args()

    if args.no_cache:
        fetch_data._cache = None

    warnings: List[str] = []

    if args.home_html:
        home_path = Path(args.home_html).expanduser()
        if not home_path.exists():
            print(json.dumps({"error": f"首页文件不存在: {home_path}"}, ensure_ascii=False))
            sys.exit(1)
        home_content = home_path.read_bytes()
    else:
        try:
            home_content = fetch_data.fetch_url(MOHURD_HOME)
        except NetworkError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
            sys.exit(1)

    links = parse_policy_links(home_content)
    if not links:
        warnings.append("首页未解析到任何文章链接（页面结构可能变化）")

    policies: List[dict] = []
    for link in links:
        policies.append({
            "title": link["title"],
            "url": link["url"],
            "date": "",
            "source": "住建部",
            "keywords": tag_keywords(link["title"]),
        })

    if not args.home_html:
        for policy in policies[: args.max_details]:
            try:
                content = fetch_data.fetch_url(policy["url"])
            except NetworkError as exc:
                warnings.append(f"详情页抓取失败（{policy['title'][:20]}...）: {exc}")
                continue
            policy["date"] = parse_policy_detail_date(content)
            if not policy["date"]:
                warnings.append(f"详情页日期未解析到（{policy['title'][:20]}...）")

    output = build_output(policies, warnings)
    payload = json.dumps(output, ensure_ascii=False, indent=2)

    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
        print(json.dumps({
            "output": str(output_path),
            "policy_count": len(policies),
            "dated": sum(1 for policy in policies if policy["date"]),
        }, ensure_ascii=False))
    else:
        print(payload)


if __name__ == "__main__":
    main()
