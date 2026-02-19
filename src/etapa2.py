"""Stage 2: Ruling (acórdão) thematic analysis with obstacle identification."""

import logging
import re
import unicodedata
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.config import (
    ENABLE_CHUNKING,
    ENABLE_PARALLEL_ETAPA2,
    ETAPA2_PARALLEL_WORKERS,
    MAX_TOKENS_ETAPA2,
    MAX_TOKENS_INTERMEDIATE,
    MAX_CONTEXT_TOKENS,
    TOKEN_BUDGET_RATIO,
)
from src.etapa1 import estimar_tokens, _verificar_contexto
from src.llm_client import chamar_llm, chamar_llm_json
from src.model_router import TaskType, get_model_for_task
from src.models import CampoEvidencia, ResultadoEtapa1, ResultadoEtapa2, TemaEtapa2
from src.prompt_loader import build_messages
from src.sumula_taxonomy import SUMULAS_STF, SUMULAS_STJ, SUMULAS_VALIDAS, SUMULAS_TAXONOMY_VERSION

logger = logging.getLogger("assessor_ai")


# --- 4.3.1 Valid súmulas ---
ETAPA2_REQUIRED_THEME_FIELDS: tuple[str, ...] = (
    "materia_controvertida",
    "conclusao_fundamentos",
    "obices_sumulas",
    "trecho_transcricao",
)
ETAPA2_DEDUP_STOPWORDS: set[str] = {
    "de", "da", "do", "das", "dos", "e", "ou", "a", "o", "as", "os",
    "no", "na", "nos", "nas", "por", "para", "com", "sem", "em",
    "que", "sobre", "ao", "aos", "à", "às",
}
ETAPA2_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "temas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "materia_controvertida": {"type": "string"},
                    "conclusao_fundamentos": {"type": "string"},
                    "base_vinculante": {"type": "string"},
                    "obices_sumulas": {"type": "array", "items": {"type": "string"}},
                    "trecho_transcricao": {"type": "string"},
                    "evidencias_campos": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
                "required": ETAPA2_REQUIRED_THEME_FIELDS,
                "additionalProperties": False,
            },
        },
    },
    "required": ["temas"],
    "additionalProperties": False,
}


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
        if not tema.obices_sumulas:
            alertas.append(f"Tema {i}: óbices/súmulas ausente")
        if not tema.trecho_transcricao:
            alertas.append(f"Tema {i}: trecho literal ausente")

    if not temas:
        alertas.append("Nenhum tema identificado na resposta")

    for alerta in alertas:
        logger.warning("⚠️  %s", alerta)

    return alertas


# --- 4.3.2 / 4.3.3 Obstacle validation ---


def _validar_obices(temas: list[TemaEtapa2], texto_acordao: str) -> list[str]:
    """Validate obstacles against allowed list and source text."""
    alertas: list[str] = []
    logger.debug("Validando óbices com taxonomia de súmulas v%s", SUMULAS_TAXONOMY_VERSION)

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

            # 4.3.3 Cross-check with source text (normalized variants included)
            if not _obice_tem_lastro_no_texto(obice, texto_acordao):
                alertas.append(
                    f"Tema {i}: óbice '{obice}' sem lastro no texto do acórdão"
                )

    return alertas


def _normalizar_texto_busca(texto: str) -> str:
    """Normalize text for robust matching (case/accents/punctuation-insensitive)."""
    if not texto:
        return ""
    normalized = unicodedata.normalize("NFD", texto)
    sem_acentos = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    sem_ruido = re.sub(r"[^a-zA-Z0-9]+", " ", sem_acentos.lower())
    return re.sub(r"\s+", " ", sem_ruido).strip()


def _obice_tem_lastro_no_texto(obice: str, texto_acordao: str) -> bool:
    """Check whether an obstacle reference appears in source text (with normalized variants)."""
    if not obice.strip():
        return True

    if _find_span_case_insensitive(texto_acordao, obice):
        return True

    texto_norm = _normalizar_texto_busca(texto_acordao)
    obice_norm = _normalizar_texto_busca(obice)
    if obice_norm and obice_norm in texto_norm:
        return True

    num_match = re.search(r"\b(\d{1,4})\b", obice_norm)
    if not num_match:
        return False

    numero = num_match.group(1)
    sumula_pattern = rf"\b(sumula|enunciado|verbete)\s*(n|no|nr|numero|nro)?\s*{re.escape(numero)}\b"
    if re.search(sumula_pattern, texto_norm):
        return True

    variants = (
        f"sumula {numero}",
        f"sumula n {numero}",
        f"enunciado {numero}",
        f"verbete {numero}",
    )
    for variant in variants:
        if _normalizar_texto_busca(variant) in texto_norm:
            return True
    return False


