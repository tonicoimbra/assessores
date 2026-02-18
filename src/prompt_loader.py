"""Prompt loading and dynamic message building by stage."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from src.config import (
    ALLOW_MINIMAL_PROMPT_FALLBACK,
    PROMPT_PROFILE,
    PROMPT_STRATEGY,
    PROMPTS_DIR,
)

logger = logging.getLogger("assessor_ai")

PromptMessage = dict[str, str]
MINIMAL_SYSTEM_PROMPT = "Você é um assessor jurídico. Não invente informações."

_PROMPT_CACHE: dict[str, str] = {}
_PROMPT_MTIME: dict[str, float] = {}

_COMPONENT_FILES: dict[str, str] = {
    "system_base": "system_base.md",
    "dev_etapa1": "dev_etapa1.md",
    "dev_etapa2": "dev_etapa2.md",
    "dev_etapa3": "dev_etapa3.md",
    "referencias_longas": "referencias_longas.md",
}

_STAGE_TO_DEV_COMPONENT: dict[str, str] = {
    "etapa1": "dev_etapa1",
    "etapa2": "dev_etapa2",
    "etapa3": "dev_etapa3",
}

_REFERENCE_STAGES = {"etapa2", "etapa3"}
_PIPELINE_STAGES = ("etapa1", "etapa2", "etapa3")
_REQUIRED_PROMPT_COMPONENTS = ("system_base", "dev_etapa1", "dev_etapa2", "dev_etapa3")
_REQUIRED_MARKERS_BY_COMPONENT: dict[str, tuple[str, ...]] = {
    "system_base": ("Regras gerais obrigatórias",),
    "dev_etapa1": ("Formato obrigatório de saída", "Número do processo", "Recorrente"),
    "dev_etapa2": ("Formato obrigatório de saída", "Tema 1", "Conclusão e fundamentos"),
    "dev_etapa3": ("Formato obrigatório de saída", "**I –**", "**II –**", "**III –**"),
}


class PromptConfigurationError(RuntimeError):
    """Raised when prompt files are missing and fallback policy blocks execution."""


def _read_prompt_file(path: Path) -> str:
    """Read prompt file with in-memory cache and mtime invalidation."""
    key = str(path.resolve())
    if not path.exists():
        return ""

    stat = path.stat()
    mtime = stat.st_mtime

    if key in _PROMPT_CACHE and _PROMPT_MTIME.get(key) == mtime:
        return _PROMPT_CACHE[key]

    content = path.read_text(encoding="utf-8").strip()
    _PROMPT_CACHE[key] = content
    _PROMPT_MTIME[key] = mtime
    return content


def get_prompt_component(component: str) -> str:
    """Load a prompt component from prompts directory."""
    filename = _COMPONENT_FILES.get(component)
    if not filename:
        return ""
    return _read_prompt_file(PROMPTS_DIR / filename)


def _load_legacy_system_prompt() -> str:
    """Fallback to monolithic prompt for backward compatibility."""
    legacy = _read_prompt_file(PROMPTS_DIR / "SYSTEM_PROMPT.md")
    if legacy:
        logger.warning(
            "Usando fallback de prompt legado (SYSTEM_PROMPT.md) "
            "porque componentes modulares não foram encontrados."
        )
    return legacy


def _build_user_content(user_text: str, extra_context: str | None = None) -> str:
    """Build final user content with optional extra context."""
    if extra_context and extra_context.strip():
        return (
            "[CONTEXTO ADICIONAL]\n"
            f"{extra_context.strip()}\n\n"
            "[TAREFA]\n"
            f"{user_text.strip()}"
        )
    return user_text.strip()


def _should_include_references(stage: str, include_references: bool | None = None) -> bool:
    """Determine if long references should be injected."""
    if include_references is not None:
        return include_references
    return PROMPT_PROFILE == "full" and stage in _REFERENCE_STAGES


def _extract_prompt_version(content: str) -> str:
    """Extract prompt version from markdown content or return a fallback."""
    text = str(content or "")
    patterns = (
        r"(?im)^\s*>\s*\*?\*?vers[aã]o\*?\*?\s*:\s*([^\n\r]+)\s*$",
        r"(?im)^\s*\*?\*?vers[aã]o\*?\*?\s*:\s*([^\n\r]+)\s*$",
        r"(?is)<!--\s*version\s*:\s*([^-]+?)\s*-->",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        value = match.group(1).strip().strip("*").strip()
        if value:
            return value
    return "unversioned"


def _resolve_prompt_artifacts(
    stage: str,
    include_references: bool | None = None,
    developer_override: str | None = None,
    legacy_system_prompt: str | None = None,
) -> tuple[str, list[tuple[str, str]]]:
    """Return profile label and prompt artifacts used to build stage messages."""
    stage_key = stage.lower().strip()

    if legacy_system_prompt and legacy_system_prompt.strip():
        return "legacy-explicit", [("legacy_system_prompt", legacy_system_prompt.strip())]
    if PROMPT_STRATEGY == "legacy":
        legacy = _load_legacy_system_prompt()
        if not legacy:
            raise PromptConfigurationError(
                "PROMPT_STRATEGY=legacy ativo, mas prompts/SYSTEM_PROMPT.md não foi encontrado."
            )
        return "legacy-strategy", [("SYSTEM_PROMPT.md", legacy)]

    system_base = get_prompt_component("system_base")
    dev_component = _STAGE_TO_DEV_COMPONENT.get(stage_key, "")
    stage_developer = developer_override or (get_prompt_component(dev_component) if dev_component else "")

    if not system_base or not stage_developer:
        legacy = _load_legacy_system_prompt()
        if legacy:
            return "legacy-fallback", [("SYSTEM_PROMPT.md", legacy)]
        if not ALLOW_MINIMAL_PROMPT_FALLBACK:
            raise PromptConfigurationError(
                "Prompt modular ausente e SYSTEM_PROMPT.md indisponível. "
                "Fallback minimalista desabilitado por ALLOW_MINIMAL_PROMPT_FALLBACK=false."
            )
        logger.warning(
            "Usando fallback minimalista de prompt para stage=%s; "
            "ative os arquivos modulares ou SYSTEM_PROMPT.md para produção.",
            stage_key,
        )
        return "minimal-fallback", [("minimal_system_prompt", MINIMAL_SYSTEM_PROMPT)]

    artifacts: list[tuple[str, str]] = [
        ("system_base.md", system_base),
        (f"{dev_component}.md" if dev_component else "developer_prompt", stage_developer),
    ]
    if _should_include_references(stage_key, include_references=include_references):
        refs = get_prompt_component("referencias_longas")
        if refs:
            artifacts.append(("referencias_longas.md", refs))
    return f"modular-{PROMPT_PROFILE}", artifacts


def get_prompt_signature(
    stage: str,
    include_references: bool | None = None,
    developer_override: str | None = None,
    legacy_system_prompt: str | None = None,
) -> dict[str, str]:
    """Return prompt signature for a specific stage (profile, version, sha256)."""
    profile, artifacts = _resolve_prompt_artifacts(
        stage=stage,
        include_references=include_references,
        developer_override=developer_override,
        legacy_system_prompt=legacy_system_prompt,
    )
    blob = "\n\n".join(f"[{name}]\n{content.strip()}" for name, content in artifacts if content.strip())
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest() if blob else ""
    versions = sorted({_extract_prompt_version(content) for _, content in artifacts if content.strip()})
    if not versions:
        version = "unversioned"
    elif len(versions) == 1:
        version = versions[0]
    else:
        version = "composite:" + ",".join(versions)
    return {
        "prompt_profile": profile,
        "prompt_version": version,
        "prompt_hash_sha256": digest,
    }


def get_pipeline_prompt_signature(legacy_system_prompt: str | None = None) -> dict[str, str]:
    """Return pipeline-level prompt signature spanning stages 1-3."""
    stage_signatures = [
        get_prompt_signature(stage=stage, legacy_system_prompt=legacy_system_prompt)
        for stage in _PIPELINE_STAGES
    ]
    combined_blob = "\n".join(
        f"{stage}:{sig['prompt_hash_sha256']}"
        for stage, sig in zip(_PIPELINE_STAGES, stage_signatures)
    )
    combined_hash = hashlib.sha256(combined_blob.encode("utf-8")).hexdigest() if combined_blob else ""
    profiles = sorted({sig["prompt_profile"] for sig in stage_signatures})
    versions = sorted({sig["prompt_version"] for sig in stage_signatures})
    return {
        "prompt_profile": profiles[0] if len(profiles) == 1 else "composite:" + ",".join(profiles),
        "prompt_version": versions[0] if len(versions) == 1 else "composite:" + ",".join(versions),
        "prompt_hash_sha256": combined_hash,
    }


def validate_prompt_contract(
    legacy_system_prompt: str | None = None,
) -> list[str]:
    """
    Validate prompt compatibility contract before pipeline execution.

    Returns a list of validation errors. Empty list means compatible prompt set.
    """
    errors: list[str] = []

    if legacy_system_prompt and legacy_system_prompt.strip():
        legacy = legacy_system_prompt.strip()
        for marker in ("Etapa 1", "Etapa 2", "Etapa 3"):
            if marker.lower() not in legacy.lower():
                errors.append(f"Prompt legado sem marcador obrigatório: '{marker}'.")
        return errors
    if PROMPT_STRATEGY == "legacy":
        legacy = _load_legacy_system_prompt().strip()
        if not legacy:
            errors.append(
                "PROMPT_STRATEGY=legacy ativo, mas prompts/SYSTEM_PROMPT.md está ausente."
            )
            return errors
        for marker in ("Etapa 1", "Etapa 2", "Etapa 3"):
            if marker.lower() not in legacy.lower():
                errors.append(f"Prompt legado sem marcador obrigatório: '{marker}'.")
        return errors

    for component in _REQUIRED_PROMPT_COMPONENTS:
        content = get_prompt_component(component).strip()
        if not content:
            errors.append(f"Componente de prompt ausente: {component}.")
            continue

        required_markers = _REQUIRED_MARKERS_BY_COMPONENT.get(component, ())
        content_norm = content.lower()
        for marker in required_markers:
            if marker.lower() not in content_norm:
                errors.append(
                    f"Componente {component} sem marcador obrigatório: '{marker}'."
                )

    return errors


def ensure_prompt_contract(
    *,
    legacy_system_prompt: str | None = None,
    strict: bool = True,
) -> None:
    """Validate prompt contract and raise in strict mode."""
    errors = validate_prompt_contract(legacy_system_prompt=legacy_system_prompt)
    if not errors:
        return

    message = " ".join(errors)
    if strict:
        raise PromptConfigurationError(message)
    logger.warning("Prompt contract warnings: %s", message)


def build_messages(
    stage: str,
    user_text: str,
    extra_context: str | None = None,
    include_references: bool | None = None,
    developer_override: str | None = None,
    legacy_system_prompt: str | None = None,
) -> list[PromptMessage]:
    """
    Build chat messages dynamically for a pipeline stage.

    Strategy:
    - Always include system_base + dev_etapaX in modular mode.
    - Include referencias_longas only when required by stage/profile.
    - Fallback to legacy SYSTEM_PROMPT when modular files are missing.
    """
    stage_key = stage.lower().strip()
    user_content = _build_user_content(user_text, extra_context=extra_context)

    # If explicit legacy prompt is provided, keep full backward compatibility.
    if legacy_system_prompt and legacy_system_prompt.strip():
        logger.info("Prompt legado explícito aplicado para stage=%s", stage_key)
        return [
            {"role": "system", "content": legacy_system_prompt.strip()},
            {"role": "user", "content": user_content},
        ]
    if PROMPT_STRATEGY == "legacy":
        legacy = _load_legacy_system_prompt()
        if not legacy:
            raise PromptConfigurationError(
                "PROMPT_STRATEGY=legacy ativo, mas prompts/SYSTEM_PROMPT.md não foi encontrado."
            )
        logger.info("Prompt legado por estratégia aplicado para stage=%s", stage_key)
        return [
            {"role": "system", "content": legacy},
            {"role": "user", "content": user_content},
        ]

    system_base = get_prompt_component("system_base")
    dev_component = _STAGE_TO_DEV_COMPONENT.get(stage_key, "")
    stage_developer = developer_override or (get_prompt_component(dev_component) if dev_component else "")

    # Fallback: if components missing, use legacy monolithic prompt.
    if not system_base or not stage_developer:
        legacy = _load_legacy_system_prompt()
        if legacy:
            return [
                {"role": "system", "content": legacy},
                {"role": "user", "content": user_content},
            ]
        if not ALLOW_MINIMAL_PROMPT_FALLBACK:
            raise PromptConfigurationError(
                f"Prompt ausente para stage={stage_key}. "
                "Fallback minimalista bloqueado (ALLOW_MINIMAL_PROMPT_FALLBACK=false)."
            )
        logger.warning(
            "Fallback minimalista aplicado para stage=%s; "
            "configuração recomendada em produção é manter ALLOW_MINIMAL_PROMPT_FALLBACK=false.",
            stage_key,
        )
        return [
            {"role": "system", "content": MINIMAL_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    messages: list[PromptMessage] = [
        {"role": "system", "content": system_base},
        {"role": "developer", "content": stage_developer},
    ]

    use_references = _should_include_references(stage_key, include_references=include_references)
    if use_references:
        refs = get_prompt_component("referencias_longas")
        if refs:
            messages.append({"role": "developer", "content": refs})
            logger.info(
                "Prompt references injected: stage=%s, profile=%s, reason=%s",
                stage_key,
                PROMPT_PROFILE,
                "profile_full" if include_references is None else "forced",
            )
    else:
        logger.info(
            "Prompt references skipped: stage=%s, profile=%s, reason=%s",
            stage_key,
            PROMPT_PROFILE,
            "profile_lean_or_stage_not_required" if include_references is None else "forced_skip",
        )

    messages.append({"role": "user", "content": user_content})
    return messages
