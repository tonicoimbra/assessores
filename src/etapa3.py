"""Stage 3: Draft generation — admissibility decision minute."""

import logging
import re

from src.config import (
    ENABLE_CHUNKING,
    MAX_CONTEXT_TOKENS,
    TOKEN_BUDGET_RATIO,
)
from src.etapa1 import estimar_tokens, _verificar_contexto
from src.llm_client import chamar_llm
from src.model_router import TaskType, get_model_for_task
from src.models import Decisao, ResultadoEtapa1, ResultadoEtapa2, ResultadoEtapa3

logger = logging.getLogger("copilot_juridico")


class Etapa3Error(Exception):
    """Raised when Stage 3 cannot proceed."""


# --- 5.1.4-5.1.7 Minute structure validation ---


def _validar_secoes(minuta: str) -> list[str]:
    """Validate that the draft contains required sections I, II, III."""
    alertas: list[str] = []

    secao_patterns = {
        "I": r"(?:Se[çc][ãa]o|Parte|Cap[ií]tulo)?\s*I\s*[–\-—:.]",
        "II": r"(?:Se[çc][ãa]o|Parte|Cap[ií]tulo)?\s*II\s*[–\-—:.]",
        "III": r"(?:Se[çc][ãa]o|Parte|Cap[ií]tulo)?\s*III\s*[–\-—:.]",
    }

    for secao, pattern in secao_patterns.items():
        if not re.search(pattern, minuta):
            alertas.append(f"Seção {secao} não encontrada na minuta")

    return alertas


def _validar_secao_i(minuta: str, resultado_etapa1: ResultadoEtapa1) -> list[str]:
    """5.1.5 — Verify section I reproduces Stage 1 data."""
    alertas: list[str] = []

    if resultado_etapa1.numero_processo and resultado_etapa1.numero_processo not in minuta:
        alertas.append(
            f"Seção I: número do processo '{resultado_etapa1.numero_processo}' ausente"
        )

    if resultado_etapa1.recorrente:
        if resultado_etapa1.recorrente.upper() not in minuta.upper():
            alertas.append(
                f"Seção I: recorrente '{resultado_etapa1.recorrente}' ausente"
            )

    if resultado_etapa1.especie_recurso:
        if resultado_etapa1.especie_recurso.upper() not in minuta.upper():
            alertas.append(
                f"Seção I: espécie do recurso '{resultado_etapa1.especie_recurso}' ausente"
            )

    return alertas


def _validar_secao_ii(minuta: str, resultado_etapa2: ResultadoEtapa2) -> list[str]:
    """5.1.6 — Verify section II contains themes with paraphrase + transcription."""
    alertas: list[str] = []

    if not resultado_etapa2.temas:
        return alertas

    # Check for at least one theme reference
    temas_encontrados = 0
    for tema in resultado_etapa2.temas:
        if tema.materia_controvertida:
            # Check if the theme's subject appears in the draft
            palavras_chave = tema.materia_controvertida.split()[:3]
            if any(p.upper() in minuta.upper() for p in palavras_chave if len(p) > 3):
                temas_encontrados += 1

    if temas_encontrados == 0:
        alertas.append("Seção II: nenhum tema da Etapa 2 encontrado na minuta")

    return alertas


def _validar_secao_iii(minuta: str) -> list[str]:
    """5.1.7 — Verify section III contains decision with reasoning."""
    alertas: list[str] = []

    decisao_patterns = [
        r"ADMITO",
        r"INADMITO",
        r"admito\s+o\s+recurso",
        r"inadmito\s+o\s+recurso",
        r"n[ãa]o\s+admito",
    ]

    has_decisao = any(re.search(p, minuta, re.IGNORECASE) for p in decisao_patterns)
    if not has_decisao:
        alertas.append("Seção III: decisão (admito/inadmito) não encontrada")

    return alertas


def _extrair_decisao(minuta: str) -> Decisao | None:
    """Extract the admissibility decision from the draft."""
    inadmito = re.search(
        r"(?:INADMITO|não\s+admito|inadmito\s+o\s+recurso)", minuta, re.IGNORECASE
    )
    admito = re.search(
        r"(?:(?<!IN)ADMITO|admito\s+o\s+recurso)", minuta, re.IGNORECASE
    )

    if inadmito:
        return Decisao.INADMITIDO
    if admito:
        return Decisao.ADMITIDO
    return None


# --- 5.2 Cross-validation (anti-hallucination) ---