def _find_span_case_insensitive(texto: str, termo: str) -> tuple[int, int] | None:
    """Find first case-insensitive span for term in text."""
    termo_limpo = termo.strip()
    if not texto or not termo_limpo:
        return None

    match = re.search(re.escape(termo_limpo), texto, re.IGNORECASE)
    if match:
        return match.start(), match.end()

    termos = [t for t in termo_limpo.split() if t]
    if not termos:
        return None
    pattern = r"\s+".join(re.escape(t) for t in termos)
    match_flex = re.search(pattern, texto, re.IGNORECASE)
    if match_flex:
        return match_flex.start(), match_flex.end()
    return None


def _inferir_pagina_por_posicao(texto: str, pos: int) -> int:
    """Infer page number by position using form-feed or explicit page markers."""
    if "\f" in texto:
        return texto.count("\f", 0, pos) + 1

    anteriores = texto[:pos + 1]
    marcadores = list(re.finditer(r"(?i)p[áa]gina\s+(\d{1,4})", anteriores))
    if marcadores:
        try:
            return max(1, int(marcadores[-1].group(1)))
        except ValueError:
            pass
    return 1


def _gerar_evidencia_tema_local(valor: str, texto_entrada: str) -> CampoEvidencia | None:
    """Generate deterministic evidence for one Stage 2 field value."""
    span = _find_span_case_insensitive(texto_entrada, valor)
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
        pagina=_inferir_pagina_por_posicao(texto_entrada, inicio),
        ancora=ancora,
        offset_inicio=inicio,
    )


def _merge_evidencia(existing: CampoEvidencia | None, generated: CampoEvidencia) -> CampoEvidencia:
    """Merge existing evidence with generated evidence, preserving explicit values first."""
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


def _campo_tema_to_text(tema: TemaEtapa2, campo: str) -> str:
    """Resolve a theme field into text for deterministic evidence extraction."""
    if campo == "obices_sumulas":
        return "; ".join(o.strip() for o in tema.obices_sumulas if o.strip())
    value = getattr(tema, campo, "")
    return str(value).strip()


def _normalizar_int(value: object) -> int | None:
    """Normalize integer-like values from structured payload."""
    if value is None:
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed


def _normalizar_evidencia(value: object) -> CampoEvidencia | None:
    """Normalize one evidence object from structured JSON."""
    if not isinstance(value, dict):
        return None

    citacao = _norm_text(value.get("citacao_literal"))
    ancora = _norm_text(value.get("ancora"))
    pagina_raw = _normalizar_int(value.get("pagina"))
    offset_raw = _normalizar_int(value.get("offset_inicio"))
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


def _normalizar_evidencias_tema(payload: object) -> dict[str, CampoEvidencia]:
    """Normalize evidencias_campos mapping from structured JSON payload."""
    if not isinstance(payload, dict):
        return {}

    evidencias: dict[str, CampoEvidencia] = {}
    for campo, raw in payload.items():
        evidencia = _normalizar_evidencia(raw)
        campo_norm = str(campo).strip()
        if evidencia and campo_norm:
            evidencias[campo_norm] = evidencia
    return evidencias


def _enriquecer_evidencias_tema(tema: TemaEtapa2, texto_acordao: str) -> None:
    """Backfill missing theme evidence from source text."""
    if tema.evidencias_campos is None:
        tema.evidencias_campos = {}

    for campo in ETAPA2_REQUIRED_THEME_FIELDS:
        value_text = _campo_tema_to_text(tema, campo)
        if not value_text:
            continue

        evidencia_atual = tema.evidencias_campos.get(campo)
        completa = (
            evidencia_atual is not None
            and bool(evidencia_atual.citacao_literal.strip())
            and bool(evidencia_atual.ancora.strip())
            and evidencia_atual.pagina is not None
        )
        if completa:
            continue

        generated: CampoEvidencia | None = None
        if campo == "obices_sumulas":
            for obice in tema.obices_sumulas:
                obice_clean = obice.strip()
                if not obice_clean:
                    continue
                generated = _gerar_evidencia_tema_local(obice_clean, texto_acordao)
                if generated:
                    break
        else:
            generated = _gerar_evidencia_tema_local(value_text, texto_acordao)

        if generated:
            tema.evidencias_campos[campo] = _merge_evidencia(evidencia_atual, generated)


