"""Stage 1: Appeal petition analysis — structured data extraction."""

import json
import logging
import re

import tiktoken

from src.config import (
    CONFIDENCE_THRESHOLD_FIELD,
    CONTEXT_LIMIT_TOKENS,
    CONTEXT_WARNING_RATIO,
    ENABLE_CHUNKING,
    ENABLE_ETAPA1_CRITICAL_FIELDS_CONSENSUS,
    MAX_TOKENS_ETAPA1,
    MAX_TOKENS_INTERMEDIATE,
    MAX_CONTEXT_TOKENS,
    TOKEN_BUDGET_RATIO,
)
from src.llm_client import chamar_llm, chamar_llm_json
from src.model_router import TaskType, get_model_for_task
from src.models import CampoEvidencia, ResultadoEtapa1
from src.prompt_loader import build_messages

logger = logging.getLogger("assessor_ai")

CRITICAL_FIELDS_ETAPA1: tuple[str, ...] = (
    "numero_processo",
    "recorrente",
    "especie_recurso",
)
ETAPA1_STRUCTURED_MAX_ATTEMPTS = 3
ETAPA1_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "numero_processo": {"type": "string"},
        "recorrente": {"type": "string"},
        "recorrido": {"type": "string"},
        "especie_recurso": {"type": "string"},
        "permissivo_constitucional": {"type": "string"},
        "camara_civel": {"type": "string"},
        "dispositivos_violados": {"type": "array", "items": {"type": "string"}},
        "justica_gratuita": {"type": "boolean"},
        "efeito_suspensivo": {"type": "boolean"},
        "evidencias_campos": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "citacao_literal": {"type": "string"},
                    "pagina": {"type": ["integer", "null"]},
                    "ancora": {"type": "string"},
                    "offset_inicio": {"type": ["integer", "null"]},
                },
            },
        },
    },
    "required": ["numero_processo", "recorrente", "especie_recurso"],
    "additionalProperties": True,
}


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
        # Truncate keeping ~60% of context limit (leave room for prompt + response)
        max_chars = int(len(texto) * (CONTEXT_LIMIT_TOKENS * 0.6 / tokens_estimados))
        marker = "\n\n[... CONTEÚDO INTERMEDIÁRIO OMITIDO POR LIMITE DE CONTEXTO ...]\n\n"
        if max_chars <= 0:
            return ""

        # Preserve beginning and end to reduce risk of losing dispositive/decisive sections.
        if max_chars <= len(marker) + 200:
            texto = texto[:max_chars]
            logger.info("Texto truncado (corte simples) para ~%d caracteres", len(texto))
            return texto

        head_chars = int(max_chars * 0.65)
        tail_chars = max_chars - head_chars - len(marker)
        if tail_chars < 100:
            head_chars = max(100, max_chars - len(marker) - 100)
            tail_chars = max_chars - head_chars - len(marker)

        texto = texto[:head_chars] + marker + texto[-tail_chars:]
        logger.info(
            "Texto truncado com preservação de extremos: head=%d, tail=%d, total=%d chars",
            head_chars,
            tail_chars,
            len(texto),
        )

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

ETAPA1_STRUCTURED_DEVELOPER = """
Você receberá uma petição recursal e deve retornar APENAS JSON válido.
Formato obrigatório:
{
  "numero_processo": "string",
  "recorrente": "string",
  "recorrido": "string",
  "especie_recurso": "string",
  "permissivo_constitucional": "string",
  "camara_civel": "string",
  "dispositivos_violados": ["string"],
  "justica_gratuita": true,
  "efeito_suspensivo": false,
  "evidencias_campos": {
    "numero_processo": {"citacao_literal": "string", "pagina": 1, "ancora": "string", "offset_inicio": 123},
    "recorrente": {"citacao_literal": "string", "pagina": 1, "ancora": "string", "offset_inicio": 234},
    "especie_recurso": {"citacao_literal": "string", "pagina": 1, "ancora": "string", "offset_inicio": 345}
  }
}
Regras:
- Use apenas dados presentes no documento.
- Se não constar, use string vazia ou lista vazia.
- Para campos críticos preenchidos (numero_processo, recorrente, especie_recurso), inclua evidência correspondente.
- Se não conseguir identificar página/offset com segurança, use pagina=1 e offset_inicio=-1.
- Não inclua texto fora do JSON.
""".strip()

ETAPA1_CHUNK_SUMMARY_DEVELOPER = """
Você receberá um chunk de petição recursal.
Resuma em JSON ESTRITAMENTE com os campos:
{
  "numero_processo": "string",
  "recorrente": "string",
  "recorrido": "string",
  "especie_recurso": "string",
  "permissivo_constitucional": "string",
  "camara_orgao": "string",
  "dispositivos_violados": ["string"],
  "fatos_argumentos": ["string"],
  "pedidos_explicitos": ["justica_gratuita", "efeito_suspensivo"],
  "trechos_chave": ["string"]
}
Regras:
- Use somente o texto do chunk.
- Não invente.
- Campo ausente: "[NÃO CONSTA NO DOCUMENTO]".
- Resposta apenas JSON válido.
""".strip()

