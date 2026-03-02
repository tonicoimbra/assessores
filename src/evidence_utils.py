"""
Shared evidence utilities for Stages 1 and 2.

Centralizes deterministic text-matching and evidence-building logic
that was previously duplicated across etapa1.py and etapa2.py.
"""

from __future__ import annotations

import re

from src.models import CampoEvidencia


# ---------------------------------------------------------------------------
# Text searching
# ---------------------------------------------------------------------------


def find_span_case_insensitive(texto: str, termo: str) -> tuple[int, int] | None:
    """Find first case-insensitive span for term in text.

    Falls back to flexible whitespace matching when exact match fails.
    Returns (start, end) offsets or None.
    """
    termo_limpo = termo.strip()
    if not texto or not termo_limpo:
        return None

    match = re.search(re.escape(termo_limpo), texto, re.IGNORECASE)
    if match:
        return match.start(), match.end()

    # Flexible whitespace fallback
    termos = [t for t in termo_limpo.split() if t]
    if not termos:
        return None
    pattern = r"\s+".join(re.escape(t) for t in termos)
    match_flex = re.search(pattern, texto, re.IGNORECASE)
    if match_flex:
        return match_flex.start(), match_flex.end()
    return None


def inferir_pagina_por_posicao(texto: str, pos: int) -> int:
    """Infer page number by position using form-feed or explicit page markers."""
    if "\f" in texto:
        return texto.count("\f", 0, pos) + 1

    anteriores = texto[: pos + 1]
    marcadores = list(re.finditer(r"(?i)p[áa]gina\s+(\d{1,4})", anteriores))
    if marcadores:
        try:
            return max(1, int(marcadores[-1].group(1)))
        except ValueError:
            pass
    return 1


# ---------------------------------------------------------------------------
# Evidence generation
# ---------------------------------------------------------------------------


def gerar_evidencia_local(valor: str, texto_entrada: str) -> CampoEvidencia | None:
    """Generate deterministic evidence from source text for one field value.

    Extracts the surrounding line/context of the first occurrence and builds
    a :class:`CampoEvidencia` with citation, anchor, page, and offset.
    Returns ``None`` when the value is not found in the source text.
    """
    span = find_span_case_insensitive(texto_entrada, valor)
    if not span:
        return None

    inicio, fim = span
    linha_inicio = texto_entrada.rfind("\n", 0, inicio) + 1
    linha_fim = texto_entrada.find("\n", fim)
    if linha_fim == -1:
        linha_fim = len(texto_entrada)

    citacao = texto_entrada[linha_inicio:linha_fim].strip()
    if not citacao:
        citacao = texto_entrada[inicio:fim].strip()
    if len(citacao) > 280:
        contexto_inicio = max(0, inicio - 80)
        contexto_fim = min(len(texto_entrada), fim + 80)
        citacao = re.sub(r"\s+", " ", texto_entrada[contexto_inicio:contexto_fim]).strip()

    ancora_inicio = max(0, inicio - 60)
    ancora_fim = min(len(texto_entrada), fim + 60)
    ancora = re.sub(r"\s+", " ", texto_entrada[ancora_inicio:ancora_fim]).strip()[:180]

    return CampoEvidencia(
        citacao_literal=citacao,
        pagina=inferir_pagina_por_posicao(texto_entrada, inicio),
        ancora=ancora,
        offset_inicio=inicio,
    )


def merge_evidencia(
    existing: CampoEvidencia | None,
    generated: CampoEvidencia,
) -> CampoEvidencia:
    """Merge existing and generated evidence, preferring explicit (existing) values."""
    if existing is None:
        return generated
    return CampoEvidencia(
        citacao_literal=existing.citacao_literal or generated.citacao_literal,
        pagina=existing.pagina or generated.pagina,
        ancora=existing.ancora or generated.ancora,
        offset_inicio=(
            existing.offset_inicio
            if existing.offset_inicio is not None
            else generated.offset_inicio
        ),
    )


# ---------------------------------------------------------------------------
# JSON normalization helpers
# ---------------------------------------------------------------------------


def normalizar_int(value: object) -> int | None:
    """Normalize integer-like values from a JSON payload."""
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def normalizar_bool(value: object) -> bool:
    """Normalize boolean-like values from a JSON payload."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    return text in {"sim", "true", "1", "yes"}


def normalizar_campo_texto(value: object) -> str:
    """Normalize text fields and map known placeholders to empty string."""
    text = str(value or "").strip()
    if not text:
        return ""
    placeholder = text.upper().replace("Ã", "A")
    if placeholder in {"[NAO CONSTA NO DOCUMENTO]", "[NÃO CONSTA NO DOCUMENTO]", "N/A", "NA"}:
        return ""
    return text


def normalizar_evidencia(value: object) -> CampoEvidencia | None:
    """Normalize one evidence dict from a structured JSON payload."""
    if not isinstance(value, dict):
        return None

    citacao = normalizar_campo_texto(value.get("citacao_literal"))
    ancora = normalizar_campo_texto(value.get("ancora"))
    pagina_raw = normalizar_int(value.get("pagina"))
    offset_raw = normalizar_int(value.get("offset_inicio"))

    pagina = pagina_raw if pagina_raw and pagina_raw > 0 else None
    offset_inicio = offset_raw if offset_raw is not None and offset_raw >= 0 else None

    if not citacao and not ancora and pagina is None and offset_inicio is None:
        return None

    return CampoEvidencia(
        citacao_literal=citacao,
        pagina=pagina,
        ancora=ancora,
        offset_inicio=offset_inicio,
    )


def normalizar_evidencias_campos(payload: object) -> dict[str, CampoEvidencia]:
    """Normalize ``evidencias_campos`` mapping from a structured JSON payload."""
    if not isinstance(payload, dict):
        return {}

    evidencias: dict[str, CampoEvidencia] = {}
    for campo, raw in payload.items():
        evidencia = normalizar_evidencia(raw)
        campo_norm = str(campo).strip()
        if evidencia and campo_norm:
            evidencias[campo_norm] = evidencia
    return evidencias