def _enriquecer_evidencias_temas(temas: list[TemaEtapa2], texto_acordao: str) -> None:
    """Backfill missing evidence for all extracted themes."""
    for tema in temas:
        _enriquecer_evidencias_tema(tema, texto_acordao)


def _validar_evidencias_temas(temas: list[TemaEtapa2], texto_acordao: str) -> list[str]:
    """Validate required theme evidence objects and source-text anchoring."""
    alertas: list[str] = []

    for i, tema in enumerate(temas, 1):
        for campo in ETAPA2_REQUIRED_THEME_FIELDS:
            valor = _campo_tema_to_text(tema, campo)
            if not valor:
                continue

            evidencia = tema.evidencias_campos.get(campo)
            if evidencia is None:
                alertas.append(f"Tema {i}: campo '{campo}' sem evidência")
                continue

            citacao = evidencia.citacao_literal.strip()
            ancora = evidencia.ancora.strip()
            if not citacao:
                alertas.append(f"Tema {i}: evidência sem citação literal em '{campo}'")
            if evidencia.pagina is None or evidencia.pagina < 1:
                alertas.append(f"Tema {i}: evidência sem página válida em '{campo}'")
            if not ancora:
                alertas.append(f"Tema {i}: evidência sem âncora em '{campo}'")

            if citacao and _find_span_case_insensitive(texto_acordao, citacao) is None:
                alertas.append(f"Tema {i}: citação de evidência de '{campo}' sem lastro no acórdão")

    for alerta in alertas:
        logger.warning("🔎 Evidência Etapa 2: %s", alerta)

    return alertas


def _texto_semantico_tema(tema: TemaEtapa2) -> str:
    """Build semantic text representation of one theme for deduplication."""
    partes = [
        tema.materia_controvertida,
        tema.conclusao_fundamentos,
        tema.base_vinculante,
        " ".join(tema.obices_sumulas),
        tema.trecho_transcricao[:220],
    ]
    return " ".join(p.strip() for p in partes if p and p.strip())


def _tokens_semanticos(texto: str) -> set[str]:
    """Tokenize text for semantic comparison."""
    texto_norm = _normalizar_texto_busca(texto)
    tokens = {
        token
        for token in texto_norm.split()
        if len(token) >= 3 and token not in ETAPA2_DEDUP_STOPWORDS
    }
    return tokens


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Compute Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _score_completude_tema(tema: TemaEtapa2) -> float:
    """Score how complete/reliable a theme is for duplicate resolution."""
    score = 0.0
    if tema.materia_controvertida.strip():
        score += 2.0
    if tema.conclusao_fundamentos.strip():
        score += 2.0
    if tema.base_vinculante.strip():
        score += 1.0
    if tema.obices_sumulas:
        score += 1.0
    if tema.trecho_transcricao.strip():
        score += 1.0

    for campo in ETAPA2_REQUIRED_THEME_FIELDS:
        evid = tema.evidencias_campos.get(campo)
        if evid is None:
            continue
        if evid.citacao_literal.strip():
            score += 0.5
        if evid.ancora.strip():
            score += 0.25
        if evid.pagina is not None and evid.pagina > 0:
            score += 0.25
    return score


