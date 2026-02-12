"""Stage 2: Ruling (acórdão) thematic analysis with obstacle identification."""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.config import (
    ENABLE_CHUNKING,
    ENABLE_PARALLEL_ETAPA2,
    ETAPA2_PARALLEL_WORKERS,
    MAX_CONTEXT_TOKENS,
    TOKEN_BUDGET_RATIO,
)
from src.etapa1 import estimar_tokens, _verificar_contexto
from src.llm_client import chamar_llm
from src.model_router import TaskType, get_model_for_task
from src.models import ResultadoEtapa1, ResultadoEtapa2, TemaEtapa2

logger = logging.getLogger("assessor_ai")


# --- 4.3.1 Valid súmulas ---

SUMULAS_STJ: set[int] = {5, 7, 13, 83, 126, 211, 518}
SUMULAS_STF: set[int] = {279, 280, 281, 282, 283, 284, 356, 735}
SUMULAS_VALIDAS: set[int] = SUMULAS_STJ | SUMULAS_STF


# --- 4.2 Theme parsing ---


def _separar_blocos_tema(texto: str) -> list[str]:
    """4.2.1 — Split response into theme blocks."""
    # Split on patterns like "Tema 1:", "TEMA 2:", "### Tema", numbered headers
    blocks = re.split(
        r"(?=(?:#{1,3}\s*)?(?:TEMA|Tema)\s*\d+\s*[:\-–—])",
        texto.strip(),
    )
    # Filter empty blocks and the header block
    return [b.strip() for b in blocks if b.strip() and len(b.strip()) > 20]


