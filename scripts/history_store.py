#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
history_store.py - 增量历史库：按期次沉淀价格指数全量数据

RSS 是滚动窗口（约 30 期），滚出的期次不会再现。本脚本把每次
validate_full_data.py 产出的数据集按期次合并进持久化历史库，
确保早期期次不丢失；数据被官方修订时保留旧版本（revisions）。

用法：
  python history_store.py --from artifacts/full-dataset.json
  python history_store.py --from artifacts/full-dataset.json --dry-run

存储结构（artifacts/history/price-index-history.json）：
  periods: { "YYYY-MM": { first_fetched_at, last_fetched_at, record_count,
                          records, revisions: [{archived_at, records}] } }
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

DEFAULT_STORE = Path(__file__).resolve().parent.parent / "artifacts" / "history" / "price-index-history.json"
MAX_REVISIONS = 2


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def canonical(records: List[dict]) -> str:
    """规范化序列化记录列表用于比较（排序 + 紧凑 JSON）。

    剔除 source_url：统计局改版 URL 不构成数据修订，若计入比较会
    让所有期次被误判 revised，噪音挤占真正的修订版本槽位。
    """
    stripped = [
        {key: value for key, value in record.items() if key != "source_url"}
        for record in records
    ]
    return json.dumps(
        sorted(stripped, key=lambda r: (r.get("city", ""), r.get("indicator", ""))),
        ensure_ascii=False,
        sort_keys=True,
    )


def group_by_period(records: List[dict]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = {}
    for record in records:
        period = record.get("period")
        if period:
            grouped.setdefault(period, []).append(record)
    return grouped


def merge(store: dict, dataset: dict, force: bool = False) -> dict:
    """将数据集合并进历史库，返回摘要（新增/修订/未变/被拒期次）。

    降级防护：已有期次的记录数骤降（<50%）时视为退化数据，拒绝覆盖，
    除非 force=True——防止一次解析故障把库里的完整版本顶掉。
    """
    periods_store = store.setdefault("periods", {})
    incoming = group_by_period(dataset.get("records", []))
    timestamp = now_iso()

    summary = {"new": [], "revised": [], "unchanged": [], "rejected": [], "total_in_store": 0}

    for period in sorted(incoming):
        records = incoming[period]
        entry = periods_store.get(period)

        if entry is None:
            periods_store[period] = {
                "first_fetched_at": timestamp,
                "last_fetched_at": timestamp,
                "record_count": len(records),
                "records": records,
                "revisions": [],
            }
            summary["new"].append(period)
            continue

        if not force and len(records) < len(entry["records"]) * 0.5:
            summary["rejected"].append({
                "period": period,
                "stored": len(entry["records"]),
                "incoming": len(records),
                "reason": "记录数骤降（<50%），疑似退化数据，拒绝覆盖；确认无误后加 --force",
            })
            continue

        if canonical(entry["records"]) == canonical(records):
            entry["last_fetched_at"] = timestamp
            summary["unchanged"].append(period)
        else:
            revisions = entry.setdefault("revisions", [])
            revisions.append({
                "archived_at": entry.get("last_fetched_at", timestamp),
                "record_count": entry.get("record_count", len(entry["records"])),
                "records": entry["records"],
            })
            entry["revisions"] = revisions[-MAX_REVISIONS:]
            entry["last_fetched_at"] = timestamp
            entry["record_count"] = len(records)
            entry["records"] = records
            summary["revised"].append(period)

    summary["total_in_store"] = len(periods_store)
    return summary


def store_metadata(store: dict) -> None:
    """更新历史库顶层元数据。"""
    periods = sorted(store.get("periods", {}))
    store["updated_at"] = now_iso()
    store["period_count"] = len(periods)
    store["period_range"] = {"first": periods[0], "last": periods[-1]} if periods else None
    store["latest_period"] = periods[-1] if periods else None


def main() -> None:
    parser = argparse.ArgumentParser(description="按期次沉淀价格指数全量数据到增量历史库")
    parser.add_argument(
        "--from",
        dest="dataset_input",
        type=str,
        required=True,
        help="validate_full_data.py 产出的数据集 JSON",
    )
    parser.add_argument("--store", type=str, default=str(DEFAULT_STORE), help="历史库文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只输出合并摘要，不写盘")
    parser.add_argument("--force", action="store_true", help="跳过降级防护（记录数骤降也覆盖）")
    args = parser.parse_args()

    dataset_path = Path(args.dataset_input).expanduser()
    if not dataset_path.exists():
        print(json.dumps({"error": f"数据集文件不存在: {dataset_path}"}, ensure_ascii=False))
        sys.exit(1)

    try:
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(json.dumps({"error": f"数据集读取失败: {exc}"}, ensure_ascii=False))
        sys.exit(1)

    if not dataset.get("records"):
        print(json.dumps({"error": "数据集为空（records 缺失）"}, ensure_ascii=False))
        sys.exit(1)

    store_path = Path(args.store).expanduser()
    store: dict = {}
    if store_path.exists():
        try:
            store = json.loads(store_path.read_text(encoding="utf-8"))
            if not isinstance(store, dict):
                raise ValueError("历史库顶层结构不是对象")
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            # 损坏库绝不静默重建覆盖：改名备份后退出，由人工决定恢复方式
            backup_path = store_path.with_name(
                f"{store_path.name}.corrupt-{int(time.time())}"
            )
            store_path.rename(backup_path)
            print(json.dumps({
                "error": f"历史库读取失败，已备份为 {backup_path}，本次拒绝写入: {exc}",
            }, ensure_ascii=False))
            sys.exit(1)

    summary = merge(store, dataset, force=args.force)
    store_metadata(store)

    if not args.dry_run:
        store_path.parent.mkdir(parents=True, exist_ok=True)
        # 原子写：临时文件 + os.replace，中断不会产生截断的历史库
        tmp_path = store_path.with_name(f"{store_path.name}.tmp")
        tmp_path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, store_path)

    print(json.dumps({
        "store": str(store_path),
        "dry_run": args.dry_run,
        "new_periods": summary["new"],
        "revised_periods": summary["revised"],
        "unchanged_count": len(summary["unchanged"]),
        "rejected": summary["rejected"],
        "total_in_store": summary["total_in_store"],
        "period_range": store.get("period_range"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
