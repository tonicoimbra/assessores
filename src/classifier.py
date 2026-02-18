"""Document classification: heuristic-first, LLM fallback."""

import logging
import re
from dataclasses import dataclass

from src.models import ClassificationAudit, DocumentoEntrada, TipoDocumento

logger = logging.getLogger("assessor_ai")


class DocumentClassificationError(Exception):
    """Raised when classified document set violates required invariants."""


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

CHEAP_VERIFIER_RECURSO_PATTERNS: list[str] = [
    r"recurso\s+especial",
    r"recurso\s+extraordin[aá]rio",
    r"raz[oõ]es\s+recursais",
    r"art\.\s*105\s*,\s*iii",
    r"art\.\s*102\s*,\s*iii",
]

CHEAP_VERIFIER_ACORDAO_PATTERNS: list[str] = [
    r"ac[óo]rd[aã]o",
    r"ementa",
    r"acordam",
    r"vistos\s*,\s*relatados",
    r"c[aâ]mara\s+c[ií]vel",
]

# Confidence threshold for heuristic classification
HEURISTIC_CONFIDENCE_THRESHOLD: float = 0.7
COMPOSITE_WEIGHT_HEURISTIC: float = 0.55
COMPOSITE_WEIGHT_LLM: float = 0.35
COMPOSITE_WEIGHT_VERIFIER: float = 0.10
COMPOSITE_MIN_CONFIDENCE: float = 0.55
COMPOSITE_MIN_MARGIN: float = 0.12
COMPOSITE_STRONG_CONFLICT_CONFIDENCE: float = 0.75

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
    heuristic_score_recurso: float = 0.0
    heuristic_score_acordao: float = 0.0
    matched_recurso_patterns: list[str] | None = None
    matched_acordao_patterns: list[str] | None = None
    evidence_snippets: list[str] | None = None
    llm_model: str = ""
    llm_tipo_raw: str = ""
    llm_confianca_raw: float | None = None
    verifier_tipo: TipoDocumento | None = None
    verifier_confidence: float = 0.0
    verifier_ok: bool = True
    verifier_reason: str = ""
    composite_score_recurso: float = 0.0
    composite_score_acordao: float = 0.0
    decision_margin: float = 0.0
    consistency_score: float = 1.0
    consistency_flags: list[str] | None = None


def _clamp01(value: float) -> float:
    """Clamp floating point value into [0, 1]."""
    return max(0.0, min(1.0, float(value)))


def _normalizar_scores_heuristicos(
    resultado_heuristica: ClassificationResult,
) -> tuple[float, float]:
    """Normalize heuristic class scores, including mocked/legacy payloads."""
    score_recurso = _clamp01(resultado_heuristica.heuristic_score_recurso)
    score_acordao = _clamp01(resultado_heuristica.heuristic_score_acordao)

    if score_recurso == score_acordao and resultado_heuristica.tipo != TipoDocumento.DESCONHECIDO:
        conf = _clamp01(resultado_heuristica.confianca)
        if resultado_heuristica.tipo == TipoDocumento.RECURSO:
            score_recurso = conf
            score_acordao = 1.0 - conf
        elif resultado_heuristica.tipo == TipoDocumento.ACORDAO:
            score_acordao = conf
            score_recurso = 1.0 - conf

    if resultado_heuristica.tipo == TipoDocumento.DESCONHECIDO:
        # Heurística inconclusiva não deve neutralizar totalmente o sinal do LLM.
        score_recurso = max(0.5, score_recurso)
        score_acordao = max(0.5, score_acordao)

    return score_recurso, score_acordao


def _score_binario_por_tipo(
    tipo_predito: TipoDocumento,
    confianca: float,
    tipo_alvo: TipoDocumento,
) -> float:
    """Convert class prediction into deterministic score for one target label."""
    conf = _clamp01(confianca)
    if tipo_predito == TipoDocumento.DESCONHECIDO:
        return 0.5
    if tipo_predito == tipo_alvo:
        return conf
    return 1.0 - conf