def _temas_semanticamente_equivalentes(a: TemaEtapa2, b: TemaEtapa2) -> bool:
    """Heuristic semantic equivalence for Stage 2 themes."""
    materia_a = _normalizar_texto_busca(a.materia_controvertida)
    materia_b = _normalizar_texto_busca(b.materia_controvertida)
    if materia_a and materia_b and materia_a == materia_b:
        return True

    texto_a = _normalizar_texto_busca(_texto_semantico_tema(a))
    texto_b = _normalizar_texto_busca(_texto_semantico_tema(b))
    if not texto_a or not texto_b:
        return False

    tokens_a = _tokens_semanticos(texto_a)
    tokens_b = _tokens_semanticos(texto_b)
    jaccard = _jaccard_similarity(tokens_a, tokens_b)
    shared_tokens = len(tokens_a & tokens_b)
    seq_materia = SequenceMatcher(None, materia_a, materia_b).ratio() if materia_a and materia_b else 0.0
    seq_full = SequenceMatcher(None, texto_a, texto_b).ratio()
    composite = (0.45 * jaccard) + (0.35 * seq_materia) + (0.20 * seq_full)
    obices_a = {m.group(1) for ob in a.obices_sumulas for m in re.finditer(r"(\d+)", ob)}
    obices_b = {m.group(1) for ob in b.obices_sumulas for m in re.finditer(r"(\d+)", ob)}
    obice_overlap = bool(obices_a and obices_b and (obices_a & obices_b))

    return (
        (seq_materia >= 0.92)
        or (seq_materia >= 0.82 and shared_tokens >= 4 and (obice_overlap or seq_full >= 0.68))
        or (jaccard >= 0.78 and seq_materia >= 0.70)
        or (composite >= 0.80 and jaccard >= 0.58)
    )


def _deduplicar_temas_semanticos(temas: list[TemaEtapa2]) -> list[TemaEtapa2]:
    """Deduplicate themes using semantic similarity and completeness score."""
    if len(temas) <= 1:
        return temas

    unicos: list[TemaEtapa2] = []
    duplicados = 0

    for tema in temas:
        duplicate_idx: int | None = None
        for idx, existente in enumerate(unicos):
            if _temas_semanticamente_equivalentes(tema, existente):
                duplicate_idx = idx
                break

        if duplicate_idx is None:
            unicos.append(tema)
            continue

        duplicados += 1
        if _score_completude_tema(tema) > _score_completude_tema(unicos[duplicate_idx]):
            unicos[duplicate_idx] = tema

    if duplicados:
        logger.info(
            "🧹 Deduplicação semântica Etapa 2 removeu %d tema(s) duplicado(s).",
            duplicados,
        )

    return unicos


# --- 4.1.1 Main function ---


ETAPA2_USER_INSTRUCTION = (
    "Analise o acórdão a seguir e execute a Etapa 2 conforme instruções.\n"
    "Identifique os temas controvertidos, conclusões, bases vinculantes "
    "e possíveis óbices para cada tema.\n\n"
)

ETAPA2_STRUCTURED_DEVELOPER = """
Você receberá texto de acórdão e deve responder APENAS JSON válido.
Formato:
{
  "temas": [
    {
      "materia_controvertida": "string",
      "conclusao_fundamentos": "string",
      "base_vinculante": "string",
      "obices_sumulas": ["string"],
      "trecho_transcricao": "string",
      "evidencias_campos": {
        "materia_controvertida": {"citacao_literal": "string", "pagina": 1, "ancora": "string", "offset_inicio": 0},
        "conclusao_fundamentos": {"citacao_literal": "string", "pagina": 1, "ancora": "string", "offset_inicio": 0},
        "obices_sumulas": {"citacao_literal": "string", "pagina": 1, "ancora": "string", "offset_inicio": 0},
        "trecho_transcricao": {"citacao_literal": "string", "pagina": 1, "ancora": "string", "offset_inicio": 0}
      }
    }
  ]
}
Regras:
- Usar somente informações do texto.
- Se não constar, usar string vazia/lista vazia.
- Para cada campo preenchido (matéria, conclusão, óbices e trecho), incluir evidência correspondente.
- Se página/offset não puderem ser inferidos com segurança, usar pagina=1 e offset_inicio=-1.
- Não retornar markdown.
""".strip()

ETAPA2_CHUNK_SUMMARY_DEVELOPER = """
Você receberá um chunk de acórdão e deve extrair resumo estruturado em JSON.
Formato:
{
  "temas": [
    {
      "materia_controvertida": "string",
      "conclusao_fundamentos": "string",
      "natureza_fundamento": "constitucional|infraconstitucional|misto|[NÃO CONSTA NO DOCUMENTO]",
      "base_vinculante": "string",
      "obices_sumulas": ["string"],
      "trechos_chave": ["string"]
    }
  ]
}
Regras:
- Usar apenas o chunk.
- Não inventar súmula, tese ou precedente.
- Se ausente, usar "[NÃO CONSTA NO DOCUMENTO]".
- Responder apenas JSON válido.
""".strip()


