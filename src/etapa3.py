"""Stage 3: Draft generation — admissibility decision minute."""

import logging
import re

from src.config import (
    ENABLE_CHUNKING,
    MAX_TOKENS_ETAPA3,
    MAX_TOKENS_INTERMEDIATE,
    MAX_CONTEXT_TOKENS,
    TOKEN_BUDGET_RATIO,
)
from src.etapa1 import estimar_tokens, _verificar_contexto
from src.llm_client import chamar_llm, chamar_llm_json
from src.model_router import TaskType, get_model_for_task
from src.models import Decisao, ResultadoEtapa1, ResultadoEtapa2, ResultadoEtapa3
from src.prompt_loader import build_messages

logger = logging.getLogger("assessor_ai")

INCONCLUSIVO_WARNING_TEXT = "Decisão jurídica inconclusiva: Requer análise adicional."
MOTIVO_BLOQUEIO_E3_INCONCLUSIVO = "E3_INCONCLUSIVO"
ETAPA3_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "minuta_completa": {"type": "string"},
        "decisao": {"type": "string", "enum": ["ADMITIDO", "INADMITIDO", "INCONCLUSIVO"]},
        "fundamentos_decisao": {"type": "array", "items": {"type": "string"}},
        "itens_evidencia_usados": {"type": "array", "items": {"type": "string"}},
        "aviso_inconclusivo": {"type": "boolean"},
        "motivo_bloqueio_codigo": {"type": "string"},
        "motivo_bloqueio_descricao": {"type": "string"},
    },
    "required": ["minuta_completa", "decisao"],
    "additionalProperties": True,
}


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
        r"INCONCLUSIV",
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
    inconclusivo = re.search(r"inconclusiv", minuta, re.IGNORECASE)
    inadmito = re.search(
        r"(?:INADMITO|não\s+admito|inadmito\s+o\s+recurso)", minuta, re.IGNORECASE
    )
    admito = re.search(
        r"(?:(?<!IN)ADMITO|admito\s+o\s+recurso)", minuta, re.IGNORECASE
    )

    if inconclusivo:
        return Decisao.INCONCLUSIVO
    if inadmito:
        return Decisao.INADMITIDO
    if admito:
        return Decisao.ADMITIDO
    return None


_OBICES_FORTES_INADMISSIBILIDADE = {
    "5", "7", "13", "83", "126", "211", "518",
    "279", "280", "281", "282", "283", "284", "356", "735",
}

_MARCADORES_INADMISSIBILIDADE = (
    "não conhecido",
    "nao conhecido",
    "não conhecimento",
    "nao conhecimento",
    "inadmiss",
    "não admit",
    "nao admit",
)

_MARCADORES_ADMISSIBILIDADE_REGEX = (
    r"\brecurso\s+conhecid[oa]\b",
    r"\bconhecimento\s+do\s+recurso\b",
    r"\badmit[eo]\s+o\s+recurso\b",
    r"\badmitid[oa]\b",
    r"\bju[ií]zo\s+positivo\s+de\s+admissibilidade\b",
)

_PRECEDENCIA_CONFLITO_EVIDENCIAS = (
    "óbice sumular forte > lastro mínimo etapa 1 ausente > conclusão textual contraditória"
)


def _extrair_numeros_sumulas(resultado_etapa2: ResultadoEtapa2) -> set[str]:
    """Extract all súmula numbers from Stage 2 obstacles."""
    numeros: set[str] = set()
    for tema in resultado_etapa2.temas:
        for obice in tema.obices_sumulas:
            numeros.update(re.findall(r"(\d+)", obice))
    return numeros


def _normalizar_texto_decisao(texto: str) -> str:
    """Normalize decision text for marker matching."""
    return (texto or "").lower()


def _detectar_marcadores_inadmissibilidade(texto: str) -> list[str]:
    """Detect inadmissibility markers in conclusions text."""
    texto_norm = _normalizar_texto_decisao(texto)
    return [m for m in _MARCADORES_INADMISSIBILIDADE if m in texto_norm]


def _detectar_marcadores_admissibilidade(texto: str) -> list[str]:
    """Detect admissibility markers in conclusions text."""
    encontrados: list[str] = []
    for pattern in _MARCADORES_ADMISSIBILIDADE_REGEX:
        if re.search(pattern, texto, re.IGNORECASE):
            encontrados.append(pattern)
    return encontrados


