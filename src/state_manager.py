"""Pipeline state management: save, restore, and cleanup checkpoints."""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.config import OUTPUTS_DIR
from src.models import EstadoPipeline, ResultadoEtapa1, ResultadoEtapa2, ResultadoEtapa3

logger = logging.getLogger("copilot_juridico")

CHECKPOINT_DIR = OUTPUTS_DIR / ".checkpoints"


def _ensure_checkpoint_dir() -> Path:
    """Create checkpoint directory if it doesn't exist."""
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    return CHECKPOINT_DIR


def _checkpoint_path(processo_id: str = "default") -> Path:
    """Get checkpoint file path for a process."""
    safe_name = processo_id.replace("/", "_").replace("\\", "_")
    return _ensure_checkpoint_dir() / f"estado_{safe_name}.json"


# --- 3.4.1 Save state ---


def salvar_estado(estado: EstadoPipeline, processo_id: str = "default") -> Path:
    """
    Save pipeline state to JSON checkpoint.

    Args:
        estado: Current pipeline state.
        processo_id: Process identifier for the checkpoint file.

    Returns:
        Path to the saved checkpoint file.
    """
    filepath = _checkpoint_path(processo_id)
    data = estado.model_dump_json(indent=2)
    filepath.write_text(data, encoding="utf-8")
    logger.info("💾 Estado salvo em: %s", filepath)
    return filepath


# --- 3.4.3 Restore state ---


def restaurar_estado(filepath: str | Path | None = None, processo_id: str = "default") -> EstadoPipeline | None:
    """
    Restore pipeline state from JSON checkpoint.

    Args:
        filepath: Direct path to checkpoint file. If None, uses processo_id.
        processo_id: Process identifier to find checkpoint.

    Returns:
        Restored EstadoPipeline, or None if no checkpoint found.
    """
    if filepath is None:
        filepath = _checkpoint_path(processo_id)
    else:
        filepath = Path(filepath)

    if not filepath.exists():
        logger.debug("Nenhum checkpoint encontrado: %s", filepath)
        return None

    try:
        data = filepath.read_text(encoding="utf-8")
        estado = EstadoPipeline.model_validate_json(data)
        logger.info("📂 Estado restaurado de: %s", filepath)
        return estado
    except Exception as e:
        logger.error("Erro ao restaurar estado de %s: %s", filepath, e)
        return None


# --- Cleanup ---


def limpar_checkpoints(processo_id: str | None = None) -> int:
    """
    Remove checkpoint files.

    Args:
        processo_id: If provided, remove only that process's checkpoint.
                     If None, remove all checkpoints.

    Returns:
        Number of files removed.
    """
    if not CHECKPOINT_DIR.exists():
        return 0

    removed = 0
    if processo_id:
        fp = _checkpoint_path(processo_id)
        if fp.exists():
            fp.unlink()
            removed = 1
    else:
        for fp in CHECKPOINT_DIR.glob("estado_*.json"):
            fp.unlink()
            removed += 1

    if removed:
        logger.info("🗑️  %d checkpoint(s) removido(s)", removed)

    return removed


def listar_checkpoints() -> list[dict]:
    """List available checkpoints with metadata."""
    if not CHECKPOINT_DIR.exists():
        return []

    result = []
    for fp in CHECKPOINT_DIR.glob("estado_*.json"):
        stat = fp.stat()
        result.append({
            "arquivo": str(fp),
            "processo": fp.stem.replace("estado_", ""),
            "tamanho_bytes": stat.st_size,
            "modificado": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return result
