"""Stage 1: Appeal petition analysis — structured data extraction."""

import json
import logging
import re

import tiktoken

from src.config import (
    CONTEXT_LIMIT_TOKENS,
    CONTEXT_WARNING_RATIO,
    ENABLE_CHUNKING,
    MAX_CONTEXT_TOKENS,
    TOKEN_BUDGET_RATIO,
)
from src.llm_client import chamar_llm, chamar_llm_json
from src.model_router import TaskType, get_model_for_task
from src.models import ResultadoEtapa1

logger = logging.getLogger("copilot_juridico")


# --- 3.3.3 Token estimation ---


def estimar_tokens(texto: str, modelo: str = "gpt-4o") -> int:
    """Estimate token count using tiktoken."""
    try:
        encoding = tiktoken.encoding_for_model(modelo)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(texto))


# --- 3.3.1 / 3.3.2 Context management ---


def _verificar_contexto(texto: str) -> str:
    """
    Check text size against context limit. Apply chunking if needed.

    Returns the text (possibly truncated with overlap) ready for LLM.
    """
    tokens_estimados = estimar_tokens(texto)
    limite_alerta = int(CONTEXT_LIMIT_TOKENS * CONTEXT_WARNING_RATIO)

    logger.info("Tokens estimados: %d (limite: %d)", tokens_estimados, CONTEXT_LIMIT_TOKENS)

    if tokens_estimados > limite_alerta:
        logger.warning(
            "⚠️  Texto excede %d%% do limite de contexto (%d/%d tokens). "
            "Aplicando truncamento com overlap.",
            int(CONTEXT_WARNING_RATIO * 100),
            tokens_estimados,
            CONTEXT_LIMIT_TOKENS,
        )
        # Truncate keeping ~70% of context limit (leave room for prompt + response)
        max_chars = int(len(texto) * (CONTEXT_LIMIT_TOKENS * 0.6 / tokens_estimados))
        overlap = min(2000, max_chars // 10)
        texto = texto[:max_chars]
        logger.info("Texto truncado para ~%d caracteres", len(texto))

    return texto


# --- 3.1.4 / 3.2 Parsing ---


def _parse_campo(texto: str, pattern: str, group: int = 1) -> str:
    """Extract a field from LLM response using regex."""
    match = re.search(pattern, texto, re.IGNORECASE | re.DOTALL)
    return match.group(group).strip() if match else ""


def _parse_numero_processo(texto: str) -> str:
    """3.2.1 — Extract case number."""
    # Pattern: Nº XXXXX-XX.XXXX.X.XX.XXXX or similar
    patterns = [
        r"N[ºo°]\s*([\d\.\-\/]+)",
        r"Processo[:\s]+([\d\.\-\/]+)",
        r"(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})",
    ]
    for p in patterns:
        result = _parse_campo(texto, p)
        if result:
            return result
    return ""


def _parse_nome(texto: str, marcador: str) -> str:
    """3.2.2 — Extract name after a section marker."""
    patterns = [
        rf"{marcador}[:\s]+\**([^\n\*]+)",
        rf"{marcador}[:\s–—-]+([^\n]+)",
    ]
    for p in patterns:
        result = _parse_campo(texto, p)
        if result:
            return result.strip("*").strip()
    return ""


def _parse_especie_recurso(texto: str) -> str:
    """3.2.3 — Extract appeal type."""
    patterns = [
        r"\[?(RECURSO\s+ESPECIAL(?:\s+C[IÍ]VEL)?|RECURSO\s+EXTRAORDIN[AÁ]RIO)\]?",
        r"Esp[ée]cie[:\s]+([^\n]+)",
    ]
    for p in patterns:
        result = _parse_campo(texto, p)
        if result:
            return result.strip("[]").strip()
    return ""


def _parse_permissivo(texto: str) -> str:
    """3.2.3 — Extract constitutional basis."""
    patterns = [
        r"[Pp]ermissivo[:\s]+([^\n]+)",
        r"(art\.\s*10[25],\s*III[^\n]*)",
        r"(artigo\s*10[25][^\n]*)",
    ]
    for p in patterns:
        result = _parse_campo(texto, p)
        if result:
            return result
    return ""


def _parse_dispositivos_violados(texto: str) -> list[str]:
    """3.2.4 — Extract list of violated legal provisions."""
    # Look for section with items
    section_match = re.search(
        r"[Dd]ispositivos?\s+[Vv]iolados?[:\s]*\n((?:.*\n)*?)(?:\n[A-Z]|\n\*\*|\Z)",
        texto,
    )
    if section_match:
        lines = section_match.group(1).strip().split("\n")
        items = []
        for line in lines:
            line = re.sub(r"^[\s\-\*•a-z\)]+", "", line).strip()
            # Only include lines that look like legal references
            if line and len(line) > 3 and re.search(r"art\.|lei|c[oó]digo|CF|CC|CPC|súmula", line, re.IGNORECASE):
                items.append(line)
        return items

    # Fallback: find individual article references
    matches = re.findall(r"(art\.\s*\d+[^\n,;]{0,60})", texto, re.IGNORECASE)
    return [m.strip() for m in matches[:20]] if matches else []


def _parse_flag(texto: str, campo: str) -> bool:
    """3.2.5 — Extract boolean flag (Sim/Não)."""
    pattern = rf"{campo}[:\s]+(Sim|Não|SIM|NÃO|sim|não|Yes|No)"
    match = re.search(pattern, texto, re.IGNORECASE)
    if match:
        return match.group(1).lower() in ("sim", "yes")
    return False


def _parse_resposta_llm(texto_resposta: str) -> ResultadoEtapa1:
    """Parse LLM response into structured ResultadoEtapa1."""
    return ResultadoEtapa1(
        numero_processo=_parse_numero_processo(texto_resposta),
        recorrente=_parse_nome(texto_resposta, "Recorrente"),
        recorrido=_parse_nome(texto_resposta, "Recorrido"),
        especie_recurso=_parse_especie_recurso(texto_resposta),
        permissivo_constitucional=_parse_permissivo(texto_resposta),
        camara_civel=_parse_nome(texto_resposta, "Câmara"),
        dispositivos_violados=_parse_dispositivos_violados(texto_resposta),
        justica_gratuita=_parse_flag(texto_resposta, "Justiça [Gg]ratuita"),
        efeito_suspensivo=_parse_flag(texto_resposta, "Efeito [Ss]uspensivo"),
        texto_formatado=texto_resposta,
    )


# --- 3.1.5 Validation ---


def _validar_campos(resultado: ResultadoEtapa1, texto_entrada: str) -> list[str]:
    """Validate that required fields are present. Return list of warnings."""
    alertas: list[str] = []

    campos_obrigatorios = {
        "numero_processo": resultado.numero_processo,
        "recorrente": resultado.recorrente,
        "especie_recurso": resultado.especie_recurso,
    }

    for campo, valor in campos_obrigatorios.items():
        if not valor:
            alertas.append(f"Campo obrigatório ausente: {campo}")
            logger.warning("⚠️  Campo '%s' não encontrado na resposta", campo)

    return alertas


# --- 3.1.6 Hallucination detection ---


def _detectar_alucinacao(resultado: ResultadoEtapa1, texto_entrada: str) -> list[str]:
    """Basic hallucination check: verify extracted data appears in input text."""
    alertas: list[str] = []

    # Check if process number appears in original text
    if resultado.numero_processo:
        # Normalize for comparison (remove formatting)
        num_limpo = re.sub(r"[\D]", "", resultado.numero_processo)
        texto_limpo = re.sub(r"[\D]", "", texto_entrada)
        if num_limpo not in texto_limpo and len(num_limpo) > 5:
            alertas.append(
                f"ALERTA: Número do processo '{resultado.numero_processo}' "
                f"não encontrado no texto de entrada"
            )

    # Check if recorrente name appears in original text
    if resultado.recorrente and len(resultado.recorrente) > 3:
        nome_upper = resultado.recorrente.upper()
        if nome_upper not in texto_entrada.upper():
            alertas.append(
                f"ALERTA: Recorrente '{resultado.recorrente}' "
                f"não encontrado no texto de entrada"
            )

    for alerta in alertas:
        logger.warning("🔍 Alucinação detectada: %s", alerta)

    return alertas


# --- 3.1.1 Main function ---


ETAPA1_USER_INSTRUCTION = (
    "Analise o documento de recurso a seguir e execute a Etapa 1 "
    "conforme instruções. Extraia todos os dados estruturados da "
    "petição do recurso.\n\n"
)


def executar_etapa1(
    texto_recurso: str,
    prompt_sistema: str,
    modelo_override: str | None = None,
) -> ResultadoEtapa1:
    """
    Execute Stage 1: extract structured data from appeal petition.

    Args:
        texto_recurso: Full text of the appeal petition.
        prompt_sistema: System prompt with general + Stage 1 rules.

    Returns:
        ResultadoEtapa1 with extracted fields and formatted text.
    """
    # 3.3 Context management
    tokens_pre = estimar_tokens(texto_recurso)
    texto_recurso = _verificar_contexto(texto_recurso)

    # 3.1.2 Mount user message
    user_message = ETAPA1_USER_INSTRUCTION + texto_recurso

    # 3.1.3 Call LLM (use hybrid model routing for legal analysis)
    if modelo_override:
        model = modelo_override
    else:
        model = get_model_for_task(TaskType.LEGAL_ANALYSIS)
    logger.info("🔄 Executando Etapa 1 — Análise da Petição do Recurso (modelo: %s)...", model)
    response = chamar_llm(
        system_prompt=prompt_sistema,
        user_message=user_message,
        model=model,
        max_tokens=2048,
    )

    # 3.3.4 Log estimated vs actual tokens
    logger.info(
        "Tokens — estimados: %d, reais: %d (prompt=%d, completion=%d)",
        tokens_pre,
        response.tokens.total_tokens,
        response.tokens.prompt_tokens,
        response.tokens.completion_tokens,
    )

    # 3.1.4 / 3.2 Parse response
    resultado = _parse_resposta_llm(response.content)

    # 3.1.5 Validate
    alertas_validacao = _validar_campos(resultado, texto_recurso)

    # 3.1.6 Hallucination check
    alertas_alucinacao = _detectar_alucinacao(resultado, texto_recurso)

    if alertas_validacao or alertas_alucinacao:
        logger.warning(
            "Etapa 1 concluída com %d alerta(s)",
            len(alertas_validacao) + len(alertas_alucinacao),
        )
    else:
        logger.info("✅ Etapa 1 concluída com sucesso")

    return resultado


# --- Chunking support (robust architecture) ---


def _merge_etapa1_results(resultados: list[ResultadoEtapa1]) -> ResultadoEtapa1:
    """
    Merge results from multiple chunks into a single ResultadoEtapa1.

    Strategy:
    - Unique fields (numero_processo, recorrente, etc.): use first non-empty value
    - List fields (dispositivos_violados): aggregate without duplicates
    - Boolean fields: OR logic (True if any chunk returns True)
    - texto_formatado: concatenate all chunks

    Args:
        resultados: List of ResultadoEtapa1 from each chunk.

    Returns:
        Merged ResultadoEtapa1.
    """
    if not resultados:
        return ResultadoEtapa1()

    if len(resultados) == 1:
        return resultados[0]

    logger.info("🔀 Mesclando resultados de %d chunks...", len(resultados))

    merged = ResultadoEtapa1()

    # Merge unique string fields (first non-empty wins)
    for r in resultados:
        if not merged.numero_processo and r.numero_processo:
            merged.numero_processo = r.numero_processo
        if not merged.recorrente and r.recorrente:
            merged.recorrente = r.recorrente
        if not merged.recorrido and r.recorrido:
            merged.recorrido = r.recorrido
        if not merged.especie_recurso and r.especie_recurso:
            merged.especie_recurso = r.especie_recurso
        if not merged.permissivo_constitucional and r.permissivo_constitucional:
            merged.permissivo_constitucional = r.permissivo_constitucional
        if not merged.camara_civel and r.camara_civel:
            merged.camara_civel = r.camara_civel

    # Merge list fields (aggregate without duplicates)
    seen_dispositivos = set()
    for r in resultados:
        for disp in r.dispositivos_violados:
            # Normalize for comparison
            disp_normalized = disp.strip().lower()
            if disp_normalized not in seen_dispositivos:
                seen_dispositivos.add(disp_normalized)
                merged.dispositivos_violados.append(disp)

    # Merge boolean fields (OR logic)
    merged.justica_gratuita = any(r.justica_gratuita for r in resultados)
    merged.efeito_suspensivo = any(r.efeito_suspensivo for r in resultados)

    # Concatenate formatted text
    merged.texto_formatado = "\n\n---\n\n".join(
        r.texto_formatado for r in resultados if r.texto_formatado
    )

    logger.info("✅ Resultados mesclados com sucesso")
    return merged


def executar_etapa1_com_chunking(
    texto_recurso: str,
    prompt_sistema: str,
) -> ResultadoEtapa1:
    """
    Execute Stage 1 with automatic chunking for large documents.

    If document fits in context limit, uses standard execution.
    Otherwise, splits into semantic chunks and merges results.

    Args:
        texto_recurso: Full text of the appeal petition.
        prompt_sistema: System prompt with general + Stage 1 rules.

    Returns:
        ResultadoEtapa1 with extracted fields and formatted text.
    """
    # Check if chunking is enabled
    if not ENABLE_CHUNKING:
        logger.debug("Chunking desabilitado — usando fluxo padrão")
        return executar_etapa1(texto_recurso, prompt_sistema)

    # Estimate tokens
    tokens_estimados = estimar_tokens(texto_recurso)
    limite_seguro = int(MAX_CONTEXT_TOKENS * TOKEN_BUDGET_RATIO)

    # If fits in one request, use standard flow
    if tokens_estimados <= limite_seguro:
        logger.debug("Documento cabe em uma requisição (%d tokens)", tokens_estimados)
        return executar_etapa1(texto_recurso, prompt_sistema)

    # Document is too large — apply chunking
    logger.warning(
        "⚠️  Documento grande detectado (%d tokens, limite: %d). Aplicando chunking inteligente...",
        tokens_estimados, limite_seguro,
    )

    # Import chunker (lazy to avoid circular imports)
    from src.token_manager import text_chunker

    chunks = text_chunker.chunk_text(texto_recurso, model="gpt-4o")
    logger.info("📦 Documento dividido em %d chunks. Processando...", len(chunks))

    resultados_parciais: list[ResultadoEtapa1] = []

    for i, chunk in enumerate(chunks, 1):
        logger.info("🔄 Processando chunk %d/%d...", i, len(chunks))

        try:
            resultado = executar_etapa1(chunk, prompt_sistema)
            resultados_parciais.append(resultado)

        except Exception as e:
            logger.error("❌ Erro ao processar chunk %d/%d: %s", i, len(chunks), e)
            # Continue processing remaining chunks
            continue

    if not resultados_parciais:
        raise RuntimeError("Nenhum chunk foi processado com sucesso")

    # Merge results
    resultado_final = _merge_etapa1_results(resultados_parciais)

    logger.info("✅ Etapa 1 concluída com chunking (%d chunks processados)", len(resultados_parciais))
    return resultado_final