def _aplicar_score_composto(
    resultado_heuristica: ClassificationResult,
    resultado_base: ClassificationResult,
    resultado_llm: ClassificationResult | None,
) -> ClassificationResult:
    """Apply deterministic composed scoring from heuristics, LLM and consistency rules."""
    heur_score_recurso, heur_score_acordao = _normalizar_scores_heuristicos(resultado_heuristica)
    heuristic_weight = (
        COMPOSITE_WEIGHT_HEURISTIC
        if resultado_heuristica.tipo != TipoDocumento.DESCONHECIDO
        else 0.25
    )

    componentes_recurso: list[tuple[float, float]] = [(heuristic_weight, heur_score_recurso)]
    componentes_acordao: list[tuple[float, float]] = [(heuristic_weight, heur_score_acordao)]

    if resultado_llm is not None:
        componentes_recurso.append(
            (
                COMPOSITE_WEIGHT_LLM,
                _score_binario_por_tipo(
                    resultado_llm.tipo,
                    resultado_llm.confianca,
                    TipoDocumento.RECURSO,
                ),
            )
        )
        componentes_acordao.append(
            (
                COMPOSITE_WEIGHT_LLM,
                _score_binario_por_tipo(
                    resultado_llm.tipo,
                    resultado_llm.confianca,
                    TipoDocumento.ACORDAO,
                ),
            )
        )

    if (
        resultado_base.verifier_tipo is not None
        and resultado_base.verifier_tipo != TipoDocumento.DESCONHECIDO
    ):
        componentes_recurso.append(
            (
                COMPOSITE_WEIGHT_VERIFIER,
                _score_binario_por_tipo(
                    resultado_base.verifier_tipo,
                    resultado_base.verifier_confidence,
                    TipoDocumento.RECURSO,
                ),
            )
        )
        componentes_acordao.append(
            (
                COMPOSITE_WEIGHT_VERIFIER,
                _score_binario_por_tipo(
                    resultado_base.verifier_tipo,
                    resultado_base.verifier_confidence,
                    TipoDocumento.ACORDAO,
                ),
            )
        )

    total_peso = max(sum(peso for peso, _ in componentes_recurso), 1e-9)
    score_composto_recurso = round(
        sum(peso * score for peso, score in componentes_recurso) / total_peso,
        3,
    )
    score_composto_acordao = round(
        sum(peso * score for peso, score in componentes_acordao) / total_peso,
        3,
    )
    margem_decisao = round(abs(score_composto_recurso - score_composto_acordao), 3)

    tipo_vencedor = (
        TipoDocumento.RECURSO
        if score_composto_recurso >= score_composto_acordao
        else TipoDocumento.ACORDAO
    )
    confianca_vencedor = (
        score_composto_recurso
        if tipo_vencedor == TipoDocumento.RECURSO
        else score_composto_acordao
    )

    consistency_flags: list[str] = []
    checks = 0
    checks_ok = 0

    if (
        resultado_llm is not None
        and resultado_llm.tipo != TipoDocumento.DESCONHECIDO
        and resultado_heuristica.tipo != TipoDocumento.DESCONHECIDO
    ):
        checks += 1
        if resultado_llm.tipo == resultado_heuristica.tipo:
            checks_ok += 1
        elif (
            resultado_llm.confianca >= COMPOSITE_STRONG_CONFLICT_CONFIDENCE
            and resultado_heuristica.confianca >= COMPOSITE_STRONG_CONFLICT_CONFIDENCE
        ):
            consistency_flags.append("strong_heuristic_llm_conflict")

    if (
        resultado_base.verifier_tipo is not None
        and resultado_base.verifier_tipo != TipoDocumento.DESCONHECIDO
    ):
        checks += 1
        if resultado_base.verifier_tipo == tipo_vencedor:
            checks_ok += 1

    consistency_score = round(checks_ok / checks, 3) if checks else 1.0

    if not resultado_base.verifier_ok:
        consistency_flags.append("crosscheck_conflict")
    if confianca_vencedor < COMPOSITE_MIN_CONFIDENCE:
        consistency_flags.append("low_composite_confidence")
    if margem_decisao < COMPOSITE_MIN_MARGIN:
        consistency_flags.append("low_composite_margin")

    if consistency_flags:
        resultado_base.tipo = TipoDocumento.DESCONHECIDO
        resultado_base.confianca = min(_clamp01(confianca_vencedor), 0.49)
    else:
        resultado_base.tipo = tipo_vencedor
        resultado_base.confianca = _clamp01(confianca_vencedor)

    if "score_composto" not in resultado_base.metodo:
        resultado_base.metodo = f"{resultado_base.metodo}+score_composto".strip("+")
    resultado_base.composite_score_recurso = score_composto_recurso
    resultado_base.composite_score_acordao = score_composto_acordao
    resultado_base.decision_margin = margem_decisao
    resultado_base.consistency_score = consistency_score
    resultado_base.consistency_flags = consistency_flags
    return resultado_base


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