def _decidir_admissibilidade_deterministica(
    resultado_etapa1: ResultadoEtapa1,
    resultado_etapa2: ResultadoEtapa2,
) -> tuple[Decisao, list[str]]:
    """
    Determine admissibility using deterministic rules from Stage 1 + Stage 2.

    This decision is authoritative; LLM is used only to draft the minute.
    """
    fundamentos: list[str] = []
    if resultado_etapa2 is None or not resultado_etapa2.temas:
        fundamentos.append("Etapa 2 sem temas válidos para decisão conclusiva.")
        return Decisao.INCONCLUSIVO, fundamentos

    conclusoes_validas = [
        t.conclusao_fundamentos.strip()
        for t in resultado_etapa2.temas
        if t.conclusao_fundamentos and t.conclusao_fundamentos.strip()
    ]
    if not conclusoes_validas:
        fundamentos.append("Etapa 2 sem conclusões/fundamentos suficientes para decisão conclusiva.")
        return Decisao.INCONCLUSIVO, fundamentos

    sinais: list[tuple[int, Decisao, str]] = []
    numeros_sumulas = _extrair_numeros_sumulas(resultado_etapa2)

    obices_fortes = sorted(n for n in numeros_sumulas if n in _OBICES_FORTES_INADMISSIBILIDADE)
    if obices_fortes:
        sinais.append((
            100,
            Decisao.INADMITIDO,
            "Óbices sumulares identificados na Etapa 2: "
            + ", ".join(f"Súmula {n}" for n in obices_fortes),
        ))

    if (
        not resultado_etapa1.permissivo_constitucional.strip()
        and not resultado_etapa1.dispositivos_violados
    ):
        sinais.append((
            90,
            Decisao.INADMITIDO,
            "Etapa 1 sem permissivo constitucional e sem dispositivos violados explícitos.",
        ))

    conclusoes_texto = " ".join(t.conclusao_fundamentos for t in resultado_etapa2.temas)
    marcadores_inad = _detectar_marcadores_inadmissibilidade(conclusoes_texto)
    marcadores_adm = _detectar_marcadores_admissibilidade(conclusoes_texto)

    if marcadores_inad:
        sinais.append((
            70,
            Decisao.INADMITIDO,
            "Conclusões da Etapa 2 sinalizam inadmissibilidade/não conhecimento.",
        ))
    if marcadores_adm:
        sinais.append((
            70,
            Decisao.ADMITIDO,
            "Conclusões da Etapa 2 sinalizam admissibilidade/conhecimento do recurso.",
        ))

    if not sinais:
        fundamentos.append("Sem óbice forte identificado; requisitos mínimos estruturais atendidos.")
        return Decisao.ADMITIDO, fundamentos

    prioridade_max = max(prio for prio, _, _ in sinais)
    sinais_topo = [s for s in sinais if s[0] == prioridade_max]
    decisoes_topo = {d for _, d, _ in sinais_topo}

    fundamentos.append(
        f"Regra de precedência aplicada em conflito de evidências: {_PRECEDENCIA_CONFLITO_EVIDENCIAS}."
    )

    if len(decisoes_topo) > 1:
        fundamentos.extend(motivo for _, _, motivo in sinais_topo)
        fundamentos.append(
            "Conflito de evidências no mesmo nível de precedência; decisão marcada como INCONCLUSIVO."
        )
        return Decisao.INCONCLUSIVO, fundamentos

    decisao_final = sinais_topo[0][1]
    fundamentos.extend(motivo for _, _, motivo in sinais_topo)

    conflitos_menores = [
        motivo for prio, decisao, motivo in sinais
        if prio < prioridade_max and decisao != decisao_final
    ]
    if conflitos_menores:
        fundamentos.append(
            "Evidências conflitantes de menor precedência não prevaleceram."
        )

    return decisao_final, fundamentos


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

