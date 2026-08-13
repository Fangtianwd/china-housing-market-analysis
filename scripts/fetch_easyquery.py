#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fetch_easyquery.py - 通过 data.stats.gov.cn EasyQuery API 补采历史价格指数

目标：补采 2020-01 至 2021-07 超出归档覆盖的 70 城价格指数期次。

API 说明：
  - URL: https://data.stats.gov.cn/easyquery.htm
  - 参数: m=QueryData, dbcode=fsnd（定基指数数据库）
  - 指标代码: A0G0E01（新建商品住宅）/ A0G0E02（二手住宅）
  - 城市代码: 6 位行政区划码
  - 时间格式: YYYYMM

注意：该 API 受 WAF 保护，部分环境可能返回 403。
  若直接访问失败，可尝试 --proxy 或从其他网络环境运行。
  也支持 --archive 模式：从搜索引擎索引的归档公告页补采（备选）。

输出：与 validate_full_data.py --dataset-output 相同结构的数据集 JSON。
"""
import argparse
import json
import re
import sys
import time
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
import validate_full_data
from config import SUPPORTED_CITIES, TITLE_KEY
from exceptions import NetworkError

# 70 城 6 位行政区划代码（从统计局数据代码表整理）
CITY_CODES = {
    "北京": "110000", "天津": "120000", "石家庄": "130100", "太原": "140100",
    "呼和浩特": "150100", "沈阳": "210100", "大连": "210200", "长春": "220100",
    "哈尔滨": "230100", "上海": "310000", "南京": "320100", "杭州": "330100",
    "宁波": "330200", "合肥": "340100", "福州": "350100", "厦门": "350200",
    "南昌": "360100", "济南": "370100", "青岛": "370200", "郑州": "410100",
    "武汉": "420100", "长沙": "430100", "广州": "440100", "深圳": "440300",
    "南宁": "450100", "海口": "460100", "重庆": "500000", "成都": "510100",
    "贵阳": "520100", "昆明": "530100", "西安": "610100", "兰州": "620100",
    "西宁": "630100", "银川": "640100", "乌鲁木齐": "650100",
    "唐山": "130200", "秦皇岛": "130300", "包头": "150200", "丹东": "210600",
    "锦州": "210700", "吉林": "220200", "牡丹江": "231000", "无锡": "320200",
    "徐州": "320300", "扬州": "321000", "温州": "330300", "金华": "330700",
    "蚌埠": "340300", "安庆": "340800", "泉州": "350500", "九江": "360400",
    "赣州": "360700", "烟台": "370600", "济宁": "370800", "洛阳": "410300",
    "平顶山": "410400", "宜昌": "420500", "襄阳": "420600", "岳阳": "430600",
    "常德": "430700", "韶关": "440200", "湛江": "440800", "惠州": "441300",
    "桂林": "450300", "北海": "450500", "三亚": "460200", "泸州": "510500",
    "南充": "511300", "遵义": "520300", "大理": "532900",
}

EASYQUERY_URL = "https://data.stats.gov.cn/easyquery.htm"
INDICATOR_CODES = {
    "新建商品住宅销售价格指数": "A0G0E01",
    "二手住宅销售价格指数": "A0G0E02",
}
REQUEST_DELAY = 1.5  # 两次请求之间的延迟（秒），避免触发反爬


def build_request_params(indicator_code: str, city_code: str, period: str) -> Dict:
    """构建 EasyQuery API 请求参数。"""
    return {
        "m": "QueryData",
        "dbcode": "fsnd",
        "rowcode": "reg",
        "colcode": "sj",
        "wds": f'[{{"wdcode":"zb","valuecode":"{indicator_code}"}},{{"wdcode":"reg","valuecode":"{city_code}"}}]',
        "dfwds": f'[{{"wdcode":"sj","valuecode":"{period}"}}]',
    }


def call_api(city: str, city_code: str, indicator_code: str, period: str) -> Optional[float]:
    """调用 EasyQuery API 查询单个城市×指标×月份的值。"""
    params = build_request_params(indicator_code, city_code, period)
    try:
        r = requests.get(
            EASYQUERY_URL,
            params=params,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Referer": "https://data.stats.gov.cn/easyquery.htm",
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        datanodes = data.get("returndata", {}).get("datanodes", [])
        if datanodes:
            return datanodes[0].get("data", {}).get("data")
        return None
    except Exception as exc:
        raise NetworkError(
            f"API 请求失败: {exc}", url=EASYQUERY_URL,
            status_code=getattr(getattr(exc, "response", None), "status_code", None),
        )


def fetch_via_archive(period: str, source_url: str) -> List[Dict]:
    """从归档公告页 URL 补采单期数据（备选方案）。"""
    try:
        content = fetch_data.fetch_url(source_url, cache_permanent=True)
    except NetworkError as exc:
        raise NetworkError(f"归档页 {period} 抓取失败: {exc}")

    records = validate_full_data.parse_full_page(content, period, source_url)
    for record in records:
        issues = validate_full_data.validate_record_schema(record)
        if issues:
            raise ValueError(f"{period} 记录 schema 问题: {issues[:3]}")
    return records


def find_archive_urls(period: str) -> str:
    """通过搜索引擎索引模式构造 2020-2021 年公告页 URL。

    公告页 URL 模式：https://www.stats.gov.cn/sj/zxfb/{YYYYMM}/t{YYYYMMDD}_XXXXXX.html
    注意：2020-2021 年公告页已从 stats.gov.cn 实时站点删除，需通过搜索引擎缓存访问。
    """
    raise NotImplementedError(
        "2020-2021 年公告页已从实时站点删除，需要通过搜索引擎缓存或 Wayback Machine 访问。"
        "参见 references/DATA_SOURCES.md 的已知缺口说明。"
    )


def build_output(records: List[Dict], warnings: List[str], period_range: dict) -> Dict:
    return {
        "source": "EasyQuery API / 归档页补采",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "period_range": period_range,
        "record_count": len(records),
        "warnings": warnings,
        "records": records,
    }


def main() -> None:
    if not DEPS_AVAILABLE:
        print(json.dumps({"error": DEPS_ERROR}, ensure_ascii=False))
        sys.exit(1)

    parser = argparse.ArgumentParser(description="补采 2020-2021 年 70 城价格指数历史数据")
    parser.add_argument("--since", default="2020-01", help="起始期次 YYYY-MM（默认 2020-01）")
    parser.add_argument("--until", default="2021-07", help="结束期次 YYYY-MM（默认 2021-07）")
    parser.add_argument("--output", type=str, default=None, help="输出文件路径")
    parser.add_argument("--api", action="store_true", help="使用 EasyQuery API（需取消 WAF 封锁）")
    parser.add_argument("--proxy", type=str, default=None, help="HTTP 代理地址（如 http://127.0.0.1:7890）")
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY, help=f"请求间隔秒数（默认 {REQUEST_DELAY}）")
    parser.add_argument("--no-cache", action="store_true", help="禁用缓存")
    args = parser.parse_args()

    if args.no_cache:
        fetch_data._cache = None

    session = requests.Session()
    if args.proxy:
        session.proxies = {"http": args.proxy, "https": args.proxy}

    periods = []
    y, m = args.since.split("-")
    until_y, until_m = args.until.split("-")
    while (y, m) <= (until_y, until_m):
        periods.append(f"{y}-{m}")
        m = str(int(m) + 1).zfill(2)
        if m > "12":
            y = str(int(y) + 1)
            m = "01"

    warnings: List[str] = []
    all_records: List[Dict] = []

    if args.api:
        # EasyQuery API 模式
        warnings.append("EasyQuery API 受 WAF 保护，部分环境可能不可用")
        for period in periods:
            for indicator_name, indicator_code in INDICATOR_CODES.items():
                for city in SUPPORTED_CITIES:
                    city_code = CITY_CODES.get(city)
                    if not city_code:
                        warnings.append(f"跳过 {city}：缺少行政区划代码")
                        continue
                    try:
                        value = call_api(city, city_code, indicator_code, period)
                        if value is not None:
                            all_records.append({
                                "period": period,
                                "city": city,
                                "indicator": indicator_name,
                                "metrics": {"定基": value},
                                "source_url": EASYQUERY_URL,
                            })
                    except NetworkError as exc:
                        warnings.append(f"{period} {city} {indicator_name}: {exc}")
                    time.sleep(args.delay)
    else:
        # 信息模式：输出已知缺口与补采说明
        print(json.dumps({
            "note": "2020-01 至 2021-07 的价格指数数据需要通过以下方式补采：",
            "method_a": {
                "source": "data.stats.gov.cn EasyQuery API",
                "command": f"python3 {__file__} --api [--proxy http://代理地址] [--since 2020-01 --until 2021-07]",
                "limitation": "该 API 受 WAF 保护，在部分网络环境（如公司代理、云服务器）可能返回 403",
            },
            "method_b": {
                "source": "谷歌快照 / 搜索引擎缓存",
                "hint": "通过 WebSearch 检索 'site:stats.gov.cn 70个大中城市商品住宅销售价格变动情况 2020' 找到公告页，"
                        "用搜索引擎快照访问并手动补采",
            },
            "method_c": {
                "source": "第三方数据平台（如 investing.com、Tushare、东方财富等）",
                "note": "需验证数据口径与统计局一致",
            },
            "known_gap": "2020-01 至 2021-07 共 19 个月，详见 references/KNOWN_BREAKS.md",
        }, ensure_ascii=False, indent=2))
        return

    output = build_output(all_records, warnings, {"first": args.since, "last": args.until})
    payload = json.dumps(output, ensure_ascii=False, indent=2)

    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")
        print(json.dumps({"output": str(output_path), "record_count": len(all_records), "warnings_count": len(warnings)}, ensure_ascii=False))
    else:
        print(payload)


if __name__ == "__main__":
    main()