def _match_patterns_with_evidence(
    texto: str,
    patterns: list[str],
) -> tuple[list[str], list[str]]:
    """Return matched patterns and short evidence snippets for audit."""
    trecho = texto[:5000]
    matched_patterns: list[str] = []
    snippets: list[str] = []

    for pattern in patterns:
        match = re.search(pattern, trecho, re.IGNORECASE)
        if not match:
            continue

        matched_patterns.append(pattern)
        snippet = re.sub(r"\s+", " ", match.group(0)).strip()[:120]
        if snippet and snippet not in snippets:
            snippets.append(snippet)

    return matched_patterns, snippets


def _classificar_por_heuristica(texto: str) -> ClassificationResult:
    """Classify document using text pattern heuristics."""
    score_recurso = _calcular_score_heuristico(texto, RECURSO_PATTERNS)
    score_acordao = _calcular_score_heuristico(texto, ACORDAO_PATTERNS)
    recurso_patterns, recurso_snippets = _match_patterns_with_evidence(
        texto,
        RECURSO_PATTERNS,
    )
    acordao_patterns, acordao_snippets = _match_patterns_with_evidence(
        texto,
        ACORDAO_PATTERNS,
    )
    evidence_snippets = list(dict.fromkeys((recurso_snippets + acordao_snippets)[:8]))

    logger.debug(
        "Heurística: score_recurso=%.2f, score_acordao=%.2f",
        score_recurso, score_acordao,
    )

    if score_recurso > score_acordao and score_recurso >= HEURISTIC_CONFIDENCE_THRESHOLD:
        return ClassificationResult(
            tipo=TipoDocumento.RECURSO,
            confianca=score_recurso,
            metodo="heuristica",
            heuristic_score_recurso=score_recurso,
            heuristic_score_acordao=score_acordao,
            matched_recurso_patterns=recurso_patterns,
            matched_acordao_patterns=acordao_patterns,
            evidence_snippets=evidence_snippets,
        )

    if score_acordao > score_recurso and score_acordao >= HEURISTIC_CONFIDENCE_THRESHOLD:
        return ClassificationResult(
            tipo=TipoDocumento.ACORDAO,
            confianca=score_acordao,
            metodo="heuristica",
            heuristic_score_recurso=score_recurso,
            heuristic_score_acordao=score_acordao,
            matched_recurso_patterns=recurso_patterns,
            matched_acordao_patterns=acordao_patterns,
            evidence_snippets=evidence_snippets,
        )

    # Inconclusive
    return ClassificationResult(
        tipo=TipoDocumento.DESCONHECIDO,
        confianca=max(score_recurso, score_acordao),
        metodo="heuristica",
        heuristic_score_recurso=score_recurso,
        heuristic_score_acordao=score_acordao,
        matched_recurso_patterns=recurso_patterns,
        matched_acordao_patterns=acordao_patterns,
        evidence_snippets=evidence_snippets,
    )


