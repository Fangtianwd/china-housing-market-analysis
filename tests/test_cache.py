import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cache import DiskCache, SimpleCache  # noqa: E402


class DiskCacheTests(unittest.TestCase):
    def test_set_get_roundtrip_across_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = DiskCache(cache_dir=tmp, ttl_seconds=3600)
            first.set("https://example.com/a", b"content-a")

            second = DiskCache(cache_dir=tmp, ttl_seconds=3600)
            self.assertEqual(second.get("https://example.com/a"), b"content-a")
            self.assertIsNone(second.get("https://example.com/missing"))
            self.assertEqual(second.size(), 1)

    def test_ttl_expiry(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = DiskCache(cache_dir=tmp, ttl_seconds=60)
            cache.set("https://example.com/ttl", b"x")

            with mock.patch("cache.time.time", return_value=time.time() + 120):
                self.assertIsNone(cache.get("https://example.com/ttl"))

    def test_permanent_never_expires(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = DiskCache(cache_dir=tmp, ttl_seconds=60)
            cache.set("https://example.com/perm", b"x", permanent=True)

            with mock.patch("cache.time.time", return_value=time.time() + 10**8):
                self.assertEqual(cache.get("https://example.com/perm"), b"x")

    def test_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = DiskCache(cache_dir=tmp, ttl_seconds=60)
            cache.set("https://example.com/a", b"x")
            cache.set("https://example.com/b", b"y")
            cache.clear()
            self.assertEqual(cache.size(), 0)

    def test_simple_cache_accepts_permanent_kwarg(self):
        cache = SimpleCache(max_size=10, ttl_seconds=3600)
        cache.set("k", b"v", permanent=True)
        self.assertEqual(cache.get("k"), b"v")


if __name__ == "__main__":
    unittest.main()