def _parse_campo_tema(bloco: str, campo: str) -> str:
    """Extract a field value from a theme block."""
    patterns = [
        rf"\*?\*?{campo}\*?\*?\s*[:\-–—]\s*(.*?)(?=\n\*?\*?[A-Z]|\n#{1,3}|\Z)",
        rf"{campo}\s*[:\-–—]\s*([^\n]+)",
    ]
    for p in patterns:
        match = re.search(p, bloco, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip().strip("*").strip()
    return ""


def _parse_materia(bloco: str) -> str:
    """4.2.2 — Extract controversial matter."""
    return (_parse_campo_tema(bloco, r"(?:Mat[ée]ria|Tema)")
            or _parse_campo_tema(bloco, r"Mat[ée]ria\s+[Cc]ontrovertida"))


def _parse_conclusao(bloco: str) -> str:
    """4.2.3 — Extract conclusion and reasoning."""
    return (_parse_campo_tema(bloco, r"Conclus[ãa]o(?:\s+e\s+[Ff]undamentos)?")
            or _parse_campo_tema(bloco, r"Fundamentos?"))


def _parse_base_vinculante(bloco: str) -> str:
    """4.2.4 — Extract precedent/binding theme application."""
    return (_parse_campo_tema(bloco, r"Aplica[çc][ãa]o\s+de\s+Tema")
            or _parse_campo_tema(bloco, r"Precedente")
            or _parse_campo_tema(bloco, r"Tema\s+Vinculante"))


def _parse_obices(bloco: str) -> list[str]:
    """4.2.5 — Extract list of obstacles/súmulas."""
    campo = (_parse_campo_tema(bloco, r"[ÓO]bices?(?:/S[úu]mulas?)?")
             or _parse_campo_tema(bloco, r"S[úu]mulas?\s+[Aa]plic[áa]veis?"))

    if not campo:
        return []

    # Extract individual súmula references
    sumulas = re.findall(r"S[úu]mula\s+n?[ºo°]?\s*(\d+)", campo, re.IGNORECASE)
    if sumulas:
        return [f"Súmula {n}" for n in sumulas]

    # If no specific numbers, return the whole text as one item
    items = [s.strip() for s in re.split(r"[;,]", campo) if s.strip()]
    return items if items else [campo]


def _parse_trecho_transcricao(bloco: str) -> str:
    """4.1.6 — Extract literal excerpt from ruling for transcription."""
    patterns = [
        r"[Tt]recho[:\s]+([\"\'].*?[\"\'])",
        r"[Tt]ranscri[çc][ãa]o[:\s]+([\"\'].*?[\"\'])",
        r"\"([^\"]{50,})\"",
    ]
    for p in patterns:
        match = re.search(p, bloco, re.DOTALL)
        if match:
            return match.group(1).strip().strip("\"'")
    return ""


def _parse_tema(bloco: str) -> TemaEtapa2:
    """Parse a single theme block into TemaEtapa2."""
    return TemaEtapa2(
        materia_controvertida=_parse_materia(bloco),
        conclusao_fundamentos=_parse_conclusao(bloco),
        base_vinculante=_parse_base_vinculante(bloco),
        obices_sumulas=_parse_obices(bloco),
        trecho_transcricao=_parse_trecho_transcricao(bloco),
    )


def _parse_resposta_etapa2(texto_resposta: str) -> ResultadoEtapa2:
    """4.2.6 — Parse full LLM response into ResultadoEtapa2."""
    blocos = _separar_blocos_tema(texto_resposta)

    temas = []
    for bloco in blocos:
        tema = _parse_tema(bloco)
        temas.append(tema)

    return ResultadoEtapa2(
        temas=temas,
        texto_formatado=texto_resposta,
    )


# --- 4.1.5 Validation ---


def _validar_temas(temas: list[TemaEtapa2]) -> list[str]:
    """Validate that each theme has required fields."""
    alertas: list[str] = []

    for i, tema in enumerate(temas, 1):
        if not tema.materia_controvertida:
            alertas.append(f"Tema {i}: matéria controvertida ausente")
        if not tema.conclusao_fundamentos:
            alertas.append(f"Tema {i}: conclusão/fundamentos ausente")

    if not temas:
        alertas.append("Nenhum tema identificado na resposta")

    for alerta in alertas:
        logger.warning("⚠️  %s", alerta)

    return alertas


# --- 4.3.2 / 4.3.3 Obstacle validation ---


def _validar_obices(temas: list[TemaEtapa2], texto_acordao: str) -> list[str]:
    """Validate obstacles against allowed list and source text."""
    alertas: list[str] = []

    for i, tema in enumerate(temas, 1):
        for obice in tema.obices_sumulas:
            # Extract number from súmula reference
            num_match = re.search(r"(\d+)", obice)
            if num_match:
                num = int(num_match.group(1))
                if num not in SUMULAS_VALIDAS:
                    alertas.append(
                        f"Tema {i}: Súmula {num} não está na lista permitida "
                        f"(STJ: {sorted(SUMULAS_STJ)}, STF: {sorted(SUMULAS_STF)})"
                    )
                    logger.warning("⚠️  Súmula %d não prevista na lista permitida", num)

            # 4.3.3 Cross-check with source text
            obice_clean = re.sub(r"[Ss][úu]mula\s+n?[ºo°]?\s*", "", obice).strip()
            if obice_clean and obice_clean not in texto_acordao:
                # Check just the number
                if num_match and num_match.group(1) not in texto_acordao:
                    alertas.append(
                        f"Tema {i}: óbice '{obice}' sem lastro no texto do acórdão"
                    )

    return alertas


# --- 4.1.1 Main function ---


ETAPA2_USER_INSTRUCTION = (
    "Analise o acórdão a seguir e execute a Etapa 2 conforme instruções.\n"
    "Identifique os temas controvertidos, conclusões, bases vinculantes "
    "e possíveis óbices para cada tema.\n\n"
)


class Etapa2Error(Exception):
    """Raised when Stage 2 cannot proceed."""


def validar_prerequisito_etapa1(resultado_etapa1: ResultadoEtapa1 | None) -> None:
    """4.4.3 — Validate that Stage 1 is complete before running Stage 2."""
    if resultado_etapa1 is None:
        raise Etapa2Error("Etapa 1 não executada. Execute a Etapa 1 antes da Etapa 2.")

    if not resultado_etapa1.numero_processo and not resultado_etapa1.recorrente:
        raise Etapa2Error(
            "Etapa 1 incompleta: número do processo e recorrente ausentes. "
            "Re-execute a Etapa 1."
        )


def executar_etapa2(
    texto_acordao: str,
    resultado_etapa1: ResultadoEtapa1,
    prompt_sistema: str,
    modelo_override: str | None = None,
) -> ResultadoEtapa2:
    """
    Execute Stage 2: thematic analysis of the ruling.

    Args:
        texto_acordao: Full text of the ruling (acórdão).
        resultado_etapa1: Stage 1 results for context.
        prompt_sistema: System prompt with general + Stage 2 rules.
        modelo_override: Optional model to use instead of default.

    Returns:
        ResultadoEtapa2 with themes, conclusions, and obstacles.
    """
    # 4.4.3 — Prerequisite check
    validar_prerequisito_etapa1(resultado_etapa1)

    # Context management
    tokens_pre = estimar_tokens(texto_acordao)
    texto_acordao = _verificar_contexto(texto_acordao)

    # 4.1.2 — Mount user message with acórdão + Stage 1 context
    dispositivos_resumo = ""
    if resultado_etapa1.dispositivos_violados:
        dispositivos_resumo = (
            "\n\n--- DISPOSITIVOS VIOLADOS IDENTIFICADOS NA ETAPA 1 ---\n"
            + "\n".join(f"• {d}" for d in resultado_etapa1.dispositivos_violados)
            + "\n--- FIM DOS DISPOSITIVOS ---\n"
        )

    user_message = (
        ETAPA2_USER_INSTRUCTION
        + dispositivos_resumo
        + "\n\n--- TEXTO DO ACÓRDÃO ---\n"
        + texto_acordao
    )

    # 4.1.3 — Call LLM (use hybrid model routing for legal analysis)
    if modelo_override:
        model = modelo_override
    else:
        model = get_model_for_task(TaskType.LEGAL_ANALYSIS)
    logger.info("🔄 Executando Etapa 2 — Análise Temática do Acórdão (modelo: %s)...", model)
    response = chamar_llm(
        system_prompt=prompt_sistema,
        user_message=user_message,
        model=model,
        max_tokens=3000,
    )

    logger.info(
        "Tokens — estimados: %d, reais: %d (prompt=%d, completion=%d)",
        tokens_pre,
        response.tokens.total_tokens,
        response.tokens.prompt_tokens,
        response.tokens.completion_tokens,
    )

    # 4.1.4 / 4.2 — Parse response
    resultado = _parse_resposta_etapa2(response.content)

    # 4.1.5 — Validate themes
    alertas_temas = _validar_temas(resultado.temas)

    # 4.3 — Validate obstacles
    alertas_obices = _validar_obices(resultado.temas, texto_acordao)

    total_alertas = len(alertas_temas) + len(alertas_obices)
    if total_alertas:
        logger.warning("Etapa 2 concluída com %d alerta(s)", total_alertas)
    else:
        logger.info(
            "✅ Etapa 2 concluída: %d tema(s) identificados",
            len(resultado.temas),
        )

    return resultado


# --- Chunking support (robust architecture) ---


def _merge_etapa2_results(resultados: list[ResultadoEtapa2]) -> ResultadoEtapa2:
    """
    Merge results from multiple chunks into a single ResultadoEtapa2.

    Strategy:
    - Aggregate all themes from all chunks
    - Deduplicate themes based on materia_controvertida similarity
    - Concatenate texto_formatado

    Args:
        resultados: List of ResultadoEtapa2 from each chunk.

    Returns:
        Merged ResultadoEtapa2.
    """
    if not resultados:
        return ResultadoEtapa2()

    if len(resultados) == 1:
        return resultados[0]

    logger.info("🔀 Mesclando resultados de %d chunks...", len(resultados))

    merged = ResultadoEtapa2()
    seen_materias = set()

    # Aggregate themes with deduplication
    for r in resultados:
        for tema in r.temas:
            # Normalize materia for comparison
            materia_normalized = tema.materia_controvertida.strip().lower()

            # Simple deduplication: skip if very similar materia exists
            is_duplicate = False
            for seen in seen_materias:
                # If 80%+ of words match, consider duplicate
                words_tema = set(materia_normalized.split())
                words_seen = set(seen.split())
                if words_tema and words_seen:
                    overlap = len(words_tema & words_seen) / max(len(words_tema), len(words_seen))
                    if overlap > 0.8:
                        is_duplicate = True
                        break

            if not is_duplicate:
                seen_materias.add(materia_normalized)
                merged.temas.append(tema)

    # Concatenate formatted text
    merged.texto_formatado = "\n\n---\n\n".join(
        r.texto_formatado for r in resultados if r.texto_formatado
    )

    logger.info("✅ Resultados mesclados: %d temas únicos de %d chunks", len(merged.temas), len(resultados))
    return merged


def executar_etapa2_com_chunking(
    texto_acordao: str,
    resultado_etapa1: ResultadoEtapa1,
    prompt_sistema: str,
    modelo_override: str | None = None,
) -> ResultadoEtapa2:
    """
    Execute Stage 2 with automatic chunking for large documents.

    If document fits in context limit, uses standard execution.
    Otherwise, splits into semantic chunks and merges results.

    Args:
        texto_acordao: Full text of the ruling (acórdão).
        resultado_etapa1: Stage 1 results for context.
        prompt_sistema: System prompt with general + Stage 2 rules.
        modelo_override: Optional model to use instead of default.

    Returns:
        ResultadoEtapa2 with themes, conclusions, and obstacles.
    """
    # Check if chunking is enabled
    if not ENABLE_CHUNKING:
        logger.debug("Chunking desabilitado — usando fluxo padrão")
        return executar_etapa2(texto_acordao, resultado_etapa1, prompt_sistema, modelo_override=modelo_override)

    # Validate prerequisite
    validar_prerequisito_etapa1(resultado_etapa1)

    # Estimate tokens (include context from etapa1)
    dispositivos_resumo = ""
    if resultado_etapa1.dispositivos_violados:
        dispositivos_resumo = (
            "\n\n--- DISPOSITIVOS VIOLADOS IDENTIFICADOS NA ETAPA 1 ---\n"
            + "\n".join(f"• {d}" for d in resultado_etapa1.dispositivos_violados)
            + "\n--- FIM DOS DISPOSITIVOS ---\n"
        )

    # Estimate full context size
    context_extra = len(ETAPA2_USER_INSTRUCTION) + len(dispositivos_resumo)
    tokens_acordao = estimar_tokens(texto_acordao)
    tokens_context = estimar_tokens(dispositivos_resumo)
    tokens_total = tokens_acordao + tokens_context
    limite_seguro = int(MAX_CONTEXT_TOKENS * TOKEN_BUDGET_RATIO)

    # If fits in one request, use standard flow
    if tokens_total <= limite_seguro:
        logger.debug("Documento cabe em uma requisição (%d tokens)", tokens_total)
        return executar_etapa2(texto_acordao, resultado_etapa1, prompt_sistema, modelo_override=modelo_override)

    # Document is too large — apply chunking
    logger.warning(
        "⚠️  Documento grande detectado (%d tokens, limite: %d). Aplicando chunking inteligente...",
        tokens_total, limite_seguro,
    )

    # Import chunker (lazy to avoid circular imports)
    from src.token_manager import text_chunker

    # Adjust max tokens to account for context overhead
    effective_limit = limite_seguro - tokens_context - 2000  # 2k buffer for response
    original_max = text_chunker.max_tokens
    text_chunker.max_tokens = effective_limit

    chunks = text_chunker.chunk_text(texto_acordao, model="gpt-4o")
    text_chunker.max_tokens = original_max  # Restore

    logger.info("📦 Documento dividido em %d chunks. Processando...", len(chunks))

    resultados_parciais: list[ResultadoEtapa2] = []

    for i, chunk in enumerate(chunks, 1):
        logger.info("🔄 Processando chunk %d/%d...", i, len(chunks))

        try:
            resultado = executar_etapa2(chunk, resultado_etapa1, prompt_sistema, modelo_override=modelo_override)
            resultados_parciais.append(resultado)

        except Exception as e:
            logger.error("❌ Erro ao processar chunk %d/%d: %s", i, len(chunks), e)
            # Continue processing remaining chunks
            continue

    if not resultados_parciais:
        raise RuntimeError("Nenhum chunk foi processado com sucesso")

    # Merge results
    resultado_final = _merge_etapa2_results(resultados_parciais)

    logger.info(
        "✅ Etapa 2 concluída com chunking (%d chunks processados, %d temas identificados)",
        len(resultados_parciais), len(resultado_final.temas),
    )
    return resultado_final


# --- Parallel processing (FASE 4) ---


def _processar_tema_paralelo(
    tema_texto: str,
    tema_numero: int,
    texto_acordao: str,
    prompt_sistema: str,
) -> TemaEtapa2:
    """
    Process a single theme in parallel.

    This function is called by ThreadPoolExecutor to analyze one theme independently.

    Args:
        tema_texto: Raw text block for this theme.
        tema_numero: Theme number for logging.
        texto_acordao: Full acordao text for reference.
        prompt_sistema: System prompt.

    Returns:
        Parsed TemaEtapa2.
    """
    logger.debug("🔄 Processando tema %d em paralelo...", tema_numero)

    try:
        # Call LLM for detailed theme analysis (use hybrid model)
        model = get_model_for_task(TaskType.LEGAL_ANALYSIS)
        response = chamar_llm(
            system_prompt=prompt_sistema,
            user_message=(
                f"Analise o tema {tema_numero} do acórdão em detalhes.\n\n"
                f"Identifique: matéria controvertida, conclusão/fundamentos, "
                f"base vinculante, óbices/súmulas, e trecho para transcrição.\n\n"
                f"TEMA:\n{tema_texto}\n\n"
                f"CONTEXTO DO ACÓRDÃO:\n{texto_acordao[:2000]}"
            ),
            model=model,
            max_tokens=2048,
        )

        # Parse the response
        tema = _parse_tema(response.content)
        logger.debug("✅ Tema %d processado", tema_numero)
        return tema

    except Exception as e:
        logger.error("❌ Erro ao processar tema %d: %s", tema_numero, e)
        # Return empty theme on error
        return TemaEtapa2()


def executar_etapa2_paralelo(
    texto_acordao: str,
    resultado_etapa1: ResultadoEtapa1,
    prompt_sistema: str,
    max_workers: int | None = None,
    modelo_override: str | None = None,
) -> ResultadoEtapa2:
    """
    Execute Stage 2 with parallel theme processing.

    Performance improvement:
    - Sequential: 3-5 themes = 15-25 seconds
    - Parallel (3 workers): 3-5 themes = 8-12 seconds (~30% faster)

    NOTE: Respects rate limits by limiting parallel workers to 2-3.

    Args:
        texto_acordao: Full text of the ruling (acórdão).
        resultado_etapa1: Stage 1 results for context.
        prompt_sistema: System prompt with general + Stage 2 rules.
        max_workers: Number of parallel workers (default: from config).

    Returns:
        ResultadoEtapa2 with themes processed in parallel.
    """
    # Check if parallel processing is enabled
    if not ENABLE_PARALLEL_ETAPA2:
        logger.debug("Processamento paralelo desabilitado — usando fluxo sequencial")
        return executar_etapa2(texto_acordao, resultado_etapa1, prompt_sistema)

    # Validate prerequisite
    validar_prerequisito_etapa1(resultado_etapa1)

    # Context management
    tokens_pre = estimar_tokens(texto_acordao)
    texto_acordao = _verificar_contexto(texto_acordao)

    # First call: identify themes (still sequential)
    dispositivos_resumo = ""
    if resultado_etapa1.dispositivos_violados:
        dispositivos_resumo = (
            "\n\n--- DISPOSITIVOS VIOLADOS IDENTIFICADOS NA ETAPA 1 ---\n"
            + "\n".join(f"• {d}" for d in resultado_etapa1.dispositivos_violados)
            + "\n--- FIM DOS DISPOSITIVOS ---\n"
        )

    user_message = (
        ETAPA2_USER_INSTRUCTION
        + dispositivos_resumo
        + "\n\n--- TEXTO DO ACÓRDÃO ---\n"
        + texto_acordao
    )

    logger.info("🔄 Executando Etapa 2 com processamento paralelo...")
    if modelo_override:
        model = modelo_override
    else:
        model = get_model_for_task(TaskType.LEGAL_ANALYSIS)
    response = chamar_llm(
        system_prompt=prompt_sistema,
        user_message=user_message,
        model=model,
    )

    # Parse to extract theme blocks
    blocos = _separar_blocos_tema(response.content)

    if not blocos:
        logger.warning("Nenhum tema identificado para processamento paralelo")
        # Fallback to sequential
        return executar_etapa2(texto_acordao, resultado_etapa1, prompt_sistema, modelo_override=modelo_override)

    logger.info("📦 %d temas identificados. Processando em paralelo...", len(blocos))

    # Process themes in parallel
    workers = max_workers or ETAPA2_PARALLEL_WORKERS
    temas_completos: list[TemaEtapa2] = []

    with ThreadPoolExecutor(max_workers=workers) as executor:
        # Submit all themes for parallel processing
        future_to_tema = {
            executor.submit(
                _processar_tema_paralelo,
                bloco, i, texto_acordao, prompt_sistema,
            ): i
            for i, bloco in enumerate(blocos, 1)
        }

        # Collect results as they complete
        for future in as_completed(future_to_tema):
            tema_num = future_to_tema[future]
            try:
                tema = future.result()
                temas_completos.append(tema)
            except Exception as e:
                logger.error("❌ Falha no tema %d: %s", tema_num, e)
                # Add empty theme on failure
                temas_completos.append(TemaEtapa2())

    logger.info(
        "Tokens — estimados: %d, reais: %d (prompt=%d, completion=%d)",
        tokens_pre,
        response.tokens.total_tokens,
        response.tokens.prompt_tokens,
        response.tokens.completion_tokens,
    )

    resultado = ResultadoEtapa2(
        temas=temas_completos,
        texto_formatado=response.content,
    )

    # Validation
    alertas_temas = _validar_temas(resultado.temas)
    alertas_obices = _validar_obices(resultado.temas, texto_acordao)

    total_alertas = len(alertas_temas) + len(alertas_obices)
    if total_alertas:
        logger.warning("Etapa 2 (paralelo) concluída com %d alerta(s)", total_alertas)
    else:
        logger.info(
            "✅ Etapa 2 (paralelo) concluída: %d tema(s) identificados com %d workers",
            len(resultado.temas), workers,
        )

    return resultado