def _classificar_por_verificador_barato(texto: str) -> tuple[TipoDocumento, float, str]:
    """Run a cheap cross-check validator for document type."""
    trecho = texto[:5000]
    hits_recurso = sum(
        1 for pattern in CHEAP_VERIFIER_RECURSO_PATTERNS
        if re.search(pattern, trecho, re.IGNORECASE)
    )
    hits_acordao = sum(
        1 for pattern in CHEAP_VERIFIER_ACORDAO_PATTERNS
        if re.search(pattern, trecho, re.IGNORECASE)
    )

    total = max(len(CHEAP_VERIFIER_RECURSO_PATTERNS), len(CHEAP_VERIFIER_ACORDAO_PATTERNS), 1)
    if hits_recurso == 0 and hits_acordao == 0:
        return TipoDocumento.DESCONHECIDO, 0.0, "sem_indicios_no_verificador_barato"

    diff = hits_recurso - hits_acordao
    if abs(diff) <= 1:
        confidence = round(max(hits_recurso, hits_acordao) / total, 3)
        return TipoDocumento.DESCONHECIDO, confidence, "indicios_ambiguos_no_verificador_barato"

    if diff > 1:
        confidence = round(min(1.0, hits_recurso / total), 3)
        return TipoDocumento.RECURSO, confidence, f"verificador_barato_hits_recurso={hits_recurso}"

    confidence = round(min(1.0, hits_acordao / total), 3)
    return TipoDocumento.ACORDAO, confidence, f"verificador_barato_hits_acordao={hits_acordao}"


def _aplicar_validacao_cruzada_barata(
    texto: str,
    resultado: ClassificationResult,
) -> ClassificationResult:
    """Apply cheap cross-check and downgrade conflicting classifications."""
    verifier_tipo, verifier_confidence, verifier_reason = _classificar_por_verificador_barato(texto)
    resultado.verifier_tipo = verifier_tipo
    resultado.verifier_confidence = verifier_confidence
    resultado.verifier_reason = verifier_reason

    if resultado.tipo == TipoDocumento.DESCONHECIDO:
        resultado.verifier_ok = True
        return resultado

    if verifier_tipo == TipoDocumento.DESCONHECIDO:
        resultado.verifier_ok = True
        return resultado

    if verifier_tipo == resultado.tipo:
        resultado.verifier_ok = True
        return resultado

    resultado.verifier_ok = False
    logger.warning(
        "⚠️  Divergência na validação cruzada da classificação: principal=%s verificador=%s",
        resultado.tipo.value,
        verifier_tipo.value,
    )
    tipo_principal = resultado.tipo
    resultado.tipo = TipoDocumento.DESCONHECIDO
    resultado.confianca = min(resultado.confianca, 0.49)
    resultado.metodo = f"{resultado.metodo}+crosscheck"
    resultado.verifier_reason = (
        f"conflito_principal_{tipo_principal.value}_vs_{verifier_tipo.value}".lower()
    )
    return resultado


