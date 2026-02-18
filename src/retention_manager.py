"""Automatic retention policy for generated artifacts and temporary data."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.config import (
    ENABLE_RETENTION_POLICY,
    OUTPUTS_DIR,
    RETENTION_CHECKPOINT_DAYS,
    RETENTION_DEAD_LETTER_DAYS,
    RETENTION_OUTPUT_DAYS,
    RETENTION_WEB_UPLOAD_DAYS,
)

logger = logging.getLogger("assessor_ai")


def _collect_target_files(base: Path, patterns: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
        for candidate in base.glob(pattern):
            if candidate.is_file():
                files.append(candidate)
    return files


def _remove_expired_files(files: list[Path], cutoff: datetime) -> int:
    removed = 0
    for fp in files:
        modified = datetime.fromtimestamp(fp.stat().st_mtime)
        if modified >= cutoff:
            continue
        try:
            fp.unlink()
            removed += 1
        except Exception:
            logger.warning("Falha ao remover arquivo expirado: %s", fp, exc_info=True)
    return removed


def _remove_empty_dirs(base: Path) -> int:
    removed = 0
    for directory in sorted(
        [d for d in base.glob("**/*") if d.is_dir()],
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        try:
            if any(directory.iterdir()):
                continue
            directory.rmdir()
            removed += 1
        except Exception:
            continue
    return removed


def aplicar_politica_retencao(now: datetime | None = None) -> dict[str, Any]:
    """Apply retention policy and return cleanup summary."""
    if not ENABLE_RETENTION_POLICY:
        return {"ativo": False, "arquivos_removidos": 0, "diretorios_removidos": 0, "detalhes": {}}

    current = now or datetime.now()
    targets: tuple[tuple[str, Path, tuple[str, ...], int], ...] = (
        (
            "outputs",
            OUTPUTS_DIR,
            (
                "minuta_*.md",
                "minuta_*.docx",
                "auditoria_*.md",
                "trilha_auditoria_*.json",
                "snapshot_execucao_*.json",
                "dashboard_operacional_*.json",
                "dashboard_operacional_*.md",
                "baseline_dataset_ouro_*.json",
                "baseline_dataset_ouro_*.md",
                "quality_gate_*.json",
                "regression_alert_*.json",
            ),
            RETENTION_OUTPUT_DAYS,
        ),
        (
            "checkpoints",
            OUTPUTS_DIR / ".checkpoints",
            ("estado_*.json",),
            RETENTION_CHECKPOINT_DAYS,
        ),
        (
            "web_uploads",
            OUTPUTS_DIR / "web_uploads",
            ("**/*",),
            RETENTION_WEB_UPLOAD_DAYS,
        ),
        (
            "dead_letter",
            OUTPUTS_DIR / "dead_letter",
            ("dlq_*.json",),
            RETENTION_DEAD_LETTER_DAYS,
        ),
    )

    summary: dict[str, Any] = {
        "ativo": True,
        "arquivos_removidos": 0,
        "diretorios_removidos": 0,
        "detalhes": {},
    }

    for nome, base, patterns, days in targets:
        if not base.exists():
            summary["detalhes"][nome] = {"arquivos_removidos": 0, "diretorios_removidos": 0}
            continue

        cutoff = current - timedelta(days=max(1, int(days)))
        files = _collect_target_files(base, patterns)
        removed_files = _remove_expired_files(files, cutoff)
        removed_dirs = _remove_empty_dirs(base)

        summary["detalhes"][nome] = {
            "arquivos_removidos": removed_files,
            "diretorios_removidos": removed_dirs,
            "cutoff_iso": cutoff.isoformat(),
        }
        summary["arquivos_removidos"] += removed_files
        summary["diretorios_removidos"] += removed_dirs

    if summary["arquivos_removidos"] > 0 or summary["diretorios_removidos"] > 0:
        logger.info(
            "🧹 Retenção aplicada: arquivos=%d diretórios=%d",
            summary["arquivos_removidos"],
            summary["diretorios_removidos"],
        )

    return summary