ETAPA3_STRUCTURED_DEVELOPER = """
Você deve responder APENAS JSON válido, sem markdown.
Formato obrigatório:
{
  "minuta_completa": "string",
  "decisao": "ADMITIDO|INADMITIDO|INCONCLUSIVO",
  "fundamentos_decisao": ["string"],
  "itens_evidencia_usados": ["string"],
  "motivo_bloqueio_codigo": "string",
  "motivo_bloqueio_descricao": "string"
}
Regras:
- A minuta deve conter as seções I, II e III.
- Use apenas informações do caso.
- Se não for possível concluir com segurança, usar "INCONCLUSIVO".
- Quando decisão for INCONCLUSIVO, incluir aviso explícito no texto da minuta.
""".strip()

ETAPA3_CHUNK_SUMMARY_DEVELOPER = """
Você receberá um chunk de acórdão para apoiar a redação da minuta final.
Responda apenas JSON com formato:
{
  "teses": [
    {
      "materia_controvertida": "string",
      "fundamentos_resumidos": "string",
      "obices_sumulas": ["string"],
      "trecho_literal_candidato": "string"
    }
  ]
}
Regras:
- Não invente.
- Use apenas o texto do chunk.
- Campo ausente: "[NÃO CONSTA NO DOCUMENTO]".
""".strip()