def _to_list(value: object) -> list[str]:
    """Normalize field as list[str]."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _norm_text(value: object) -> str:
    """Normalize text fields and placeholders from structured JSON."""
    text = str(value or "").strip()
    if not text:
        return ""
    placeholder = text.upper().replace("Ã", "A")
    if placeholder in {"[NAO CONSTA NO DOCUMENTO]", "[NÃO CONSTA NO DOCUMENTO]", "N/A", "NA"}:
        return ""
    return text


def _tema_etapa2_from_json(item: object) -> TemaEtapa2:
    """Convert one structured JSON object into TemaEtapa2."""
    if not isinstance(item, dict):
        return TemaEtapa2()
    obices = [_norm_text(v) for v in _to_list(item.get("obices_sumulas"))]
    obices = [o for o in obices if o]
    return TemaEtapa2(
        materia_controvertida=_norm_text(item.get("materia_controvertida")),
        conclusao_fundamentos=_norm_text(item.get("conclusao_fundamentos")),
        base_vinculante=_norm_text(item.get("base_vinculante")),
        obices_sumulas=obices,
        trecho_transcricao=_norm_text(item.get("trecho_transcricao")),
        evidencias_campos=_normalizar_evidencias_tema(item.get("evidencias_campos")),
    )


def _resultado_etapa2_from_json(payload: dict) -> ResultadoEtapa2:
    """Convert structured JSON payload into ResultadoEtapa2."""
    temas_raw = payload.get("temas", [])
    temas: list[TemaEtapa2] = []
    if isinstance(temas_raw, list):
        temas = [_tema_etapa2_from_json(item) for item in temas_raw]
    return ResultadoEtapa2(
        temas=temas,
        texto_formatado=str(payload),
    )


def _summarizar_chunk_etapa2(chunk: str, idx: int, total: int) -> dict:
    """Generate structured summary for one Stage 2 chunk using mini model."""
    model = get_model_for_task(TaskType.PARSING)
    user_text = (
        f"Chunk {idx}/{total} do acórdão.\n"
        "Extraia temas e evidências em JSON.\n\n"
        "--- INÍCIO DO CHUNK ---\n"
        f"{chunk}\n"
        "--- FIM DO CHUNK ---\n"
    )
    messages = build_messages(
        stage="etapa2",
        user_text=user_text,
        include_references=False,
        developer_override=ETAPA2_CHUNK_SUMMARY_DEVELOPER,
    )
    logger.info("🧩 Etapa 2 resumo chunk %d/%d — modelo=%s", idx, total, model)
    summary = chamar_llm_json(
        messages=messages,
        model=model,
        temperature=0.0,
        max_tokens=MAX_TOKENS_INTERMEDIATE,
    )
    return summary if isinstance(summary, dict) else {}


def _compactar_resumos_etapa2(resumos: list[dict]) -> str:
    """Build compact textual context from Stage 2 chunk summaries."""
    blocos: list[str] = []
    tema_counter = 1
    for i, r in enumerate(resumos, 1):
        temas = r.get("temas")
        if not isinstance(temas, list):
            continue
        for tema in temas:
            if not isinstance(tema, dict):
                continue
            obices = _to_list(tema.get("obices_sumulas"))[:6]
            trechos = _to_list(tema.get("trechos_chave"))[:4]
            bloco = [
                f"Tema consolidado {tema_counter} (origem chunk {i}):",
                f"matéria: {tema.get('materia_controvertida', '[NÃO CONSTA NO DOCUMENTO]')}",
                f"conclusão e fundamentos: {tema.get('conclusao_fundamentos', '[NÃO CONSTA NO DOCUMENTO]')}",
                f"natureza do fundamento: {tema.get('natureza_fundamento', '[NÃO CONSTA NO DOCUMENTO]')}",
                f"base vinculante: {tema.get('base_vinculante', '[NÃO CONSTA NO DOCUMENTO]')}",
                "óbices/súmulas: " + ("; ".join(obices) if obices else "[NÃO CONSTA NO DOCUMENTO]"),
                "trechos chave: " + (" | ".join(trechos) if trechos else "[NÃO CONSTA NO DOCUMENTO]"),
            ]
            blocos.append("\n".join(bloco))
            tema_counter += 1
    resumo_compacto = "\n\n".join(blocos)
    logger.info(
        "📦 Resumos Etapa 2 compactados: chunks=%d, chars=%d, tokens_estimados=%d",
        len(resumos),
        len(resumo_compacto),
        estimar_tokens(resumo_compacto),
    )
    return resumo_compacto


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
    structured_messages = build_messages(
        stage="etapa2",
        user_text=user_message,
        developer_override=ETAPA2_STRUCTURED_DEVELOPER,
        legacy_system_prompt=prompt_sistema.strip() if prompt_sistema and prompt_sistema.strip() else None,
    )
    legacy_messages = build_messages(
        stage="etapa2",
        user_text=user_message,
        legacy_system_prompt=prompt_sistema.strip() if prompt_sistema and prompt_sistema.strip() else None,
    )

    resultado: ResultadoEtapa2 | None = None
    structured_error: Exception | None = None
    for attempt in (1, 2):
        attempt_messages = structured_messages
        if attempt == 2:
            reinforced = (
                ETAPA2_STRUCTURED_DEVELOPER
                + "\nReforço: responda somente com JSON válido, sem markdown."
            )
            attempt_messages = build_messages(
                stage="etapa2",
                user_text=user_message,
                developer_override=reinforced,
                legacy_system_prompt=prompt_sistema.strip() if prompt_sistema and prompt_sistema.strip() else None,
            )
        try:
            payload = chamar_llm_json(
                messages=attempt_messages,
                model=model,
                max_tokens=MAX_TOKENS_ETAPA2,
                temperature=0.0,
                use_cache=False,
                response_schema=ETAPA2_RESPONSE_SCHEMA,
                schema_name="etapa2_resultado",
            )
            resultado = _resultado_etapa2_from_json(payload)
            logger.info("Etapa 2 estruturada (JSON) concluída com sucesso na tentativa %d.", attempt)
            break
        except Exception as e:
            structured_error = e
            logger.warning("Falha no modo estruturado da Etapa 2 (tentativa %d): %s", attempt, e)

    if resultado is None:
        logger.warning(
            "Falha persistente no modo estruturado da Etapa 2 (%s). "
            "Usando fallback legado de texto livre.",
            structured_error,
        )
        response = chamar_llm(
            messages=legacy_messages,
            model=model,
            max_tokens=MAX_TOKENS_ETAPA2,
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

    assert resultado is not None

    _enriquecer_evidencias_temas(resultado.temas, texto_acordao)

    # 4.1.5 — Validate themes
    alertas_temas = _validar_temas(resultado.temas)
    alertas_evidencia = _validar_evidencias_temas(resultado.temas, texto_acordao)

    # 4.3 — Validate obstacles
    alertas_obices = _validar_obices(resultado.temas, texto_acordao)

    total_alertas = len(alertas_temas) + len(alertas_evidencia) + len(alertas_obices)
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
    temas_aggregados = [tema for r in resultados for tema in r.temas]
    merged.temas = _deduplicar_temas_semanticos(temas_aggregados)

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
    chunking_audit: dict | None = None,
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
        if chunking_audit is not None:
            chunking_audit.update({
                "aplicado": False,
                "motivo": "chunking_disabled",
            })
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
        if chunking_audit is not None:
            chunking_audit.update({
                "aplicado": False,
                "motivo": "fits_context",
                "total_tokens_estimados": tokens_total,
                "limite_seguro": limite_seguro,
            })
        return executar_etapa2(texto_acordao, resultado_etapa1, prompt_sistema, modelo_override=modelo_override)

    # Document is too large — apply map-reduce chunking
    logger.warning(
        "⚠️  Documento grande detectado (%d tokens, limite: %d). "
        "Aplicando map-reduce (mini -> forte)...",
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
        chunking_audit["tokens_contexto"] = tokens_context

    logger.info("📦 Documento dividido em %d chunks. Gerando resumos...", len(chunks))
    summaries: list[dict] = []

    for i, chunk in enumerate(chunks, 1):
        logger.info("🔄 Resumindo chunk %d/%d...", i, len(chunks))

        try:
            summary = _summarizar_chunk_etapa2(chunk, i, len(chunks))
            summaries.append(summary)
        except Exception as e:
            logger.error("❌ Erro ao resumir chunk %d/%d: %s", i, len(chunks), e)
            continue

    if not summaries:
        raise RuntimeError("Nenhum chunk foi resumido com sucesso")
    if chunking_audit is not None:
        chunking_audit["chunks_resumidos"] = len(summaries)
        chunking_audit["chunks_falhos"] = len(chunks) - len(summaries)

    resumo_compacto = _compactar_resumos_etapa2(summaries)
    user_message = (
        ETAPA2_USER_INSTRUCTION
        + "Use SOMENTE os resumos estruturados abaixo para gerar a saída final da Etapa 2.\n"
        + "Não invente dados e mantenha exatamente os rótulos obrigatórios.\n\n"
        + "--- DISPOSITIVOS VIOLADOS IDENTIFICADOS NA ETAPA 1 ---\n"
        + ("\n".join(f"• {d}" for d in resultado_etapa1.dispositivos_violados) if resultado_etapa1.dispositivos_violados else "[NÃO CONSTA NO DOCUMENTO]")
        + "\n--- FIM DOS DISPOSITIVOS ---\n\n"
        + "--- RESUMOS ESTRUTURADOS DOS CHUNKS ---\n"
        + resumo_compacto
    )

    if modelo_override:
        model = modelo_override
    else:
        model = get_model_for_task(TaskType.LEGAL_ANALYSIS)

    messages = build_messages(
        stage="etapa2",
        user_text=user_message,
        legacy_system_prompt=prompt_sistema.strip() if prompt_sistema and prompt_sistema.strip() else None,
    )
    response = chamar_llm(
        messages=messages,
        model=model,
        max_tokens=MAX_TOKENS_ETAPA2,
    )
    resultado_final = _parse_resposta_etapa2(response.content)
    resultado_final.temas = _deduplicar_temas_semanticos(resultado_final.temas)

    _enriquecer_evidencias_temas(resultado_final.temas, texto_acordao)
    alertas_temas = _validar_temas(resultado_final.temas)
    alertas_evidencia = _validar_evidencias_temas(resultado_final.temas, texto_acordao)
    alertas_obices = _validar_obices(resultado_final.temas, texto_acordao)
    total_alertas = len(alertas_temas) + len(alertas_evidencia) + len(alertas_obices)

    if total_alertas:
        logger.warning("Etapa 2 (map-reduce) concluída com %d alerta(s)", total_alertas)
    else:
        logger.info(
            "✅ Etapa 2 concluída com map-reduce (%d chunks resumidos, %d temas)",
            len(summaries), len(resultado_final.temas),
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
        messages = build_messages(
            stage="etapa2",
            user_text=(
                f"Analise o tema {tema_numero} do acórdão em detalhes.\n\n"
                f"Identifique: matéria controvertida, conclusão/fundamentos, "
                f"base vinculante, óbices/súmulas, e trecho para transcrição.\n\n"
                f"TEMA:\n{tema_texto}\n\n"
                f"CONTEXTO DO ACÓRDÃO:\n{texto_acordao[:2000]}"
            ),
            legacy_system_prompt=prompt_sistema.strip() if prompt_sistema and prompt_sistema.strip() else None,
        )
        response = chamar_llm(
            messages=messages,
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
    messages = build_messages(
        stage="etapa2",
        user_text=user_message,
        legacy_system_prompt=prompt_sistema.strip() if prompt_sistema and prompt_sistema.strip() else None,
    )
    response = chamar_llm(
        messages=messages,
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
    resultado.temas = _deduplicar_temas_semanticos(resultado.temas)

    _enriquecer_evidencias_temas(resultado.temas, texto_acordao)

    # Validation
    alertas_temas = _validar_temas(resultado.temas)
    alertas_evidencia = _validar_evidencias_temas(resultado.temas, texto_acordao)
    alertas_obices = _validar_obices(resultado.temas, texto_acordao)

    total_alertas = len(alertas_temas) + len(alertas_evidencia) + len(alertas_obices)
    if total_alertas:
        logger.warning("Etapa 2 (paralelo) concluída com %d alerta(s)", total_alertas)
    else:
        logger.info(
            "✅ Etapa 2 (paralelo) concluída: %d tema(s) identificados com %d workers",
            len(resultado.temas), workers,
        )

    return resultado
