# -*- coding: utf-8 -*-
"""
缓存实现：内存缓存（SimpleCache）与磁盘缓存（DiskCache）

磁盘缓存面向一次性 CLI 场景（跨进程生效）：
- 历史公告页一经发布不会变，可用 permanent=True 永久缓存；
- RSS 等会变的内容用 TTL（默认 1 小时）。
"""
import hashlib
import json
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional


class SimpleCache:
    """LRU 内存缓存（仅进程内有效，测试用途）"""

    def __init__(self, max_size: int = 100, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        if key not in self._cache:
            return None

        entry = self._cache[key]
        if time.time() - entry["timestamp"] > self.ttl_seconds:
            # 缓存过期，删除
            del self._cache[key]
            return None

        # 移到最后（最近使用）
        self._cache.move_to_end(key)
        return entry["value"]

    def set(self, key: str, value: Any, permanent: bool = False) -> None:
        """设置缓存值（内存缓存忽略 permanent）"""
        if key in self._cache:
            self._cache[key] = {
                "value": value,
                "timestamp": time.time(),
            }
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)
            self._cache[key] = {
                "value": value,
                "timestamp": time.time(),
            }

    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()

    def size(self) -> int:
        """获取缓存大小"""
        return len(self._cache)


class DiskCache:
    """磁盘缓存：URL 哈希 -> body 文件 + meta 文件，跨进程生效。"""

    def __init__(self, cache_dir, ttl_seconds: int = 3600):
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = ttl_seconds
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _paths(self, key: str):
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return (
            self.cache_dir / f"{digest}.body",
            self.cache_dir / f"{digest}.meta.json",
        )

    def get(self, key: str) -> Optional[bytes]:
        """获取缓存内容。permanent 条目永不过期，其余按 TTL。"""
        body_path, meta_path = self._paths(key)
        if not body_path.exists() or not meta_path.exists():
            return None

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        if not meta.get("permanent"):
            if time.time() - meta.get("fetched_at", 0) > self.ttl_seconds:
                return None

        try:
            return body_path.read_bytes()
        except OSError:
            return None

    def set(self, key: str, value: Any, permanent: bool = False) -> None:
        """写入缓存。permanent=True 用于发布后不再变化的历史页面。

        两个文件都走「临时文件 + rename」原子替换，meta 最后写入，
        中断不会留下 body/meta 不一致的组合。
        """
        body_path, meta_path = self._paths(key)
        body = value if isinstance(value, bytes) else str(value).encode("utf-8")

        body_tmp = body_path.with_suffix(".tmp")
        body_tmp.write_bytes(body)
        body_tmp.replace(body_path)

        meta_tmp = meta_path.with_suffix(".tmp")
        meta_tmp.write_text(
            json.dumps(
                {
                    "url": key,
                    "fetched_at": time.time(),
                    "permanent": bool(permanent),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        meta_tmp.replace(meta_path)

    def clear(self) -> None:
        """清空缓存"""
        for path in self.cache_dir.glob("*"):
            if path.is_file():
                path.unlink()

    def size(self) -> int:
        """获取缓存条目数"""
        return len(list(self.cache_dir.glob("*.body")))
