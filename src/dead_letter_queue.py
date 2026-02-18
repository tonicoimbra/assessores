"""Dead-letter queue persistence for non-transient pipeline failures."""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import ENABLE_DEAD_LETTER_QUEUE, OUTPUTS_DIR
from src.models import EstadoPipeline

logger = logging.getLogger("assessor_ai")

DEAD_LETTER_DIR = OUTPUTS_DIR / "dead_letter"

TRANSIENT_ERROR_NAMES = {
    "RateLimitError",
    "APITimeoutError",
    "APIConnectionError",
    "TimeoutError",
    "ConnectionError",
    "ServiceUnavailableError",
}

TRANSIENT_MESSAGE_HINTS = (
    "rate limit",
    "429",
    "temporar",
    "timeout",
    "connection reset",
    "network",
)


def _sanitize_name(raw: str) -> str:
    """Sanitize dynamic names used in filesystem paths."""
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw).strip("_") or "default"


def is_non_transient_error(exc: Exception) -> bool:
    """Return True when failure should be persisted in dead-letter queue."""
    if not ENABLE_DEAD_LETTER_QUEUE:
        return False

    if isinstance(exc, KeyboardInterrupt):
        return False

    name = type(exc).__name__
    if name in TRANSIENT_ERROR_NAMES:
        return False

    message = str(exc).lower()
    if any(hint in message for hint in TRANSIENT_MESSAGE_HINTS):
        return False

    return True


def salvar_dead_letter(
    exc: Exception,
    *,
    processo_id: str = "default",
    estado: EstadoPipeline | None = None,
    metricas: dict[str, Any] | None = None,
    contexto: dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
) -> Path | None:
    """Persist full error snapshot for non-transient failures."""
    if not is_non_transient_error(exc):
        return None

    base_dir = Path(output_dir) if output_dir else DEAD_LETTER_DIR
    base_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    safe_proc = _sanitize_name(processo_id)
    filepath = base_dir / f"dlq_{safe_proc}_{now.strftime('%Y%m%d_%H%M%S_%f')}.json"
    execucao_id = estado.metadata.execucao_id if estado else ""
    error_trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    payload: dict[str, Any] = {
        "dlq_schema_version": "1.0.0",
        "timestamp": now.isoformat(),
        "processo_id": processo_id,
        "execucao_id": execucao_id,
        "erro": {
            "tipo": type(exc).__name__,
            "mensagem": str(exc),
            "non_transient": True,
            "traceback": error_trace,
        },
        "contexto": contexto or {},
        "metricas": metricas or {},
        "estado_pipeline": estado.model_dump(mode="json") if estado else None,
    }

    filepath.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.error("📮 Caso não-transiente enviado para DLQ: %s", filepath)
    return filepath