def _to_list(value: object) -> list[str]:
    """Normalize value to list[str]."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _tem_aviso_inconclusivo(minuta: str) -> bool:
    """Check whether draft includes explicit inconclusive warning."""
    if not minuta.strip():
        return False
    patterns = (
        r"decis[aã]o\s+jur[ií]dica\s+inconclusiva",
        r"aviso\s*:\s*decis[aã]o.*inconclus",
        r"\[inconclusiv[oa]\]",
    )
    return any(re.search(pattern, minuta, re.IGNORECASE) for pattern in patterns)


def _garantir_aviso_inconclusivo(minuta: str, motivo: str = "") -> str:
    """Ensure inconclusive drafts contain an explicit warning line."""
    if _tem_aviso_inconclusivo(minuta):
        return minuta
    detalhe = motivo.strip() if motivo and motivo.strip() else INCONCLUSIVO_WARNING_TEXT
    aviso = f"AVISO: {INCONCLUSIVO_WARNING_TEXT}"
    if detalhe and detalhe != INCONCLUSIVO_WARNING_TEXT:
        aviso += f" Motivo: {detalhe}"
    minuta_limpa = minuta.strip()
    if not minuta_limpa:
        return aviso
    return f"{aviso}\n\n{minuta_limpa}"


def _merge_list_unique(*listas: list[str]) -> list[str]:
    """Merge list[str] preserving order and removing duplicates."""
    merged: list[str] = []
    seen: set[str] = set()
    for lista in listas:
        for item in lista:
            value = str(item or "").strip()
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(value)
    return merged


def _motivo_bloqueio_inconclusivo(fundamentos: list[str] | None = None) -> tuple[str, str]:
    """Return standardized block reason for inconclusive decisions."""
    fundamentos_limpos = [f.strip() for f in (fundamentos or []) if str(f).strip()]
    descricao = (
        fundamentos_limpos[0]
        if fundamentos_limpos
        else "Evidências insuficientes ou conflitantes para decisão conclusiva."
    )
    return MOTIVO_BLOQUEIO_E3_INCONCLUSIVO, descricao


def _coletar_itens_evidencia_estruturados(
    resultado_etapa1: ResultadoEtapa1,
    resultado_etapa2: ResultadoEtapa2,
    limite: int = 16,
) -> list[str]:
    """Collect evidence items from Stage 1/2 for structured Stage 3 output."""
    itens: list[str] = []

    for campo in ("numero_processo", "recorrente", "especie_recurso"):
        evidencia = resultado_etapa1.evidencias_campos.get(campo)
        if evidencia and evidencia.citacao_literal.strip():
            pagina = evidencia.pagina if evidencia.pagina is not None else "?"
            itens.append(
                f"Etapa 1/{campo}: {evidencia.citacao_literal.strip()} (p.{pagina})"
            )

    for idx, tema in enumerate(resultado_etapa2.temas, 1):
        for campo in (
            "materia_controvertida",
            "conclusao_fundamentos",
            "obices_sumulas",
            "trecho_transcricao",
        ):
            evidencia = tema.evidencias_campos.get(campo)
            if not evidencia or not evidencia.citacao_literal.strip():
                continue
            pagina = evidencia.pagina if evidencia.pagina is not None else "?"
            itens.append(
                f"Tema {idx}/{campo}: {evidencia.citacao_literal.strip()} (p.{pagina})"
            )

    dedup = _merge_list_unique(itens)
    return dedup[:limite]


def _resultado_etapa3_from_json(payload: dict) -> ResultadoEtapa3:
    """Convert structured JSON payload into ResultadoEtapa3."""
    minuta = str(payload.get("minuta_completa") or "").strip()
    decisao_raw = str(payload.get("decisao") or "").strip().upper()
    decisao = None
    if decisao_raw == Decisao.ADMITIDO.value:
        decisao = Decisao.ADMITIDO
    elif decisao_raw == Decisao.INADMITIDO.value:
        decisao = Decisao.INADMITIDO
    elif decisao_raw == Decisao.INCONCLUSIVO.value:
        decisao = Decisao.INCONCLUSIVO

    if decisao is None and minuta:
        decisao = _extrair_decisao(minuta)

    fundamentos = _to_list(payload.get("fundamentos_decisao"))
    codigo = str(payload.get("motivo_bloqueio_codigo") or "").strip()
    descricao = str(payload.get("motivo_bloqueio_descricao") or "").strip()
    if decisao == Decisao.INCONCLUSIVO and not codigo:
        codigo, descricao_padrao = _motivo_bloqueio_inconclusivo(fundamentos)
        if not descricao:
            descricao = descricao_padrao

    return ResultadoEtapa3(
        minuta_completa=minuta,
        decisao=decisao,
        fundamentos_decisao=fundamentos,
        itens_evidencia_usados=_to_list(payload.get("itens_evidencia_usados")),
        aviso_inconclusivo=_tem_aviso_inconclusivo(minuta),
        motivo_bloqueio_codigo=codigo,
        motivo_bloqueio_descricao=descricao,
    )


def _summarizar_chunk_etapa3(chunk: str, idx: int, total: int) -> dict:
    """Generate chunk evidence summary for Stage 3 using mini model."""
    model = get_model_for_task(TaskType.PARSING)
    user_text = (
        f"Chunk {idx}/{total} do acórdão para evidências da minuta.\n\n"
        "--- INÍCIO DO CHUNK ---\n"
        f"{chunk}\n"
        "--- FIM DO CHUNK ---\n"
    )
    messages = build_messages(
        stage="etapa3",
        user_text=user_text,
        include_references=False,
        developer_override=ETAPA3_CHUNK_SUMMARY_DEVELOPER,
    )
    logger.info("🧩 Etapa 3 resumo chunk %d/%d — modelo=%s", idx, total, model)
    summary = chamar_llm_json(
        messages=messages,
        model=model,
        temperature=0.0,
        max_tokens=MAX_TOKENS_INTERMEDIATE,
    )
    return summary if isinstance(summary, dict) else {}


def _compactar_resumos_etapa3(resumos: list[dict]) -> str:
    """Compact summaries from chunk evidence into a deterministic context block."""
    blocos: list[str] = []
    tese_id = 1
    for i, resumo in enumerate(resumos, 1):
        teses = resumo.get("teses")
        if not isinstance(teses, list):
            continue
        for tese in teses:
            if not isinstance(tese, dict):
                continue
            obices = _to_list(tese.get("obices_sumulas"))[:6]
            trecho = str(tese.get("trecho_literal_candidato", "[NÃO CONSTA NO DOCUMENTO]")).strip()
            bloco = [
                f"Tese evidenciada {tese_id} (chunk {i}):",
                f"matéria: {tese.get('materia_controvertida', '[NÃO CONSTA NO DOCUMENTO]')}",
                f"fundamentos resumidos: {tese.get('fundamentos_resumidos', '[NÃO CONSTA NO DOCUMENTO]')}",
                "óbices/súmulas: " + ("; ".join(obices) if obices else "[NÃO CONSTA NO DOCUMENTO]"),
                f"trecho literal candidato: {trecho if trecho else '[NÃO CONSTA NO DOCUMENTO]'}",
            ]
            blocos.append("\n".join(bloco))
            tese_id += 1

    resumo_compacto = "\n\n".join(blocos)
    logger.info(
        "📦 Resumos Etapa 3 compactados: chunks=%d, chars=%d, tokens_estimados=%d",
        len(resumos),
        len(resumo_compacto),
        estimar_tokens(resumo_compacto),
    )
    return resumo_compacto


def executar_etapa3(
    resultado_etapa1: ResultadoEtapa1,
    resultado_etapa2: ResultadoEtapa2,
    texto_acordao: str,
    prompt_sistema: str,
    modelo_override: str | None = None,
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

    decisao_deterministica, fundamentos_decisao = _decidir_admissibilidade_deterministica(
        resultado_etapa1,
        resultado_etapa2,
    )
    fundamentos_texto = "\n".join(f"- {f}" for f in fundamentos_decisao) or "- [NÃO CONSTA NO DOCUMENTO]"

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
        + "\n\n--- DECISÃO DETERMINÍSTICA (VINCULANTE) ---\n"
        + f"Decisão obrigatória para a Seção III: {decisao_deterministica.value}\n"
        + "Fundamentos determinísticos:\n"
        + fundamentos_texto
        + "\n\n--- TEXTO DO ACÓRDÃO (para transcrição) ---\n"
        + texto_acordao_ctx
    )

    # 5.1.3 — Call LLM (use hybrid model routing for draft generation)
    if modelo_override:
        model = modelo_override
    else:
        model = get_model_for_task(TaskType.DRAFT_GENERATION)
    logger.info("🔄 Executando Etapa 3 — Geração da Minuta de Admissibilidade (modelo: %s)...", model)
    tokens_pre = estimar_tokens(user_message)
    structured_messages = build_messages(
        stage="etapa3",
        user_text=user_message,
        developer_override=ETAPA3_STRUCTURED_DEVELOPER,
        legacy_system_prompt=prompt_sistema.strip() if prompt_sistema and prompt_sistema.strip() else None,
    )
    legacy_messages = build_messages(
        stage="etapa3",
        user_text=user_message,
        legacy_system_prompt=prompt_sistema.strip() if prompt_sistema and prompt_sistema.strip() else None,
    )

    resultado_struct: ResultadoEtapa3 | None = None
    structured_error: Exception | None = None
    for attempt in (1, 2):
        attempt_messages = structured_messages
        if attempt == 2:
            reinforced = (
                ETAPA3_STRUCTURED_DEVELOPER
                + "\nReforço: resposta EXCLUSIVAMENTE JSON válido."
            )
            attempt_messages = build_messages(
                stage="etapa3",
                user_text=user_message,
                developer_override=reinforced,
                legacy_system_prompt=prompt_sistema.strip() if prompt_sistema and prompt_sistema.strip() else None,
            )
        try:
            payload = chamar_llm_json(
                messages=attempt_messages,
                model=model,
                max_tokens=MAX_TOKENS_ETAPA3,
                temperature=0.0,
                use_cache=False,
                response_schema=ETAPA3_RESPONSE_SCHEMA,
                schema_name="etapa3_resultado",
            )
            resultado_struct = _resultado_etapa3_from_json(payload)
            if resultado_struct.minuta_completa:
                logger.info("Etapa 3 estruturada (JSON) concluída com sucesso na tentativa %d.", attempt)
                break
        except Exception as e:
            structured_error = e
            logger.warning("Falha no modo estruturado da Etapa 3 (tentativa %d): %s", attempt, e)

    if resultado_struct is None or not resultado_struct.minuta_completa:
        logger.warning(
            "Falha persistente no modo estruturado da Etapa 3 (%s). "
            "Usando fallback legado de texto livre.",
            structured_error,
        )
        response = chamar_llm(
            messages=legacy_messages,
            model=model,
            max_tokens=MAX_TOKENS_ETAPA3,
        )

        logger.info(
            "Tokens — estimados: %d, reais: %d (prompt=%d, completion=%d)",
            tokens_pre,
            response.tokens.total_tokens,
            response.tokens.prompt_tokens,
            response.tokens.completion_tokens,
        )
        minuta = response.content
    else:
        minuta = resultado_struct.minuta_completa

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

    decisao_extraida = (
        resultado_struct.decisao
        if resultado_struct and resultado_struct.decisao
        else _extrair_decisao(minuta)
    )
    if decisao_extraida and decisao_extraida != decisao_deterministica:
        logger.warning(
            "⚠️ Divergência entre minuta e motor determinístico na Etapa 3 "
            "(minuta=%s, determinístico=%s). Aplicando decisão determinística.",
            decisao_extraida.value,
            decisao_deterministica.value,
        )

    if decisao_deterministica == Decisao.INCONCLUSIVO:
        minuta = _garantir_aviso_inconclusivo(
            minuta,
            fundamentos_decisao[0] if fundamentos_decisao else "",
        )

    fundamentos_estruturados = (
        resultado_struct.fundamentos_decisao
        if resultado_struct and resultado_struct.fundamentos_decisao
        else []
    )
    evidencias_estruturadas = (
        resultado_struct.itens_evidencia_usados
        if resultado_struct and resultado_struct.itens_evidencia_usados
        else []
    )
    evidencias_fallback = _coletar_itens_evidencia_estruturados(resultado_etapa1, resultado_etapa2)
    motivo_codigo = ""
    motivo_descricao = ""
    if decisao_deterministica == Decisao.INCONCLUSIVO:
        motivo_codigo, motivo_descricao = _motivo_bloqueio_inconclusivo(fundamentos_decisao)

    resultado = ResultadoEtapa3(
        minuta_completa=minuta,
        decisao=decisao_deterministica,
        fundamentos_decisao=_merge_list_unique(fundamentos_decisao, fundamentos_estruturados),
        itens_evidencia_usados=_merge_list_unique(evidencias_estruturadas, evidencias_fallback),
        aviso_inconclusivo=_tem_aviso_inconclusivo(minuta),
        motivo_bloqueio_codigo=motivo_codigo,
        motivo_bloqueio_descricao=motivo_descricao,
    )

    if todos_alertas:
        logger.warning("Etapa 3 concluída com %d alerta(s)", len(todos_alertas))
    else:
        logger.info(
            "✅ Etapa 3 concluída — Decisão determinística: %s",
            decisao_deterministica.value,
        )

    return resultado


# --- Chunking support (robust architecture) ---


def _merge_etapa3_results(resultados: list[ResultadoEtapa3]) -> ResultadoEtapa3:
    """
    Merge results from multiple chunks into a single ResultadoEtapa3.

    Strategy:
    - Use the LAST chunk as the base minuta (most complete)
    - Extract and deduplicate all quoted transcriptions from all chunks
    - Merge transcriptions into Section II of the final minuta
    - Use decision from last chunk

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

    # Use the last chunk as base (most complete context)
    minuta_base = resultados[-1].minuta_completa

    # Extract all unique transcriptions from all chunks
    transcricoes_unicas = set()
    for r in resultados:
        if r.minuta_completa:
            # Find all quoted text (potential transcriptions)
            quotes = re.findall(r'"([^"]{30,})"', r.minuta_completa)
            for quote in quotes:
                # Normalize whitespace and store
                transcricoes_unicas.add(quote.strip())

    # Count transcriptions found
    if len(transcricoes_unicas) > 1:
        logger.info("📝 %d transcrições únicas encontradas nos chunks", len(transcricoes_unicas))

    # Use decision from last chunk (most likely to have full context)
    decisao_final = resultados[-1].decisao

    # Count decisions to check consistency
    decisoes = [r.decisao for r in resultados if r.decisao]
    if decisoes:
        admitidos = sum(1 for d in decisoes if d == Decisao.ADMITIDO)
        inadmitidos = sum(1 for d in decisoes if d == Decisao.INADMITIDO)
        inconclusivos = sum(1 for d in decisoes if d == Decisao.INCONCLUSIVO)

        if admitidos > 0 and inadmitidos > 0:
            logger.warning(
                "⚠️  Decisões inconsistentes entre chunks: %d ADMITIDO, %d INADMITIDO",
                admitidos, inadmitidos,
            )
            # Use majority vote
            decisao_final = Decisao.ADMITIDO if admitidos > inadmitidos else Decisao.INADMITIDO
        elif inconclusivos and not admitidos and not inadmitidos:
            decisao_final = Decisao.INCONCLUSIVO

    fundamentos_merged = _merge_list_unique(*[r.fundamentos_decisao for r in resultados])
    evidencias_merged = _merge_list_unique(*[r.itens_evidencia_usados for r in resultados])

    if decisao_final == Decisao.INCONCLUSIVO:
        minuta_base = _garantir_aviso_inconclusivo(minuta_base)
    motivo_codigo = ""
    motivo_descricao = ""
    if decisao_final == Decisao.INCONCLUSIVO:
        motivo_codigo, motivo_descricao = _motivo_bloqueio_inconclusivo(fundamentos_merged)

    resultado = ResultadoEtapa3(
        minuta_completa=minuta_base,
        decisao=decisao_final,
        fundamentos_decisao=fundamentos_merged,
        itens_evidencia_usados=evidencias_merged,
        aviso_inconclusivo=_tem_aviso_inconclusivo(minuta_base),
        motivo_bloqueio_codigo=motivo_codigo,
        motivo_bloqueio_descricao=motivo_descricao,
    )

    logger.info(
        "✅ Minuta final baseada no último chunk de %d chunks processados — Decisão: %s",
        len(resultados), decisao_final.value if decisao_final else "N/A",
    )
    return resultado


