"""Tests for automatic retention policy cleanup."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import src.retention_manager as retention_manager


def _touch_with_mtime(path: Path, when: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    ts = when.timestamp()
    path.chmod(0o600)
    import os

    os.utime(path, (ts, ts))


def test_retention_disabled_returns_inactive(monkeypatch) -> None:
    monkeypatch.setattr(retention_manager, "ENABLE_RETENTION_POLICY", False)
    summary = retention_manager.aplicar_politica_retencao()
    assert summary["ativo"] is False
    assert summary["arquivos_removidos"] == 0


def test_retention_removes_expired_files_and_keeps_recent(tmp_path: Path, monkeypatch) -> None:
    outputs_dir = tmp_path / "outputs"
    now = datetime(2026, 2, 18, 12, 0, 0)

    old_file = outputs_dir / "minuta_old.md"
    new_file = outputs_dir / "minuta_new.md"
    old_checkpoint = outputs_dir / ".checkpoints" / "estado_old.json"
    new_checkpoint = outputs_dir / ".checkpoints" / "estado_new.json"

    _touch_with_mtime(old_file, now - timedelta(days=40))
    _touch_with_mtime(new_file, now - timedelta(days=1))
    _touch_with_mtime(old_checkpoint, now - timedelta(days=10))
    _touch_with_mtime(new_checkpoint, now - timedelta(days=1))

    monkeypatch.setattr(retention_manager, "ENABLE_RETENTION_POLICY", True)
    monkeypatch.setattr(retention_manager, "OUTPUTS_DIR", outputs_dir)
    monkeypatch.setattr(retention_manager, "RETENTION_OUTPUT_DAYS", 30)
    monkeypatch.setattr(retention_manager, "RETENTION_CHECKPOINT_DAYS", 7)
    monkeypatch.setattr(retention_manager, "RETENTION_WEB_UPLOAD_DAYS", 2)
    monkeypatch.setattr(retention_manager, "RETENTION_DEAD_LETTER_DAYS", 30)

    summary = retention_manager.aplicar_politica_retencao(now=now)

    assert summary["ativo"] is True
    assert summary["arquivos_removidos"] >= 2
    assert not old_file.exists()
    assert not old_checkpoint.exists()
    assert new_file.exists()
    assert new_checkpoint.exists()