ETAPA1_CRITICAL_CONSENSUS_DEVELOPER = """
CONSENSO_N2_ETAPA1
Retorne APENAS JSON válido para os campos críticos da Etapa 1:
{
  "numero_processo": "string",
  "recorrente": "string",
  "especie_recurso": "string",
  "evidencias_campos": {
    "numero_processo": {"citacao_literal": "string", "pagina": 1, "ancora": "string", "offset_inicio": 0},
    "recorrente": {"citacao_literal": "string", "pagina": 1, "ancora": "string", "offset_inicio": 0},
    "especie_recurso": {"citacao_literal": "string", "pagina": 1, "ancora": "string", "offset_inicio": 0}
  }
}
Regras:
- Use exclusivamente o texto-fonte.
- Não invente.
- Se não constar, use string vazia.
- Não inclua markdown nem texto fora do JSON.
""".strip()

ETAPA1_FREE_TEXT_TO_JSON_DEVELOPER = """
Você receberá a saída textual livre de uma análise de Etapa 1.
Converta para JSON válido no formato:
{
  "numero_processo": "string",
  "recorrente": "string",
  "recorrido": "string",
  "especie_recurso": "string",
  "permissivo_constitucional": "string",
  "camara_civel": "string",
  "dispositivos_violados": ["string"],
  "justica_gratuita": true,
  "efeito_suspensivo": false,
  "evidencias_campos": {
    "numero_processo": {"citacao_literal": "string", "pagina": 1, "ancora": "string", "offset_inicio": 0},
    "recorrente": {"citacao_literal": "string", "pagina": 1, "ancora": "string", "offset_inicio": 0},
    "especie_recurso": {"citacao_literal": "string", "pagina": 1, "ancora": "string", "offset_inicio": 0}
  }
}
Regras:
- Use apenas informações presentes no texto fornecido.
- Sem markdown e sem texto fora do JSON.
- Se ausente, usar string vazia/lista vazia/false.
""".strip()


def _to_list(value: object) -> list[str]:
    """Normalize JSON field into list[str]."""
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _extrair_json_de_texto_livre(texto: str) -> dict | None:
    """Best-effort extraction of a JSON object from free text output."""
    bruto = (texto or "").strip()
    if not bruto:
        return None

    try:
        payload = json.loads(bruto)
        return payload if isinstance(payload, dict) else None
    except Exception:
        pass

    # Try extracting first JSON-like block.
    start = bruto.find("{")
    end = bruto.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    bloco = bruto[start:end + 1]
    try:
        payload = json.loads(bloco)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _normalizar_campo_texto(value: object) -> str:
    """Normalize structured JSON text fields and map placeholders to empty."""
    text = str(value or "").strip()
    if not text:
        return ""
    placeholder = text.upper().replace("Ã", "A")
    if placeholder in {"[NAO CONSTA NO DOCUMENTO]", "[NÃO CONSTA NO DOCUMENTO]", "N/A", "NA"}:
        return ""
    return text