def executar_etapa3_com_chunking(
    resultado_etapa1: ResultadoEtapa1,
    resultado_etapa2: ResultadoEtapa2,
    texto_acordao: str,
    prompt_sistema: str,
    modelo_override: str | None = None,
    chunking_audit: dict | None = None,
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
        if chunking_audit is not None:
            chunking_audit.update({
                "aplicado": False,
                "motivo": "chunking_disabled",
            })
        return executar_etapa3(resultado_etapa1, resultado_etapa2, texto_acordao, prompt_sistema, modelo_override=modelo_override)

    # Prerequisite validation
    if resultado_etapa2 is None or not resultado_etapa2.temas:
        raise Etapa3Error("Etapa 2 não executada ou sem temas. Execute a Etapa 2 antes.")

    decisao_deterministica, fundamentos_decisao = _decidir_admissibilidade_deterministica(
        resultado_etapa1,
        resultado_etapa2,
    )
    fundamentos_texto = "\n".join(f"- {f}" for f in fundamentos_decisao) or "- [NÃO CONSTA NO DOCUMENTO]"

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
        if chunking_audit is not None:
            chunking_audit.update({
                "aplicado": False,
                "motivo": "fits_context",
                "total_tokens_estimados": tokens_total,
                "limite_seguro": limite_seguro,
            })
        return executar_etapa3(resultado_etapa1, resultado_etapa2, texto_acordao, prompt_sistema, modelo_override=modelo_override)

    # Document is too large — apply map-reduce to acordao only
    logger.warning(
        "⚠️  Documento grande detectado (%d tokens, limite: %d). "
        "Aplicando map-reduce (mini -> forte) no acórdão...",
        tokens_total, limite_seguro,
    )

    # Import chunker (lazy to avoid circular imports)
    from src.token_manager import text_chunker

    # Adjust max tokens to account for context overhead
    effective_limit = limite_seguro - tokens_context - 2000  # 2k buffer for response
    original_max = text_chunker.max_tokens
    text_chunker.max_tokens = effective_limit

    chunks, coverage_report = text_chunker.chunk_text_with_coverage(texto_acordao, model="gpt-4o")
    text_chunker.max_tokens = original_max  # Restore
    if chunking_audit is not None:
        chunking_audit.update(coverage_report)
        chunking_audit["limite_seguro"] = limite_seguro
        chunking_audit["effective_limit"] = effective_limit
        chunking_audit["tokens_contexto_base"] = tokens_context

    logger.info("📦 Acórdão dividido em %d chunks. Gerando resumos de evidência...", len(chunks))
    summaries: list[dict] = []

    for i, chunk in enumerate(chunks, 1):
        logger.info("🔄 Resumindo chunk %d/%d...", i, len(chunks))

        try:
            summary = _summarizar_chunk_etapa3(chunk, i, len(chunks))
            summaries.append(summary)
        except Exception as e:
            logger.error("❌ Erro ao resumir chunk %d/%d: %s", i, len(chunks), e)
            continue

    if not summaries:
        raise RuntimeError("Nenhum chunk foi resumido com sucesso")
    if chunking_audit is not None:
        chunking_audit["chunks_resumidos"] = len(summaries)
        chunking_audit["chunks_falhos"] = len(chunks) - len(summaries)

    resumo_evidencias = _compactar_resumos_etapa3(summaries)
    user_message = (
        ETAPA3_USER_INSTRUCTION
        + "--- RESULTADO DA ETAPA 1 ---\n"
        + etapa1_resumo
        + "\n\n--- RESULTADO DA ETAPA 2 ---\n"
        + etapa2_resumo
        + "\n\n--- DECISÃO DETERMINÍSTICA (VINCULANTE) ---\n"
        + f"Decisão obrigatória para a Seção III: {decisao_deterministica.value}\n"
        + "Fundamentos determinísticos:\n"
        + fundamentos_texto
        + "\n\n--- EVIDÊNCIAS CONSOLIDADAS DO ACÓRDÃO (RESUMOS) ---\n"
        + resumo_evidencias
    )

    if modelo_override:
        model = modelo_override
    else:
        model = get_model_for_task(TaskType.DRAFT_GENERATION)

    messages = build_messages(
        stage="etapa3",
        user_text=user_message,
        legacy_system_prompt=prompt_sistema.strip() if prompt_sistema and prompt_sistema.strip() else None,
    )
    response = chamar_llm(
        messages=messages,
        model=model,
        max_tokens=MAX_TOKENS_ETAPA3,
    )

    minuta = response.content
    alertas_secoes = _validar_secoes(minuta)
    alertas_secao_i = _validar_secao_i(minuta, resultado_etapa1)
    alertas_secao_ii = _validar_secao_ii(minuta, resultado_etapa2)
    alertas_secao_iii = _validar_secao_iii(minuta)
    alertas_disp = _validar_cruzada_dispositivos(minuta, resultado_etapa1)
    alertas_temas = _validar_cruzada_temas(minuta, resultado_etapa2)
    alertas_transc = _validar_transcricoes(minuta, texto_acordao)
    alertas_sumulas = _validar_sumulas_secao_iii(minuta, resultado_etapa2)

    todos_alertas = (
        alertas_secoes + alertas_secao_i + alertas_secao_ii + alertas_secao_iii
        + alertas_disp + alertas_temas + alertas_transc + alertas_sumulas
    )
    for alerta in todos_alertas:
        logger.warning("⚠️  %s", alerta)

    decisao_extraida = _extrair_decisao(minuta)
    if decisao_extraida and decisao_extraida != decisao_deterministica:
        logger.warning(
            "⚠️ Divergência entre minuta e motor determinístico na Etapa 3 com chunking "
            "(minuta=%s, determinístico=%s). Aplicando decisão determinística.",
            decisao_extraida.value,
            decisao_deterministica.value,
        )

    minuta_final = (
        _garantir_aviso_inconclusivo(
            minuta,
            fundamentos_decisao[0] if fundamentos_decisao else "",
        )
        if decisao_deterministica == Decisao.INCONCLUSIVO
        else minuta
    )

    resultado_final = ResultadoEtapa3(
        minuta_completa=minuta_final,
        decisao=decisao_deterministica,
        fundamentos_decisao=fundamentos_decisao,
        itens_evidencia_usados=_coletar_itens_evidencia_estruturados(resultado_etapa1, resultado_etapa2),
        aviso_inconclusivo=_tem_aviso_inconclusivo(minuta_final),
        motivo_bloqueio_codigo=(
            _motivo_bloqueio_inconclusivo(fundamentos_decisao)[0]
            if decisao_deterministica == Decisao.INCONCLUSIVO
            else ""
        ),
        motivo_bloqueio_descricao=(
            _motivo_bloqueio_inconclusivo(fundamentos_decisao)[1]
            if decisao_deterministica == Decisao.INCONCLUSIVO
            else ""
        ),
    )

    logger.info(
        "✅ Etapa 3 concluída com map-reduce (%d chunks resumidos) — Decisão determinística: %s",
        len(summaries),
        decisao_deterministica.value,
    )
    return resultado_final