def _validar_cruzada_dispositivos(
    minuta: str, resultado_etapa1: ResultadoEtapa1
) -> list[str]:
    """5.2.1 — Compare devices in section I with Stage 1."""
    alertas: list[str] = []

    for disp in resultado_etapa1.dispositivos_violados:
        # Extract article number for flexible matching
        num_match = re.search(r"\d+", disp)
        if num_match and num_match.group() not in minuta:
            alertas.append(f"Dispositivo '{disp}' da Etapa 1 ausente na minuta")

    return alertas


def _validar_cruzada_temas(
    minuta: str, resultado_etapa2: ResultadoEtapa2
) -> list[str]:
    """5.2.2 — Compare themes in section II with Stage 2."""
    alertas: list[str] = []

    for i, tema in enumerate(resultado_etapa2.temas, 1):
        if tema.materia_controvertida:
            palavras = [w for w in tema.materia_controvertida.split() if len(w) > 4][:2]
            if palavras and not any(p.upper() in minuta.upper() for p in palavras):
                alertas.append(f"Tema {i} da Etapa 2 possivelmente ausente na minuta")

    return alertas


def _validar_transcricoes(minuta: str, texto_acordao: str) -> list[str]:
    """5.2.3 — Verify literal transcription excerpts exist in ruling text."""
    alertas: list[str] = []

    # Find quoted text in the draft (potential transcriptions)
    quotes = re.findall(r'"([^"]{30,})"', minuta)
    for quote in quotes:
        # Check if the quoted text appears in the ruling
        clean_quote = quote.strip()[:100]
        if clean_quote not in texto_acordao:
            alertas.append(
                f"Transcrição não encontrada no acórdão: '{clean_quote[:60]}...'"
            )

    return alertas


def _validar_sumulas_secao_iii(
    minuta: str, resultado_etapa2: ResultadoEtapa2
) -> list[str]:
    """5.2.4 — Verify súmulas in section III match Stage 2."""
    alertas: list[str] = []

    # Extract all súmula references in the draft
    sumulas_minuta = set(re.findall(r"S[úu]mula\s+n?[ºo°]?\s*(\d+)", minuta, re.IGNORECASE))

    # Extract all súmulas from Stage 2
    sumulas_etapa2 = set()
    for tema in resultado_etapa2.temas:
        for obice in tema.obices_sumulas:
            nums = re.findall(r"(\d+)", obice)
            sumulas_etapa2.update(nums)

    # Check for new súmulas not in Stage 2
    novas = sumulas_minuta - sumulas_etapa2
    for s in novas:
        alertas.append(f"Súmula {s} na minuta não aparece na Etapa 2")

    return alertas


# --- 5.1.1 Main function ---


ETAPA3_USER_INSTRUCTION = (
    "Monte a minuta de admissibilidade conforme as instruções da Etapa 3.\n"
    "Use os dados das Etapas 1 e 2 abaixo. A minuta deve conter "
    "Seção I (Relatório), Seção II (Análise Temática) e Seção III (Decisão).\n\n"
)


