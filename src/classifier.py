"""Document classification: heuristic-first, LLM fallback."""

import logging
import re
from dataclasses import dataclass

from src.models import DocumentoEntrada, TipoDocumento

logger = logging.getLogger("assessor_ai")


# Heuristic patterns
RECURSO_PATTERNS: list[str] = [
    r"PROJUDI\s*[-–—]\s*Recurso",
    r"Recurso\s+Especial",
    r"Recurso\s+Extraordin[aá]rio",
    r"raz[oõ]es\s+recursais",
    r"art\.\s*105\s*,\s*III",
    r"art\.\s*102\s*,\s*III",
    r"interposi[cç][aã]o\s+de\s+recurso",
    r"petição\s+de\s+recurso",
]

ACORDAO_PATTERNS: list[str] = [
    r"AC[OÓ]RD[AÃ]O",
    r"Vistos\s*,\s*relatados\s+e\s+discutidos",
    r"C[aâ]mara\s+C[ií]vel",
    r"EMENTA",
    r"ACORDAM",
    r"Rel(?:ator|atora)\s*:",
    r"TRIBUNAL\s+DE\s+JUSTI[CÇ]A",
]

# Confidence threshold for heuristic classification
HEURISTIC_CONFIDENCE_THRESHOLD: float = 0.7

# LLM classification prompt
CLASSIFICATION_PROMPT: str = """Você é um classificador de documentos jurídicos.
Analise o texto e classifique como RECURSO ou ACORDAO.

RECURSO = Petição de recurso especial ou extraordinário (razões recursais)
ACORDAO = Acórdão, decisão colegiada do tribunal

Responda APENAS com JSON:
{"tipo": "RECURSO" ou "ACORDAO", "confianca": 0.0 a 1.0}"""


@dataclass
class ClassificationResult:
    """Result of document classification."""

    tipo: TipoDocumento
    confianca: float
    metodo: str  # "heuristica" or "llm"


def _calcular_score_heuristico(
    texto: str,
    patterns: list[str],
) -> float:
    """Calculate heuristic confidence score based on pattern matches."""
    if not texto:
        return 0.0

    # Search in first 5000 chars for efficiency
    trecho = texto[:5000].upper()
    matches = sum(
        1 for pattern in patterns
        if re.search(pattern, trecho, re.IGNORECASE)
    )

    total = len(patterns)
    return min(matches / max(total * 0.3, 1), 1.0)


def _classificar_por_heuristica(texto: str) -> ClassificationResult:
    """Classify document using text pattern heuristics."""
    score_recurso = _calcular_score_heuristico(texto, RECURSO_PATTERNS)
    score_acordao = _calcular_score_heuristico(texto, ACORDAO_PATTERNS)

    logger.debug(
        "Heurística: score_recurso=%.2f, score_acordao=%.2f",
        score_recurso, score_acordao,
    )

    if score_recurso > score_acordao and score_recurso >= HEURISTIC_CONFIDENCE_THRESHOLD:
        return ClassificationResult(
            tipo=TipoDocumento.RECURSO,
            confianca=score_recurso,
            metodo="heuristica",
        )

    if score_acordao > score_recurso and score_acordao >= HEURISTIC_CONFIDENCE_THRESHOLD:
        return ClassificationResult(
            tipo=TipoDocumento.ACORDAO,
            confianca=score_acordao,
            metodo="heuristica",
        )

    # Inconclusive
    return ClassificationResult(
        tipo=TipoDocumento.DESCONHECIDO,
        confianca=max(score_recurso, score_acordao),
        metodo="heuristica",
    )


