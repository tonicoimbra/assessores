"""Tests for file-based cache manager."""

from __future__ import annotations

import time
import os
from pathlib import Path

from src.cache_manager import CacheManager


class TestCacheManager:
    """Cache behavior: read/write, TTL, cleanup, and stats."""

    def test_hash_is_stable_and_short(self, tmp_path: Path) -> None:
        cache = CacheManager(cache_dir=tmp_path / ".cache", ttl_hours=1)
        h1 = cache._hash_text("same input")
        h2 = cache._hash_text("same input")
        h3 = cache._hash_text("different input")

        assert h1 == h2
        assert h1 != h3
        assert len(h1) == 16

    def test_hash_payload_is_stable_for_equivalent_dict_order(self, tmp_path: Path) -> None:
        cache = CacheManager(cache_dir=tmp_path / ".cache", ttl_hours=1)
        p1 = {"model": "gpt-4o", "params": {"max_tokens": 100, "temperature": 0.0}}
        p2 = {"params": {"temperature": 0.0, "max_tokens": 100}, "model": "gpt-4o"}

        h1 = cache.hash_payload(p1)
        h2 = cache.hash_payload(p2)

        assert h1 == h2
        assert len(h1) == 32

    def test_build_multilevel_cache_identity_contains_model_prompt_and_schema(self, tmp_path: Path) -> None:
        cache = CacheManager(cache_dir=tmp_path / ".cache", ttl_hours=1)
        category, key = cache.build_multilevel_cache_identity(
            model="gpt-4o-mini",
            input_payload=[{"role": "user", "content": "oi"}],
            prompt_version="v2",
            prompt_hash="abcdef1234567890",
            schema_version="json_object",
            provider="openai",
        )

        assert category == "llm_calls/openai/gpt-4o-mini/v2/json_object"
        assert len(key) == 32

    def test_set_and_get_roundtrip(self, tmp_path: Path) -> None:
        cache = CacheManager(cache_dir=tmp_path / ".cache", ttl_hours=1)
        key = cache._hash_text("prompt")
        payload = {"answer": "ok", "tokens": 123}

        cache.set(key, payload, category="llm")
        cached = cache.get(key, category="llm")

        assert cached == payload

    def test_get_expired_entry_returns_none_and_deletes_file(self, tmp_path: Path) -> None:
        cache = CacheManager(cache_dir=tmp_path / ".cache", ttl_hours=1)
        key = cache._hash_text("old entry")
        cache.set(key, {"value": "stale"}, category="llm")
        cache_file = cache._get_cache_path(key, "llm")

        old_mtime = time.time() - (cache.ttl_seconds + 10)
        os.utime(cache_file, (old_mtime, old_mtime))

        assert cache.get(key, category="llm") is None
        assert not cache_file.exists()

    def test_get_corrupted_file_returns_none_and_deletes_file(self, tmp_path: Path) -> None:
        cache = CacheManager(cache_dir=tmp_path / ".cache", ttl_hours=1)
        key = cache._hash_text("broken")
        cache_file = cache._get_cache_path(key, "llm")
        cache_file.write_text("{invalid json", encoding="utf-8")

        assert cache.get(key, category="llm") is None
        assert not cache_file.exists()

    def test_invalidate_existing_and_missing_keys(self, tmp_path: Path) -> None:
        cache = CacheManager(cache_dir=tmp_path / ".cache", ttl_hours=1)
        key = cache._hash_text("to-delete")
        cache.set(key, {"ok": True})

        assert cache.invalidate(key) is True
        assert cache.invalidate(key) is False

    def test_clear_category_and_all(self, tmp_path: Path) -> None:
        cache = CacheManager(cache_dir=tmp_path / ".cache", ttl_hours=1)
        cache.set(cache._hash_text("a"), {"v": 1}, category="stage1")
        cache.set(cache._hash_text("b"), {"v": 2}, category="stage1")
        cache.set(cache._hash_text("c"), {"v": 3}, category="stage2")

        cleared_stage1 = cache.clear(category="stage1")
        assert cleared_stage1 == 2
        assert cache.clear(category="missing") == 0

        cleared_all = cache.clear()
        assert cleared_all == 1

    def test_cleanup_expired_only_removes_stale_entries(self, tmp_path: Path) -> None:
        cache = CacheManager(cache_dir=tmp_path / ".cache", ttl_hours=1)
        stale_key = cache._hash_text("stale")
        fresh_key = cache._hash_text("fresh")

        cache.set(stale_key, {"v": "old"}, category="llm")
        cache.set(fresh_key, {"v": "new"}, category="llm")

        stale_file = cache._get_cache_path(stale_key, "llm")
        old_mtime = time.time() - (cache.ttl_seconds + 10)
        os.utime(stale_file, (old_mtime, old_mtime))

        deleted = cache.cleanup_expired()
        assert deleted == 1
        assert cache.get(stale_key, "llm") is None
        assert cache.get(fresh_key, "llm") == {"v": "new"}

    def test_get_stats_reports_category_counts(self, tmp_path: Path) -> None:
        cache = CacheManager(cache_dir=tmp_path / ".cache", ttl_hours=2)
        cache.set(cache._hash_text("1"), {"v": 1}, category="a")
        cache.set(cache._hash_text("2"), {"v": 2}, category="b")
        cache.set(cache._hash_text("3"), {"v": 3}, category="b")

        stats = cache.get_stats()
        assert stats["total_files"] == 3
        assert stats["categories"]["a"] == 1
        assert stats["categories"]["b"] == 2
        assert stats["ttl_hours"] == 2

    def test_nested_categories_are_supported(self, tmp_path: Path) -> None:
        cache = CacheManager(cache_dir=tmp_path / ".cache", ttl_hours=2)
        cache.set("k1", {"v": 1}, category="llm_calls/openai/gpt-4o/v1/raw")
        cache.set("k2", {"v": 2}, category="llm_calls/openai/gpt-4o/v1/raw")
        cache.set("k3", {"v": 3}, category="llm_calls/openai/gpt-4o/v2/json_object")

        stats = cache.get_stats()
        assert stats["total_files"] == 3
        assert stats["categories"]["llm_calls/openai/gpt-4o/v1/raw"] == 2
        assert stats["categories"]["llm_calls/openai/gpt-4o/v2/json_object"] == 1