def executar_etapa3(
    resultado_etapa1: ResultadoEtapa1,
    resultado_etapa2: ResultadoEtapa2,
    texto_acordao: str,
    prompt_sistema: str,
) -> ResultadoEtapa3:
    """
    Execute Stage 3: generate admissibility decision draft.

    Args:
        resultado_etapa1: Stage 1 results (appeal data).
        resultado_etapa2: Stage 2 results (thematic analysis).
        texto_acordao: Full ruling text (for transcription verification).
        prompt_sistema: System prompt with general + Stage 3 rules.

    Returns:
        ResultadoEtapa3 with complete draft and decision.
    """
    # Prerequisite validation
    if resultado_etapa2 is None or not resultado_etapa2.temas:
        raise Etapa3Error("Etapa 2 não executada ou sem temas. Execute a Etapa 2 antes.")

    # 5.1.2 — Mount user message
    etapa1_resumo = resultado_etapa1.texto_formatado or (
        f"Processo: {resultado_etapa1.numero_processo}\n"
        f"Recorrente: {resultado_etapa1.recorrente}\n"
        f"Recorrido: {resultado_etapa1.recorrido}\n"
        f"Espécie: {resultado_etapa1.especie_recurso}\n"
        f"Permissivo: {resultado_etapa1.permissivo_constitucional}\n"
        f"Dispositivos: {', '.join(resultado_etapa1.dispositivos_violados)}\n"
        f"Justiça Gratuita: {'Sim' if resultado_etapa1.justica_gratuita else 'Não'}\n"
        f"Efeito Suspensivo: {'Sim' if resultado_etapa1.efeito_suspensivo else 'Não'}\n"
    )

    etapa2_resumo = resultado_etapa2.texto_formatado or ""

    # Context management for ruling text
    texto_acordao_ctx = _verificar_contexto(texto_acordao)

    user_message = (
        ETAPA3_USER_INSTRUCTION
        + "--- RESULTADO DA ETAPA 1 ---\n"
        + etapa1_resumo
        + "\n\n--- RESULTADO DA ETAPA 2 ---\n"
        + etapa2_resumo
        + "\n\n--- TEXTO DO ACÓRDÃO (para transcrição) ---\n"
        + texto_acordao_ctx
    )

    # 5.1.3 — Call LLM (use hybrid model routing for draft generation)
    model = get_model_for_task(TaskType.DRAFT_GENERATION)
    logger.info("🔄 Executando Etapa 3 — Geração da Minuta de Admissibilidade (modelo: %s)...", model)
    tokens_pre = estimar_tokens(user_message)
    response = chamar_llm(
        system_prompt=prompt_sistema,
        user_message=user_message,
        model=model,
        max_tokens=4096,
    )

    logger.info(
        "Tokens — estimados: %d, reais: %d (prompt=%d, completion=%d)",
        tokens_pre,
        response.tokens.total_tokens,
        response.tokens.prompt_tokens,
        response.tokens.completion_tokens,
    )

    minuta = response.content

    # 5.1.4 — Validate structure
    alertas_secoes = _validar_secoes(minuta)

    # 5.1.5 — Validate section I
    alertas_secao_i = _validar_secao_i(minuta, resultado_etapa1)

    # 5.1.6 — Validate section II
    alertas_secao_ii = _validar_secao_ii(minuta, resultado_etapa2)

    # 5.1.7 — Validate section III
    alertas_secao_iii = _validar_secao_iii(minuta)

    # 5.2 — Cross-validation
    alertas_disp = _validar_cruzada_dispositivos(minuta, resultado_etapa1)
    alertas_temas = _validar_cruzada_temas(minuta, resultado_etapa2)
    alertas_transc = _validar_transcricoes(minuta, texto_acordao)
    alertas_sumulas = _validar_sumulas_secao_iii(minuta, resultado_etapa2)

    # Aggregate alerts
    todos_alertas = (
        alertas_secoes + alertas_secao_i + alertas_secao_ii + alertas_secao_iii
        + alertas_disp + alertas_temas + alertas_transc + alertas_sumulas
    )

    for alerta in todos_alertas:
        logger.warning("⚠️  %s", alerta)

    # Extract decision
    decisao = _extrair_decisao(minuta)

    resultado = ResultadoEtapa3(
        minuta_completa=minuta,
        decisao=decisao,
    )

    if todos_alertas:
        logger.warning("Etapa 3 concluída com %d alerta(s)", len(todos_alertas))
    else:
        logger.info("✅ Etapa 3 concluída — Decisão: %s", decisao.value if decisao else "N/A")

    return resultado


# --- Chunking support (robust architecture) ---


def _merge_etapa3_results(resultados: list[ResultadoEtapa3]) -> ResultadoEtapa3:
    """
    Merge results from multiple chunks into a single ResultadoEtapa3.

    Strategy:
    - Concatenate minutas from all chunks
    - Use decision from last chunk (most complete)
    - Add separators between chunks

    Args:
        resultados: List of ResultadoEtapa3 from each chunk.

    Returns:
        Merged ResultadoEtapa3.
    """
    if not resultados:
        return ResultadoEtapa3()

    if len(resultados) == 1:
        return resultados[0]

    logger.info("🔀 Mesclando minutas de %d chunks...", len(resultados))

    # Concatenate all minutas
    minutas_completas = []
    for i, r in enumerate(resultados, 1):
        if r.minuta_completa:
            minutas_completas.append(f"--- Chunk {i}/{len(resultados)} ---\n{r.minuta_completa}")

    minuta_final = "\n\n".join(minutas_completas)

    # Use decision from last chunk (most likely to have full context)
    decisao_final = resultados[-1].decisao

    # Count decisions to check consistency
    decisoes = [r.decisao for r in resultados if r.decisao]
    if decisoes:
        admitidos = sum(1 for d in decisoes if d == Decisao.ADMITIDO)
        inadmitidos = sum(1 for d in decisoes if d == Decisao.INADMITIDO)

        if admitidos > 0 and inadmitidos > 0:
            logger.warning(
                "⚠️  Decisões inconsistentes entre chunks: %d ADMITIDO, %d INADMITIDO",
                admitidos, inadmitidos,
            )
            # Use majority vote
            decisao_final = Decisao.ADMITIDO if admitidos > inadmitidos else Decisao.INADMITIDO

    resultado = ResultadoEtapa3(
        minuta_completa=minuta_final,
        decisao=decisao_final,
    )

    logger.info(
        "✅ Minutas mescladas de %d chunks — Decisão final: %s",
        len(resultados), decisao_final.value if decisao_final else "N/A",
    )
    return resultado