def _classificar_por_llm(texto: str) -> ClassificationResult:
    """Classify document using LLM as fallback (uses gpt-4o-mini for cost savings)."""
    from src.llm_client import LLMError, chamar_llm_json
    from src.model_router import TaskType, get_model_for_task

    trecho = texto[:2000]

    # Use cost-effective model for classification
    model = get_model_for_task(TaskType.CLASSIFICATION)

    try:
        result = chamar_llm_json(
            system_prompt=CLASSIFICATION_PROMPT,
            user_message=f"Classifique este documento:\n\n{trecho}",
            temperature=0.0,
            max_tokens=100,
            model=model,  # Use gpt-4o-mini (83% cheaper than gpt-4o)
        )

        tipo_str = result.get("tipo", "").upper()
        confianca = float(result.get("confianca", 0.0))

        if tipo_str == "RECURSO":
            tipo = TipoDocumento.RECURSO
        elif tipo_str == "ACORDAO":
            tipo = TipoDocumento.ACORDAO
        else:
            tipo = TipoDocumento.DESCONHECIDO

        return ClassificationResult(
            tipo=tipo,
            confianca=confianca,
            metodo="llm",
        )

    except LLMError as e:
        logger.error("Falha na classificação por LLM: %s", e)
        return ClassificationResult(
            tipo=TipoDocumento.DESCONHECIDO,
            confianca=0.0,
            metodo="llm",
        )


def classificar_documento(texto: str) -> ClassificationResult:
    """
    Classify a document as RECURSO or ACORDAO.

    Uses text heuristics first. Falls back to LLM if confidence < 0.7.

    Args:
        texto: Extracted document text.

    Returns:
        ClassificationResult with tipo, confidence, and method used.
    """
    # Try heuristics first
    resultado = _classificar_por_heuristica(texto)

    if resultado.tipo != TipoDocumento.DESCONHECIDO:
        logger.info(
            "📋 Classificação (heurística): %s (confiança: %.2f)",
            resultado.tipo.value, resultado.confianca,
        )
        return resultado

    # Fallback to LLM
    logger.info("Heurística inconclusiva (%.2f). Usando LLM...", resultado.confianca)
    resultado = _classificar_por_llm(texto)

    logger.info(
        "📋 Classificação (LLM): %s (confiança: %.2f)",
        resultado.tipo.value, resultado.confianca,
    )
    return resultado


def classificar_documentos(
    documentos: list[DocumentoEntrada],
) -> list[DocumentoEntrada]:
    """
    Classify multiple documents and update their tipo field.

    Also validates that at least 1 RECURSO was found.

    Args:
        documentos: List of DocumentoEntrada to classify.

    Returns:
        Same list with tipo field updated.
    """
    for doc in documentos:
        resultado = classificar_documento(doc.texto_extraido)
        doc.tipo = resultado.tipo

    # Validation: at least 1 RECURSO
    recursos = [d for d in documentos if d.tipo == TipoDocumento.RECURSO]
    acordaos = [d for d in documentos if d.tipo == TipoDocumento.ACORDAO]

    if not recursos:
        logger.warning(
            "⚠️  Nenhum RECURSO identificado entre os %d documento(s). "
            "Verifique se os PDFs corretos foram fornecidos.",
            len(documentos),
        )

    if not acordaos:
        logger.warning(
            "⚠️  Nenhum ACÓRDÃO identificado entre os %d documento(s). "
            "A Etapa 2 requer um acórdão.",
            len(documentos),
        )

    logger.info(
        "Classificação concluída: %d recurso(s), %d acórdão(s), %d desconhecido(s)",
        len(recursos), len(acordaos),
        len(documentos) - len(recursos) - len(acordaos),
    )

    return documentos


def agrupar_documentos(
    documentos: list[DocumentoEntrada],
) -> dict[TipoDocumento, list[DocumentoEntrada]]:
    """
    Group classified documents by type.

    Args:
        documentos: List of classified DocumentoEntrada.

    Returns:
        Dict mapping TipoDocumento to list of documents.
    """
    grupos: dict[TipoDocumento, list[DocumentoEntrada]] = {
        TipoDocumento.RECURSO: [],
        TipoDocumento.ACORDAO: [],
        TipoDocumento.DESCONHECIDO: [],
    }

    for doc in documentos:
        grupos[doc.tipo].append(doc)

    return grupos
