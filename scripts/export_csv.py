#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_csv.py - 从全量数据集导出 70 城价格指数 CSV（UTF-8 BOM）

消费 artifacts/full-dataset.json（validate_full_data.py --dataset-output 产出），
输出长格式 CSV：城市 × 月份 × 住宅类型 × 面积段 × 环比/同比/定基/累计平均。

用法：
  python export_csv.py [--input artifacts/full-dataset.json] [--output FILE]
"""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from config import AREA_SEGMENTS, CATEGORY_METRIC_SEPARATOR, INDICATORS

DEFAULT_INPUT = Path(__file__).resolve().parent.parent / "artifacts" / "full-dataset.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "artifacts" / "china_housing_market_data.csv"

INDICATOR_LABELS = {
    INDICATORS["new"]: "新建商品住宅",
    INDICATORS["used"]: "二手住宅",
    INDICATORS["new_cat"]: "新建商品住宅",
    INDICATORS["used_cat"]: "二手住宅",
}
CATEGORY_INDICATORS = (INDICATORS["new_cat"], INDICATORS["used_cat"])
METRIC_COLUMNS = ["环比", "同比", "定基", "累计平均"]
CSV_HEADER = ["城市", "月份", "住宅类型", "面积段", *METRIC_COLUMNS, "来源URL"]


def record_to_rows(record: Dict[str, object]) -> List[List[Optional[str]]]:
    """将数据集记录展开为 CSV 行（分类记录按面积段展开为多行）。"""
    indicator = record.get("indicator")
    base = [
        record.get("city"),
        record.get("period"),
        INDICATOR_LABELS.get(indicator, indicator),
    ]
    metrics = record.get("metrics") or {}
    source_url = record.get("source_url", "")

    if indicator in CATEGORY_INDICATORS:
        rows = []
        for segment in AREA_SEGMENTS:
            prefix = f"{segment}{CATEGORY_METRIC_SEPARATOR}"
            values = [metrics.get(f"{prefix}{metric}") for metric in METRIC_COLUMNS]
            if all(value is None for value in values):
                continue
            rows.append([*base, segment, *values, source_url])
        return rows

    values = [metrics.get(metric) for metric in METRIC_COLUMNS]
    return [[*base, "全部", *values, source_url]]


def export(dataset: Dict[str, object], output_path: Path) -> Dict[str, object]:
    """导出 CSV（UTF-8 BOM），返回统计摘要。"""
    records = dataset.get("records", [])
    row_count = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        for record in records:
            for row in record_to_rows(record):
                writer.writerow(row)
                row_count += 1

    periods = sorted({record["period"] for record in records if record.get("period")})
    return {
        "output": str(output_path),
        "encoding": "utf-8-sig",
        "row_count": row_count,
        "record_count": len(records),
        "period_range": {"first": periods[0], "last": periods[-1]} if periods else None,
        "exported_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="从全量数据集导出 70 城价格指数 CSV（UTF-8 BOM）")
    parser.add_argument("--input", type=str, default=str(DEFAULT_INPUT), help="全量数据集 JSON 路径")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT), help="CSV 输出路径")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser()
    if not input_path.exists():
        print(json.dumps({
            "error": f"数据集文件不存在: {input_path}",
            "hint": "先运行: python scripts/validate_full_data.py --dataset-output artifacts/full-dataset.json",
        }, ensure_ascii=False))
        sys.exit(1)

    try:
        dataset = json.loads(input_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"error": f"数据集读取失败: {exc}"}, ensure_ascii=False))
        sys.exit(1)

    if not dataset.get("records"):
        print(json.dumps({"error": "数据集为空（records 缺失）", "input": str(input_path)}, ensure_ascii=False))
        sys.exit(1)

    summary = export(dataset, Path(args.output).expanduser())
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