def executar_etapa3_com_chunking(
    resultado_etapa1: ResultadoEtapa1,
    resultado_etapa2: ResultadoEtapa2,
    texto_acordao: str,
    prompt_sistema: str,
) -> ResultadoEtapa3:
    """
    Execute Stage 3 with automatic chunking for large documents.

    If document fits in context limit, uses standard execution.
    Otherwise, splits acordao into semantic chunks and merges results.

    Args:
        resultado_etapa1: Stage 1 results (appeal data).
        resultado_etapa2: Stage 2 results (thematic analysis).
        texto_acordao: Full ruling text (for transcription verification).
        prompt_sistema: System prompt with general + Stage 3 rules.

    Returns:
        ResultadoEtapa3 with complete draft and decision.
    """
    # Check if chunking is enabled
    if not ENABLE_CHUNKING:
        logger.debug("Chunking desabilitado — usando fluxo padrão")
        return executar_etapa3(resultado_etapa1, resultado_etapa2, texto_acordao, prompt_sistema)

    # Prerequisite validation
    if resultado_etapa2 is None or not resultado_etapa2.temas:
        raise Etapa3Error("Etapa 2 não executada ou sem temas. Execute a Etapa 2 antes.")

    # Build context from etapas 1 and 2
    etapa1_resumo = resultado_etapa1.texto_formatado or (
        f"Processo: {resultado_etapa1.numero_processo}\n"
        f"Recorrente: {resultado_etapa1.recorrente}\n"
        f"Recorrido: {resultado_etapa1.recorrido}\n"
        f"Espécie: {resultado_etapa1.especie_recurso}\n"
        f"Permissivo: {resultado_etapa1.permissivo_constitucional}\n"
        f"Dispositivos: {', '.join(resultado_etapa1.dispositivos_violados)}\n"
        f"Justiça Gratuita: {'Sim' if resultado_etapa1.justica_gratuita else 'Não'}\n"
        f"Efeito Suspensivo: {'Sim' if resultado_etapa1.efeito_suspensivo else 'Não'}\n"
    )

    etapa2_resumo = resultado_etapa2.texto_formatado or ""

    # Estimate total context size
    context_base = (
        ETAPA3_USER_INSTRUCTION
        + "--- RESULTADO DA ETAPA 1 ---\n" + etapa1_resumo
        + "\n\n--- RESULTADO DA ETAPA 2 ---\n" + etapa2_resumo
        + "\n\n--- TEXTO DO ACÓRDÃO (para transcrição) ---\n"
    )

    tokens_context = estimar_tokens(context_base)
    tokens_acordao = estimar_tokens(texto_acordao)
    tokens_total = tokens_context + tokens_acordao
    limite_seguro = int(MAX_CONTEXT_TOKENS * TOKEN_BUDGET_RATIO)

    # If fits in one request, use standard flow
    if tokens_total <= limite_seguro:
        logger.debug("Documento cabe em uma requisição (%d tokens)", tokens_total)
        return executar_etapa3(resultado_etapa1, resultado_etapa2, texto_acordao, prompt_sistema)

    # Document is too large — apply chunking to acordao only
    logger.warning(
        "⚠️  Documento grande detectado (%d tokens, limite: %d). Aplicando chunking ao acórdão...",
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

    logger.info("📦 Acórdão dividido em %d chunks. Processando...", len(chunks))

    resultados_parciais: list[ResultadoEtapa3] = []

    for i, chunk in enumerate(chunks, 1):
        logger.info("🔄 Processando chunk %d/%d...", i, len(chunks))

        try:
            resultado = executar_etapa3(resultado_etapa1, resultado_etapa2, chunk, prompt_sistema)
            resultados_parciais.append(resultado)

        except Exception as e:
            logger.error("❌ Erro ao processar chunk %d/%d: %s", i, len(chunks), e)
            # Continue processing remaining chunks
            continue

    if not resultados_parciais:
        raise RuntimeError("Nenhum chunk foi processado com sucesso")

    # Merge results
    resultado_final = _merge_etapa3_results(resultados_parciais)

    logger.info(
        "✅ Etapa 3 concluída com chunking (%d chunks processados)",
        len(resultados_parciais),
    )
    return resultado_final
