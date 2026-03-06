"""Dead-letter queue persistence for non-transient pipeline failures.

Security policy:
- New snapshots are persisted only as encrypted `.dlq` files.
- If DLQ encryption key is missing, persistence is skipped to avoid plaintext at rest.
- Legacy `.json` files remain readable via `ler_dead_letter(path)` for migration/debug.
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import (
    DLQ_ENCRYPTION_ENABLED,
    DLQ_ENCRYPTION_KEY,
    ENABLE_DEAD_LETTER_QUEUE,
    OUTPUTS_DIR,
)
from src.crypto_utils import decrypt_json, encrypt_json
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
    """Persist full error snapshot for non-transient failures.

    Saves encrypted `.dlq` snapshots.
    If DLQ encryption is not configured, returns None and logs a security warning.
    """
    if not is_non_transient_error(exc):
        return None
    if not DLQ_ENCRYPTION_ENABLED or not DLQ_ENCRYPTION_KEY:
        logger.error(
            "DLQ não persistida: DLQ_ENCRYPTION_KEY ausente (bloqueado para evitar texto plano)."
        )
        return None

    base_dir = Path(output_dir) if output_dir else DEAD_LETTER_DIR
    base_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    safe_proc = _sanitize_name(processo_id)
    extension = ".dlq"
    filepath = base_dir / f"dlq_{safe_proc}_{now.strftime('%Y%m%d_%H%M%S_%f')}{extension}"

    execucao_id = estado.metadata.execucao_id if estado else ""
    error_trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    payload: dict[str, Any] = {
        "dlq_schema_version": "2.1.0",
        "encrypted": True,
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

    blob = encrypt_json(payload, DLQ_ENCRYPTION_KEY)
    filepath.write_bytes(blob)
    logger.error(
        "📮 🔐 Caso não-transiente enviado para DLQ (criptografado): %s", filepath
    )

    return filepath


def ler_dead_letter(path: str | Path) -> dict[str, Any]:
    """Read a DLQ file, automatically handling both encrypted (.dlq) and plaintext (.json) formats.

    Args:
        path: Path to a `.dlq` (encrypted) or `.json` (legacy) file.

    Returns:
        Decrypted/parsed dict with the full error snapshot.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is encrypted but DLQ_ENCRYPTION_KEY is not set,
                    or if the key is incorrect/data is corrupted.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo DLQ não encontrado: {path}")

    raw = path.read_bytes()

    if path.suffix == ".dlq":
        if not DLQ_ENCRYPTION_KEY:
            raise ValueError(
                f"Arquivo '{path.name}' está criptografado mas DLQ_ENCRYPTION_KEY não está configurada."
            )
        return decrypt_json(raw, DLQ_ENCRYPTION_KEY)

    # Legacy plaintext .json
    return json.loads(raw.decode("utf-8"))