def _normalizar_bool(value: object) -> bool:
    """Normalize boolean-like values from JSON payload."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    return text in {"sim", "true", "1", "yes"}


def _normalizar_int(value: object) -> int | None:
    """Normalize integer-like values from JSON payload."""
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

    citacao = _normalizar_campo_texto(value.get("citacao_literal"))
    ancora = _normalizar_campo_texto(value.get("ancora"))
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


def _normalizar_evidencias_campos(payload: object) -> dict[str, CampoEvidencia]:
    """Normalize evidencias_campos mapping from structured JSON payload."""
    if not isinstance(payload, dict):
        return {}

    evidencias: dict[str, CampoEvidencia] = {}
    for campo, raw in payload.items():
        evidencia = _normalizar_evidencia(raw)
        if evidencia:
            evidencias[str(campo).strip()] = evidencia
    return evidencias


def _find_span_case_insensitive(texto: str, termo: str) -> tuple[int, int] | None:
    """Find first case-insensitive span for term in text."""
    termo_limpo = termo.strip()
    if not texto or not termo_limpo:
        return None

    match = re.search(re.escape(termo_limpo), texto, re.IGNORECASE)
    if match:
        return match.start(), match.end()

    # Fallback: flexible whitespace matching
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


def _gerar_evidencia_local(valor: str, texto_entrada: str) -> CampoEvidencia | None:
    """Generate deterministic local evidence from source text for one field."""
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
    """Merge existing and generated evidence, preserving explicit values first."""
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


def _enriquecer_evidencias_campos_criticos(
    resultado: ResultadoEtapa1,
    texto_entrada: str,
) -> None:
    """Backfill missing critical field evidence using deterministic text matching."""
    if resultado.evidencias_campos is None:
        resultado.evidencias_campos = {}

    for campo in CRITICAL_FIELDS_ETAPA1:
        valor = str(getattr(resultado, campo, "") or "").strip()
        if not valor:
            continue

        evidencia_atual = resultado.evidencias_campos.get(campo)
        completa = (
            evidencia_atual is not None
            and bool(evidencia_atual.citacao_literal.strip())
            and bool(evidencia_atual.ancora.strip())
            and evidencia_atual.pagina is not None
        )
        if completa:
            continue

        gerada = _gerar_evidencia_local(valor, texto_entrada)
        if gerada:
            resultado.evidencias_campos[campo] = _merge_evidencia(evidencia_atual, gerada)


def _validar_evidencias_campos_criticos(
    resultado: ResultadoEtapa1,
    texto_entrada: str,
) -> list[str]:
    """Validate critical field evidence presence and basic consistency."""
    alertas: list[str] = []

    for campo in CRITICAL_FIELDS_ETAPA1:
        valor = str(getattr(resultado, campo, "") or "").strip()
        if not valor:
            continue

        evidencia = resultado.evidencias_campos.get(campo)
        if evidencia is None:
            alertas.append(f"Campo crítico sem evidência: {campo}")
            continue

        if not evidencia.citacao_literal.strip():
            alertas.append(f"Evidência sem citação literal: {campo}")
        if evidencia.pagina is None or evidencia.pagina < 1:
            alertas.append(f"Evidência sem página válida: {campo}")
        if not evidencia.ancora.strip():
            alertas.append(f"Evidência sem âncora: {campo}")

        citacao = evidencia.citacao_literal.strip()
        if citacao:
            if campo == "numero_processo":
                valor_num = re.sub(r"\D", "", valor)
                cit_num = re.sub(r"\D", "", citacao)
                if valor_num and cit_num and valor_num not in cit_num:
                    alertas.append(f"Evidência inconsistente para {campo}: valor não consta na citação")
            elif valor.lower() not in citacao.lower():
                alertas.append(f"Evidência inconsistente para {campo}: valor não consta na citação")

    for alerta in alertas:
        logger.warning("🔎 Evidência Etapa 1: %s", alerta)

    return alertas


def _verificar_campo_critico_no_texto(
    campo: str,
    valor: str,
    texto_entrada: str,
) -> bool:
    """Independent verification that a critical field value is present in source text."""
    if not valor.strip():
        return True

    if campo == "numero_processo":
        valor_num = re.sub(r"\D", "", valor)
        texto_num = re.sub(r"\D", "", texto_entrada)
        return bool(valor_num) and valor_num in texto_num

    return _find_span_case_insensitive(texto_entrada, valor) is not None


def _verificador_independente_etapa1(
    resultado: ResultadoEtapa1,
    texto_entrada: str,
) -> list[str]:
    """
    Independent post-LLM verifier for critical fields against source text.

    Stores per-field status in resultado.verificacao_campos.
    """
    alertas: list[str] = []

    for campo in CRITICAL_FIELDS_ETAPA1:
        valor = str(getattr(resultado, campo, "") or "").strip()
        if not valor:
            continue

        ok = _verificar_campo_critico_no_texto(campo, valor, texto_entrada)
        resultado.verificacao_campos[campo] = ok
        if not ok:
            alertas.append(
                f"Verificação independente falhou para {campo}: valor não confirmado no texto-fonte."
            )

    for alerta in alertas:
        logger.warning("🧪 Verificador Etapa 1: %s", alerta)

    return alertas


def _build_retry_hints_etapa1(
    alertas_validacao: list[str],
    alertas_evidencia: list[str],
    alertas_verificador: list[str],
    structured_error: Exception | None = None,
) -> list[str]:
    """Build retry hints focused on specific validation failures."""
    hints: list[str] = []
    if structured_error is not None:
        hints.append(
            "A saída anterior falhou em formato/parse. Retorne JSON válido estrito."
        )
        hints.append(f"Erro observado: {type(structured_error).__name__}: {structured_error}")

    if alertas_validacao:
        hints.append(
            "Corrija campos obrigatórios ausentes: "
            + " | ".join(alertas_validacao)
        )
    if alertas_evidencia:
        hints.append(
            "Corrija evidências dos campos críticos (citação, página, âncora): "
            + " | ".join(alertas_evidencia)
        )
    if alertas_verificador:
        hints.append(
            "Corrija inconsistências semânticas com o texto-fonte: "
            + " | ".join(alertas_verificador)
        )

    if not hints:
        hints.append("Garanta conformidade total com o schema JSON e com os campos críticos.")
    return hints


def _marcar_inconclusivo_se_necessario(
    resultado: ResultadoEtapa1,
    alertas_validacao: list[str],
    alertas_evidencia: list[str],
    alertas_verificador: list[str],
) -> None:
    """Mark Stage 1 result as inconclusive when critical validations still fail."""
    alertas_criticos = alertas_validacao + alertas_evidencia + alertas_verificador
    if not alertas_criticos:
        resultado.inconclusivo = False
        resultado.motivo_inconclusivo = ""
        return

    resultado.inconclusivo = True
    # Keep deterministic compact reason for audit/logging.
    motivo = " | ".join(dict.fromkeys(alertas_criticos))
    resultado.motivo_inconclusivo = motivo[:2000]


def _resultado_etapa1_from_json(payload: dict) -> ResultadoEtapa1:
    """Convert structured JSON payload into ResultadoEtapa1."""
    dispositivos = [
        _normalizar_campo_texto(item)
        for item in _to_list(payload.get("dispositivos_violados"))
    ]
    dispositivos = [item for item in dispositivos if item]

    return ResultadoEtapa1(
        numero_processo=_normalizar_campo_texto(payload.get("numero_processo")),
        recorrente=_normalizar_campo_texto(payload.get("recorrente")),
        recorrido=_normalizar_campo_texto(payload.get("recorrido")),
        especie_recurso=_normalizar_campo_texto(payload.get("especie_recurso")),
        permissivo_constitucional=_normalizar_campo_texto(payload.get("permissivo_constitucional")),
        camara_civel=_normalizar_campo_texto(payload.get("camara_civel")),
        dispositivos_violados=dispositivos,
        justica_gratuita=_normalizar_bool(payload.get("justica_gratuita")),
        efeito_suspensivo=_normalizar_bool(payload.get("efeito_suspensivo")),
        evidencias_campos=_normalizar_evidencias_campos(payload.get("evidencias_campos")),
        texto_formatado=json.dumps(payload, ensure_ascii=False, indent=2),
    )


def _converter_texto_livre_para_resultado_etapa1(
    texto_resposta: str,
    *,
    modelo_override: str | None = None,
) -> ResultadoEtapa1 | None:
    """
    Convert free-text Stage 1 output to structured result without regex as primary path.

    Order:
    1) Parse direct/embedded JSON from text.
    2) Ask LLM to normalize free text into strict JSON.
    3) Return None when both fail (caller may use legacy regex fallback).
    """
    payload_local = _extrair_json_de_texto_livre(texto_resposta)
    if payload_local:
        return _resultado_etapa1_from_json(payload_local)

    model = modelo_override or get_model_for_task(TaskType.PARSING)
    user_text = (
        "Converta a saída textual abaixo para JSON estrito da Etapa 1.\n\n"
        "--- INÍCIO DA SAÍDA LIVRE ---\n"
        f"{texto_resposta}\n"
        "--- FIM DA SAÍDA LIVRE ---\n"
    )
    messages = build_messages(
        stage="etapa1",
        user_text=user_text,
        developer_override=ETAPA1_FREE_TEXT_TO_JSON_DEVELOPER,
    )
    try:
        payload = chamar_llm_json(
            messages=messages,
            model=model,
            temperature=0.0,
            max_tokens=MAX_TOKENS_INTERMEDIATE,
            use_cache=False,
            response_schema=ETAPA1_RESPONSE_SCHEMA,
            schema_name="etapa1_resultado",
        )
        if isinstance(payload, dict):
            return _resultado_etapa1_from_json(payload)
    except Exception as e:
        logger.warning("Falha ao normalizar saída livre da Etapa 1 para JSON: %s", e)

    return None


def _summarizar_chunk_etapa1(chunk: str, chunk_idx: int, total: int) -> dict:
    """Summarize one Stage 1 chunk using mini model to reduce strong-model tokens."""
    model = get_model_for_task(TaskType.PARSING)
    user_text = (
        f"Chunk {chunk_idx}/{total} da petição recursal.\n"
        "Extraia os campos estruturados em JSON.\n\n"
        "--- INÍCIO DO CHUNK ---\n"
        f"{chunk}\n"
        "--- FIM DO CHUNK ---\n"
    )
    messages = build_messages(
        stage="etapa1",
        user_text=user_text,
        include_references=False,
        developer_override=ETAPA1_CHUNK_SUMMARY_DEVELOPER,
    )
    logger.info("🧩 Etapa 1 resumo chunk %d/%d — modelo=%s", chunk_idx, total, model)
    summary = chamar_llm_json(
        messages=messages,
        model=model,
        temperature=0.0,
        max_tokens=MAX_TOKENS_INTERMEDIATE,
    )
    return summary if isinstance(summary, dict) else {}


def _compactar_resumos_etapa1(resumos: list[dict]) -> str:
    """Build a compact deterministic context from chunk summaries."""
    blocos: list[str] = []
    for i, r in enumerate(resumos, 1):
        dispositivos = _to_list(r.get("dispositivos_violados"))[:8]
        fatos = _to_list(r.get("fatos_argumentos"))[:8]
        pedidos = _to_list(r.get("pedidos_explicitos"))[:4]
        trechos = _to_list(r.get("trechos_chave"))[:5]

        bloco = [
            f"[Resumo Chunk {i}]",
            f"numero_processo: {r.get('numero_processo', '[NÃO CONSTA NO DOCUMENTO]')}",
            f"recorrente: {r.get('recorrente', '[NÃO CONSTA NO DOCUMENTO]')}",
            f"recorrido: {r.get('recorrido', '[NÃO CONSTA NO DOCUMENTO]')}",
            f"especie_recurso: {r.get('especie_recurso', '[NÃO CONSTA NO DOCUMENTO]')}",
            f"permissivo_constitucional: {r.get('permissivo_constitucional', '[NÃO CONSTA NO DOCUMENTO]')}",
            f"camara_orgao: {r.get('camara_orgao', '[NÃO CONSTA NO DOCUMENTO]')}",
            "dispositivos_violados: " + ("; ".join(dispositivos) if dispositivos else "[NÃO CONSTA NO DOCUMENTO]"),
            "fatos_argumentos: " + ("; ".join(fatos) if fatos else "[NÃO CONSTA NO DOCUMENTO]"),
            "pedidos_explicitos: " + ("; ".join(pedidos) if pedidos else "[NÃO CONSTA NO DOCUMENTO]"),
            "trechos_chave: " + (" | ".join(trechos) if trechos else "[NÃO CONSTA NO DOCUMENTO]"),
        ]
        blocos.append("\n".join(bloco))
    resumo_compacto = "\n\n".join(blocos)
    logger.info(
        "📦 Resumos Etapa 1 compactados: chunks=%d, chars=%d, tokens_estimados=%d",
        len(resumos),
        len(resumo_compacto),
        estimar_tokens(resumo_compacto),
    )
    return resumo_compacto


def _score_campo_critico_etapa1(resultado: ResultadoEtapa1, campo: str) -> float:
    """Compute confidence score (0..1) for one critical field in Stage 1."""
    valor = str(getattr(resultado, campo, "") or "").strip()
    if not valor:
        return 0.0

    evidencia = resultado.evidencias_campos.get(campo)
    checks = [
        True,
        evidencia is not None,
        bool(evidencia and evidencia.citacao_literal.strip()),
        bool(evidencia and evidencia.pagina is not None and evidencia.pagina >= 1),
        bool(evidencia and evidencia.ancora.strip()),
        resultado.verificacao_campos.get(campo) is True,
    ]
    return sum(1 for ok in checks if ok) / len(checks)


def _extrair_campos_criticos_de_alertas(alertas: list[str]) -> set[str]:
    """Extract critical field names cited in validation alerts."""
    campos: set[str] = set()
    for alerta in alertas:
        alerta_norm = str(alerta or "").lower()
        for campo in CRITICAL_FIELDS_ETAPA1:
            if campo in alerta_norm:
                campos.add(campo)
    return campos


def _normalizar_valor_consenso(campo: str, valor: str) -> str:
    """Normalize field value for consensus comparison."""
    raw = str(valor or "").strip()
    if not raw:
        return ""
    if campo == "numero_processo":
        return re.sub(r"\D", "", raw)
    return re.sub(r"\s+", " ", raw).strip().casefold()


def _detectar_campos_baixa_confianca_etapa1(
    resultado: ResultadoEtapa1,
    *,
    alertas_validacao: list[str],
    alertas_evidencia: list[str],
    alertas_verificador: list[str],
    had_structured_instability: bool,
) -> list[str]:
    """Detect critical fields that should enter N=2 consensus pass."""
    alertas = alertas_validacao + alertas_evidencia + alertas_verificador
    campos = _extrair_campos_criticos_de_alertas(alertas)

    for campo in CRITICAL_FIELDS_ETAPA1:
        score = _score_campo_critico_etapa1(resultado, campo)
        if score < CONFIDENCE_THRESHOLD_FIELD:
            campos.add(campo)
        elif had_structured_instability and str(getattr(resultado, campo, "") or "").strip():
            # Instability in structured extraction is treated as low confidence signal.
            campos.add(campo)

    return sorted(campos)


def _aplicar_consenso_n2_campos_criticos(
    resultado: ResultadoEtapa1,
    *,
    texto_recurso_original: str,
    model: str,
    campos_alvo: list[str],
) -> dict[str, list[str]]:
    """Run N=2 consensus for critical fields and apply only convergent verified values."""
    diagnostico: dict[str, list[str]] = {
        "aplicados": [],
        "divergentes": [],
        "falhas_chamada": [],
    }
    if not campos_alvo:
        return diagnostico

    votos: dict[str, list[tuple[str, str, CampoEvidencia]]] = {campo: [] for campo in campos_alvo}
    campos_str = ", ".join(campos_alvo)
    user_text = (
        "Reavalie SOMENTE os campos críticos da Etapa 1 com evidências.\n"
        f"Campos-alvo: {campos_str}\n\n"
        "Texto do recurso:\n"
        f"{texto_recurso_original}"
    )
    messages = build_messages(
        stage="etapa1",
        user_text=user_text,
        include_references=False,
        developer_override=ETAPA1_CRITICAL_CONSENSUS_DEVELOPER,
    )

    for tentativa in range(1, 3):
        try:
            payload = chamar_llm_json(
                messages=messages,
                model=model,
                max_tokens=MAX_TOKENS_INTERMEDIATE,
                temperature=0.0,
                use_cache=False,
                response_schema=ETAPA1_RESPONSE_SCHEMA,
                schema_name="etapa1_resultado",
            )
        except Exception as e:
            diagnostico["falhas_chamada"].append(f"tentativa_{tentativa}:{type(e).__name__}")
            continue

        candidato = _resultado_etapa1_from_json(payload)
        _enriquecer_evidencias_campos_criticos(candidato, texto_recurso_original)
        _verificador_independente_etapa1(candidato, texto_recurso_original)

        for campo in campos_alvo:
            valor = str(getattr(candidato, campo, "") or "").strip()
            if not valor:
                continue
            if candidato.verificacao_campos.get(campo) is not True:
                continue
            evidencia = candidato.evidencias_campos.get(campo)
            if (
                evidencia is None
                or not evidencia.citacao_literal.strip()
                or evidencia.pagina is None
                or evidencia.pagina < 1
                or not evidencia.ancora.strip()
            ):
                continue
            votos[campo].append((_normalizar_valor_consenso(campo, valor), valor, evidencia))

    for campo in campos_alvo:
        votos_campo = votos.get(campo, [])
        if len(votos_campo) < 2:
            continue

        norm_1, valor_1, evid_1 = votos_campo[0]
        norm_2, valor_2, evid_2 = votos_campo[1]
        if not norm_1 or norm_1 != norm_2:
            diagnostico["divergentes"].append(campo)
            continue

        valor_consenso = valor_1 if len(valor_1) >= len(valor_2) else valor_2
        evidencia_consenso = _merge_evidencia(evid_1, evid_2)
        valor_atual = str(getattr(resultado, campo, "") or "").strip()
        if valor_consenso and valor_consenso != valor_atual:
            setattr(resultado, campo, valor_consenso)
            diagnostico["aplicados"].append(campo)
        resultado.evidencias_campos[campo] = _merge_evidencia(
            resultado.evidencias_campos.get(campo),
            evidencia_consenso,
        )
        resultado.verificacao_campos[campo] = True

    return diagnostico


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
    texto_recurso_original = texto_recurso
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
    legacy_messages = build_messages(
        stage="etapa1",
        user_text=user_message,
        legacy_system_prompt=prompt_sistema.strip() if prompt_sistema and prompt_sistema.strip() else None,
    )
    # First try strict JSON structured output with retry guided by validation errors.
    resultado: ResultadoEtapa1 | None = None
    structured_success = False
    structured_error: Exception | None = None
    retry_hints: list[str] = []
    had_structured_instability = False
    for attempt in range(1, ETAPA1_STRUCTURED_MAX_ATTEMPTS + 1):
        developer_prompt = ETAPA1_STRUCTURED_DEVELOPER
        if retry_hints:
            developer_prompt = (
                ETAPA1_STRUCTURED_DEVELOPER
                + "\n\nCorreções obrigatórias nesta tentativa:\n"
                + "\n".join(f"- {hint}" for hint in retry_hints)
                + "\nReforço: resposta EXCLUSIVAMENTE JSON válido, sem markdown."
            )

        attempt_messages = build_messages(
            stage="etapa1",
            user_text=user_message,
            developer_override=developer_prompt,
        )
        try:
            payload = chamar_llm_json(
                messages=attempt_messages,
                model=model,
                max_tokens=MAX_TOKENS_ETAPA1,
                temperature=0.0,
                use_cache=False,
                response_schema=ETAPA1_RESPONSE_SCHEMA,
                schema_name="etapa1_resultado",
            )
            candidato = _resultado_etapa1_from_json(payload)
            _enriquecer_evidencias_campos_criticos(candidato, texto_recurso_original)
            alertas_validacao = _validar_campos(candidato, texto_recurso)
            alertas_evidencia = _validar_evidencias_campos_criticos(candidato, texto_recurso_original)
            alertas_verificador = _verificador_independente_etapa1(candidato, texto_recurso_original)

            resultado = candidato
            if not alertas_validacao and not alertas_evidencia and not alertas_verificador:
                structured_success = True
                logger.info("Etapa 1 estruturada (JSON) concluída com sucesso na tentativa %d.", attempt)
                break

            retry_hints = _build_retry_hints_etapa1(
                alertas_validacao,
                alertas_evidencia,
                alertas_verificador,
            )
            had_structured_instability = True
            logger.warning(
                "Etapa 1 estruturada com inconsistências na tentativa %d; preparando retry orientado.",
                attempt,
            )
        except Exception as e:
            structured_error = e
            retry_hints = _build_retry_hints_etapa1([], [], [], structured_error=e)
            had_structured_instability = True
            logger.warning("Falha no modo estruturado da Etapa 1 (tentativa %d): %s", attempt, e)

    if not structured_success:
        had_structured_instability = True
        logger.warning(
            "Falha persistente no modo estruturado da Etapa 1 (%s). "
            "Usando fallback legado de texto livre.",
            structured_error,
        )
        response = chamar_llm(
            messages=legacy_messages,
            model=model,
            max_tokens=MAX_TOKENS_ETAPA1,
        )

        # 3.3.4 Log estimated vs actual tokens
        logger.info(
            "Tokens — estimados: %d, reais: %d (prompt=%d, completion=%d)",
            tokens_pre,
            response.tokens.total_tokens,
            response.tokens.prompt_tokens,
            response.tokens.completion_tokens,
        )

        # Prefer structured normalization from free text; keep regex as last resort.
        resultado_convertido = _converter_texto_livre_para_resultado_etapa1(
            response.content,
            modelo_override=modelo_override,
        )
        if resultado_convertido is not None:
            resultado = resultado_convertido
        else:
            resultado = _parse_resposta_llm(response.content)

    assert resultado is not None

    _enriquecer_evidencias_campos_criticos(resultado, texto_recurso_original)

    # 3.1.5 Validate
    alertas_validacao = _validar_campos(resultado, texto_recurso)
    alertas_evidencia = _validar_evidencias_campos_criticos(resultado, texto_recurso_original)
    alertas_verificador = _verificador_independente_etapa1(resultado, texto_recurso_original)
    campos_baixa_confianca = _detectar_campos_baixa_confianca_etapa1(
        resultado,
        alertas_validacao=alertas_validacao,
        alertas_evidencia=alertas_evidencia,
        alertas_verificador=alertas_verificador,
        had_structured_instability=had_structured_instability,
    )
    if ENABLE_ETAPA1_CRITICAL_FIELDS_CONSENSUS and campos_baixa_confianca:
        logger.info(
            "🔁 Consenso N=2 acionado para campos críticos da Etapa 1: %s",
            ", ".join(campos_baixa_confianca),
        )
        diagnostico_consenso = _aplicar_consenso_n2_campos_criticos(
            resultado,
            texto_recurso_original=texto_recurso_original,
            model=model,
            campos_alvo=campos_baixa_confianca,
        )
        if diagnostico_consenso["aplicados"]:
            logger.info(
                "✅ Consenso N=2 aplicou atualização em: %s",
                ", ".join(sorted(set(diagnostico_consenso["aplicados"]))),
            )
            _enriquecer_evidencias_campos_criticos(resultado, texto_recurso_original)
            alertas_validacao = _validar_campos(resultado, texto_recurso)
            alertas_evidencia = _validar_evidencias_campos_criticos(resultado, texto_recurso_original)
            alertas_verificador = _verificador_independente_etapa1(resultado, texto_recurso_original)
        if diagnostico_consenso["divergentes"]:
            logger.warning(
                "Consenso N=2 sem convergência para: %s",
                ", ".join(sorted(set(diagnostico_consenso["divergentes"]))),
            )
        if diagnostico_consenso["falhas_chamada"]:
            logger.warning(
                "Consenso N=2 com falha em chamada(s): %s",
                ", ".join(diagnostico_consenso["falhas_chamada"]),
            )

    # 3.1.6 Hallucination check
    alertas_alucinacao = _detectar_alucinacao(resultado, texto_recurso_original)
    _marcar_inconclusivo_se_necessario(
        resultado,
        alertas_validacao,
        alertas_evidencia,
        alertas_verificador,
    )

    if resultado.inconclusivo:
        logger.warning("🚫 Etapa 1 marcada como INCONCLUSIVA: %s", resultado.motivo_inconclusivo)

    if alertas_validacao or alertas_alucinacao or alertas_evidencia or alertas_verificador:
        logger.warning(
            "Etapa 1 concluída com %d alerta(s)",
            len(alertas_validacao)
            + len(alertas_alucinacao)
            + len(alertas_evidencia)
            + len(alertas_verificador),
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
            if r.evidencias_campos.get("numero_processo"):
                merged.evidencias_campos["numero_processo"] = r.evidencias_campos["numero_processo"]
        if not merged.recorrente and r.recorrente:
            merged.recorrente = r.recorrente
            if r.evidencias_campos.get("recorrente"):
                merged.evidencias_campos["recorrente"] = r.evidencias_campos["recorrente"]
        if not merged.recorrido and r.recorrido:
            merged.recorrido = r.recorrido
        if not merged.especie_recurso and r.especie_recurso:
            merged.especie_recurso = r.especie_recurso
            if r.evidencias_campos.get("especie_recurso"):
                merged.evidencias_campos["especie_recurso"] = r.evidencias_campos["especie_recurso"]
        if not merged.permissivo_constitucional and r.permissivo_constitucional:
            merged.permissivo_constitucional = r.permissivo_constitucional
        if not merged.camara_civel and r.camara_civel:
            merged.camara_civel = r.camara_civel

    # Fill missing critical evidences from any chunk that has them.
    for campo in CRITICAL_FIELDS_ETAPA1:
        if merged.evidencias_campos.get(campo):
            continue
        for r in resultados:
            evidencia = r.evidencias_campos.get(campo)
            if evidencia:
                merged.evidencias_campos[campo] = evidencia
                break

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

    inconclusivos = [r.motivo_inconclusivo for r in resultados if r.inconclusivo and r.motivo_inconclusivo]
    if inconclusivos:
        merged.inconclusivo = True
        merged.motivo_inconclusivo = " | ".join(dict.fromkeys(inconclusivos))[:2000]

    logger.info("✅ Resultados mesclados com sucesso")
    return merged


def executar_etapa1_com_chunking(
    texto_recurso: str,
    prompt_sistema: str,
    modelo_override: str | None = None,
    chunking_audit: dict | None = None,
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
    tokens_estimados = estimar_tokens(texto_recurso)
    limite_seguro = int(MAX_CONTEXT_TOKENS * TOKEN_BUDGET_RATIO)

    if not ENABLE_CHUNKING:
        logger.debug("Chunking desabilitado — usando fluxo padrão")
        if chunking_audit is not None:
            chunking_audit.update({
                "aplicado": False,
                "motivo": "chunking_disabled",
                "total_tokens_estimados": tokens_estimados,
                "limite_seguro": limite_seguro,
            })
        return executar_etapa1(texto_recurso, prompt_sistema, modelo_override=modelo_override)

    # If fits in one request, use standard flow
    if tokens_estimados <= limite_seguro:
        logger.debug("Documento cabe em uma requisição (%d tokens)", tokens_estimados)
        if chunking_audit is not None:
            chunking_audit.update({
                "aplicado": False,
                "motivo": "fits_context",
                "total_tokens_estimados": tokens_estimados,
                "limite_seguro": limite_seguro,
            })
        return executar_etapa1(texto_recurso, prompt_sistema, modelo_override=modelo_override)

    # Document is too large — apply map-reduce chunking
    logger.warning(
        "⚠️  Documento grande detectado (%d tokens, limite: %d). "
        "Aplicando map-reduce (mini -> forte)...",
        tokens_estimados, limite_seguro,
    )

    # Import chunker (lazy to avoid circular imports)
    from src.token_manager import text_chunker

    chunks, coverage_report = text_chunker.chunk_text_with_coverage(texto_recurso, model="gpt-4o")
    if chunking_audit is not None:
        chunking_audit.update(coverage_report)
        chunking_audit["limite_seguro"] = limite_seguro
    logger.info("📦 Documento dividido em %d chunks. Gerando resumos intermediários...", len(chunks))
    summaries: list[dict] = []

    for i, chunk in enumerate(chunks, 1):
        logger.info("🔄 Resumindo chunk %d/%d...", i, len(chunks))

        try:
            summary = _summarizar_chunk_etapa1(chunk, i, len(chunks))
            summaries.append(summary)
        except Exception as e:
            logger.error("❌ Erro ao resumir chunk %d/%d: %s", i, len(chunks), e)
            continue

    if not summaries:
        raise RuntimeError("Nenhum chunk foi resumido com sucesso")
    if chunking_audit is not None:
        chunking_audit["chunks_resumidos"] = len(summaries)
        chunking_audit["chunks_falhos"] = len(chunks) - len(summaries)

    resumo_compacto = _compactar_resumos_etapa1(summaries)
    user_message = (
        ETAPA1_USER_INSTRUCTION
        + "Use SOMENTE os resumos estruturados abaixo para montar a saída final.\n"
        + "Não invente e mantenha exatamente o formato da Etapa 1.\n\n"
        + "--- RESUMOS ESTRUTURADOS DOS CHUNKS ---\n"
        + resumo_compacto
    )

    if modelo_override:
        model = modelo_override
    else:
        model = get_model_for_task(TaskType.LEGAL_ANALYSIS)

    messages = build_messages(
        stage="etapa1",
        user_text=user_message,
        legacy_system_prompt=prompt_sistema.strip() if prompt_sistema and prompt_sistema.strip() else None,
    )
    response = chamar_llm(
        messages=messages,
        model=model,
        max_tokens=MAX_TOKENS_ETAPA1,
    )

    resultado_final = _converter_texto_livre_para_resultado_etapa1(
        response.content,
        modelo_override=modelo_override,
    )
    if resultado_final is None:
        resultado_final = _parse_resposta_llm(response.content)
    _enriquecer_evidencias_campos_criticos(resultado_final, texto_recurso)
    alertas_validacao = _validar_campos(resultado_final, texto_recurso)
    alertas_evidencia = _validar_evidencias_campos_criticos(resultado_final, texto_recurso)
    alertas_verificador = _verificador_independente_etapa1(resultado_final, texto_recurso)
    _detectar_alucinacao(resultado_final, texto_recurso)
    _marcar_inconclusivo_se_necessario(
        resultado_final,
        alertas_validacao,
        alertas_evidencia,
        alertas_verificador,
    )
    if resultado_final.inconclusivo:
        logger.warning(
            "🚫 Etapa 1 (chunking) marcada como INCONCLUSIVA: %s",
            resultado_final.motivo_inconclusivo,
        )

    logger.info("✅ Etapa 1 concluída com map-reduce (%d chunks resumidos)", len(summaries))
    return resultado_final