def _classificar_por_llm(texto: str) -> ClassificationResult:
    """Classify document using LLM as fallback (uses gpt-4o-mini for cost savings)."""
    from src.llm_client import LLMError, chamar_llm_json
    from src.model_router import TaskType, get_model_for_task

    trecho = texto[:2000]

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
            llm_model=model,
            llm_tipo_raw=tipo_str,
            llm_confianca_raw=confianca,
        )

    except LLMError as e:
        logger.error("Falha na classificação por LLM: %s", e)
        return ClassificationResult(
            tipo=TipoDocumento.DESCONHECIDO,
            confianca=0.0,
            metodo="llm",
            llm_model=model,
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
    resultado_heuristica = _classificar_por_heuristica(texto)
    resultado_llm: ClassificationResult | None = None
    resultado_base: ClassificationResult

    if resultado_heuristica.tipo != TipoDocumento.DESCONHECIDO:
        resultado_base = _aplicar_validacao_cruzada_barata(texto, resultado_heuristica)
        resultado_final = _aplicar_score_composto(resultado_heuristica, resultado_base, None)
        logger.info(
            "📋 Classificação (heurística): %s (confiança: %.2f)",
            resultado_final.tipo.value, resultado_final.confianca,
        )
        return resultado_final

    # Fallback to LLM
    logger.info(
        "Heurística inconclusiva (%.2f). Usando LLM...",
        resultado_heuristica.confianca,
    )
    resultado_llm = _classificar_por_llm(texto)
    resultado_llm.heuristic_score_recurso = resultado_heuristica.heuristic_score_recurso
    resultado_llm.heuristic_score_acordao = resultado_heuristica.heuristic_score_acordao
    resultado_llm.matched_recurso_patterns = resultado_heuristica.matched_recurso_patterns
    resultado_llm.matched_acordao_patterns = resultado_heuristica.matched_acordao_patterns
    resultado_llm.evidence_snippets = resultado_heuristica.evidence_snippets
    resultado_base = _aplicar_validacao_cruzada_barata(texto, resultado_llm)
    resultado_final = _aplicar_score_composto(resultado_heuristica, resultado_base, resultado_llm)

    logger.info(
        "📋 Classificação (LLM): %s (confiança: %.2f)",
        resultado_final.tipo.value, resultado_final.confianca,
    )
    return resultado_final


def classificar_documentos(
    documentos: list[DocumentoEntrada],
    *,
    strict: bool = False,
    require_exactly_one_recurso: bool = True,
    min_acordaos: int = 1,
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
        doc.classification_audit = ClassificationAudit(
            method=resultado.metodo,
            confidence=resultado.confianca,
            heuristic_score_recurso=resultado.heuristic_score_recurso,
            heuristic_score_acordao=resultado.heuristic_score_acordao,
            matched_recurso_patterns=resultado.matched_recurso_patterns or [],
            matched_acordao_patterns=resultado.matched_acordao_patterns or [],
            evidence_snippets=resultado.evidence_snippets or [],
            llm_model=resultado.llm_model,
            llm_tipo_raw=resultado.llm_tipo_raw,
            llm_confianca_raw=resultado.llm_confianca_raw,
            verifier_tipo=(resultado.verifier_tipo.value if resultado.verifier_tipo else ""),
            verifier_confidence=resultado.verifier_confidence,
            verifier_ok=resultado.verifier_ok,
            verifier_reason=resultado.verifier_reason,
            composite_score_recurso=resultado.composite_score_recurso,
            composite_score_acordao=resultado.composite_score_acordao,
            decision_margin=resultado.decision_margin,
            consistency_score=resultado.consistency_score,
            consistency_flags=resultado.consistency_flags or [],
        )
        logger.info(
            "🧾 Classificação auditada — arquivo=%s tipo=%s método=%s conf=%.2f "
            "score_r=%.2f score_a=%.2f comp_r=%.2f comp_a=%.2f margem=%.2f evidências=%d",
            doc.filepath,
            doc.tipo.value,
            doc.classification_audit.method,
            doc.classification_audit.confidence,
            doc.classification_audit.heuristic_score_recurso,
            doc.classification_audit.heuristic_score_acordao,
            doc.classification_audit.composite_score_recurso,
            doc.classification_audit.composite_score_acordao,
            doc.classification_audit.decision_margin,
            len(doc.classification_audit.evidence_snippets),
        )

    recursos, acordaos, desconhecidos = validar_classificacao_documentos(
        documentos,
        strict=strict,
        require_exactly_one_recurso=require_exactly_one_recurso,
        min_acordaos=min_acordaos,
    )

    logger.info(
        "Classificação concluída: %d recurso(s), %d acórdão(s), %d desconhecido(s)",
        recursos,
        acordaos,
        desconhecidos,
    )

    return documentos


def validar_classificacao_documentos(
    documentos: list[DocumentoEntrada],
    *,
    strict: bool = False,
    require_exactly_one_recurso: bool = True,
    min_acordaos: int = 1,
) -> tuple[int, int, int]:
    """
    Validate classified document invariants.

    Returns:
        Tuple (recursos, acordaos, desconhecidos).

    Raises:
        DocumentClassificationError: when strict=True and invariants are violated.
    """
    recursos = sum(1 for d in documentos if d.tipo == TipoDocumento.RECURSO)
    acordaos = sum(1 for d in documentos if d.tipo == TipoDocumento.ACORDAO)
    desconhecidos = len(documentos) - recursos - acordaos

    erros: list[str] = []

    if require_exactly_one_recurso:
        if recursos == 0:
            erros.append("Nenhum RECURSO identificado.")
        elif recursos > 1:
            erros.append(f"Foram identificados {recursos} RECURSOS; esperado exatamente 1.")
    elif recursos == 0:
        erros.append("Nenhum RECURSO identificado.")

    if acordaos < min_acordaos:
        erros.append(
            f"Foram identificados {acordaos} ACÓRDÃOS; esperado ao menos {min_acordaos}."
        )

    if erros:
        for erro in erros:
            logger.warning("⚠️  %s", erro)
        if strict:
            raise DocumentClassificationError(" ".join(erros))

    return recursos, acordaos, desconhecidos


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
