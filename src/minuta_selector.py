"""
Seletor de minuta de referência para few-shot na Etapa 3.

Dado o contexto do caso atual (tipo de recurso, matérias, súmulas),
encontra a minuta mais similar na base de referência.

Uso:
    from src.minuta_selector import selecionar_minuta_referencia
    texto = selecionar_minuta_referencia(
        tipo_recurso="recurso_especial",
        sumulas=["7/STJ", "283/STF"],
        materias=["reexame_de_prova"],
        decisao_estimada="inadmitido",
    )
"""

from __future__ import annotations

import json
import logging
import math
import pickle
import re
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("assessor_ai")

BASE_DIR = Path(__file__).resolve().parent.parent
INDEX_FILE = BASE_DIR / "minutas_referencia" / "index.json"
TEXTOS_DIR = BASE_DIR / "minutas_referencia" / "textos"
EMBEDDINGS_FILE = BASE_DIR / "minutas_referencia" / "embeddings.pkl"
EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# Cache em memória (carregado uma vez) — protegido por lock para thread-safety
_INDEX: list[dict] | None = None
_INDEX_LOCK = threading.Lock()
_EMBEDDINGS: dict[str, list[float]] | None = None
_EMBEDDINGS_LOCK = threading.Lock()
_EMBEDDING_MODEL: Any | None = None
_EMBEDDING_MODEL_LOCK = threading.Lock()
MAX_CHARS_REFERENCIA = 6_000  # ~1500 tokens — suficiente sem estourar contexto
SECTION_HEADER_PATTERN = re.compile(
    r"(?im)^[\t \f]*(?P<label>III|II|I)\s*(?:[-–—:.)](?:\s|$)|$)"
)


def _carregar_indice() -> list[dict]:
    """Carrega o índice em memória (lazy, singleton, thread-safe)."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    with _INDEX_LOCK:
        # Double-checked locking: another thread may have loaded it while we waited
        if _INDEX is None:
            if not INDEX_FILE.exists():
                logger.warning("Índice de minutas não encontrado: %s", INDEX_FILE)
                _INDEX = []
            else:
                _INDEX = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
                logger.info("📚 %d minutas de referência carregadas.", len(_INDEX))
    return _INDEX


def _carregar_embeddings() -> dict[str, list[float]] | None:
    """Carrega embeddings pré-calculados (lazy, singleton, thread-safe)."""
    global _EMBEDDINGS
    if _EMBEDDINGS is not None:
        return _EMBEDDINGS or None

    with _EMBEDDINGS_LOCK:
        if _EMBEDDINGS is None:
            if not EMBEDDINGS_FILE.exists():
                logger.info("Embeddings de minutas não encontrados: %s", EMBEDDINGS_FILE)
                _EMBEDDINGS = {}
                return None

            try:
                payload = pickle.loads(EMBEDDINGS_FILE.read_bytes())
                if not isinstance(payload, dict):
                    logger.warning("Arquivo de embeddings inválido (esperado dict): %s", EMBEDDINGS_FILE)
                    _EMBEDDINGS = {}
                    return None

                normalizado: dict[str, list[float]] = {}
                for key, value in payload.items():
                    if not isinstance(key, str):
                        continue
                    vector_raw = value.tolist() if hasattr(value, "tolist") else value
                    if not isinstance(vector_raw, (list, tuple)):
                        continue
                    try:
                        normalizado[key] = [float(v) for v in vector_raw]
                    except (TypeError, ValueError):
                        continue
                _EMBEDDINGS = normalizado
                logger.info("🧠 %d embeddings de minutas carregados.", len(_EMBEDDINGS))
            except Exception as exc:
                logger.warning("Falha ao carregar embeddings (%s): %s", EMBEDDINGS_FILE, exc)
                _EMBEDDINGS = {}

    return _EMBEDDINGS or None


def _carregar_modelo_embeddings() -> Any | None:
    """Carrega o modelo sentence-transformers sob demanda."""
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is not None:
        return _EMBEDDING_MODEL

    with _EMBEDDING_MODEL_LOCK:
        if _EMBEDDING_MODEL is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                logger.info(
                    "sentence-transformers não disponível. "
                    "Seleção semântica desativada (fallback linear ativo)."
                )
                return None

            try:
                _EMBEDDING_MODEL = SentenceTransformer(EMBEDDING_MODEL_NAME)
                logger.info("Modelo semântico carregado: %s", EMBEDDING_MODEL_NAME)
            except Exception as exc:
                logger.warning("Falha ao carregar modelo semântico (%s): %s", EMBEDDING_MODEL_NAME, exc)
                return None
    return _EMBEDDING_MODEL


def _normalizar_sumulas(sumulas: list[str]) -> set[str]:
    """Normaliza súmulas para comparação: '7/STJ' -> {'7', '7/STJ'}."""
    resultado = set()
    for s in sumulas:
        resultado.add(s.strip())
        resultado.add(s.split("/")[0].strip().lstrip("0"))  # '07' -> '7'
    return resultado


def _score(
    candidato: dict,
    tipo_recurso: str,
    sumulas_norm: set[str],
    materias: list[str],
    decisao_estimada: str,
) -> float:
    """
    Calcula score linear de similaridade entre um candidato e o caso atual.

    Critérios (pesos):
      - Mesmo tipo de recurso : 10 (eliminatório-ish)
      - Mesma decisão estimada:  5
      - Súmulas em comum      :  3 por súmula
      - Matérias em comum     :  1 por matéria
    """
    score = 0.0

    if candidato.get("tipo_recurso") == tipo_recurso:
        score += 10
    elif tipo_recurso and candidato.get("tipo_recurso") == "desconhecido":
        score += 2

    if decisao_estimada and candidato.get("decisao") == decisao_estimada:
        score += 5
    if candidato.get("decisao") == "diligencia":
        score -= 3

    cand_sumulas = _normalizar_sumulas(candidato.get("sumulas", []))
    comuns_sumulas = sumulas_norm & cand_sumulas
    score += len(comuns_sumulas) * 3

    cand_materias = set(candidato.get("materias", []))
    comuns_materias = set(materias) & cand_materias
    score += len(comuns_materias) * 1

    return score


def _truncar_texto(texto: str, max_chars: int) -> str:
    """Trunca texto mantendo a estrutura (corta no último parágrafo completo)."""
    if len(texto) <= max_chars:
        return texto
    truncado = texto[:max_chars]
    ultimo_para = truncado.rfind("\n\n")
    if ultimo_para > max_chars * 0.7:
        truncado = truncado[:ultimo_para]
    return truncado + "\n\n[...trecho truncado para economizar tokens...]"


def _compor_secoes(secao_i: str, secao_ii: str, secao_iii: str) -> str:
    """Compõe seções em ordem preservando separação por parágrafos."""
    partes = [secao_i.strip(), secao_ii.strip(), secao_iii.strip()]
    return "\n\n".join(parte for parte in partes if parte)


def _extrair_secoes_i_ii_iii(texto: str) -> tuple[str, str, str] | None:
    """Extrai o bloco das seções I, II e III quando presentes no texto."""
    posicoes: dict[str, int] = {}
    for match in SECTION_HEADER_PATTERN.finditer(texto):
        label = match.group("label")
        if label not in posicoes:
            posicoes[label] = match.start()

    inicio_i = posicoes.get("I")
    inicio_ii = posicoes.get("II")
    inicio_iii = posicoes.get("III")
    if inicio_i is None or inicio_ii is None or inicio_iii is None:
        return None
    if not (inicio_i < inicio_ii < inicio_iii):
        return None

    secao_i = texto[inicio_i:inicio_ii].strip()
    secao_ii = texto[inicio_ii:inicio_iii].strip()
    secao_iii = texto[inicio_iii:].strip()
    if not secao_i or not secao_ii or not secao_iii:
        return None
    return secao_i, secao_ii, secao_iii


def _truncar_por_secoes(texto: str, max_chars: int) -> str:
    """
    Trunca minuta priorizando preservação da Seção III.

    Estratégia:
      1) Detectar seções I/II/III por regex.
      2) Reduzir seção II proporcionalmente ao espaço disponível.
      3) Preservar seção III completa sempre que possível.
      4) Fallback para truncamento tradicional quando não houver seções.
    """
    if len(texto) <= max_chars:
        return texto

    secoes = _extrair_secoes_i_ii_iii(texto)
    if secoes is None:
        return _truncar_texto(texto, max_chars)

    secao_i, secao_ii, secao_iii = secoes
    texto_completo = _compor_secoes(secao_i, secao_ii, secao_iii)
    if len(texto_completo) <= max_chars:
        return texto_completo

    if len(secao_iii) >= max_chars:
        logger.info(
            "Seção III excede limite de truncamento (%d chars). Aplicando fallback na própria seção.",
            max_chars,
        )
        return _truncar_texto(secao_iii, max_chars)

    base_sem_secao_ii = _compor_secoes(secao_i, "", secao_iii)
    if len(base_sem_secao_ii) > max_chars:
        # Se ainda exceder, remove II totalmente e reduz I para preservar III integral.
        espaco_para_i = max_chars - len(secao_iii) - 2
        if espaco_para_i <= 0:
            return _truncar_texto(secao_iii, max_chars)
        secao_i_reduzida = _truncar_texto(secao_i, espaco_para_i)
        return _compor_secoes(secao_i_reduzida, "", secao_iii)

    espaco_disponivel_secao_ii = max_chars - len(base_sem_secao_ii)
    if espaco_disponivel_secao_ii < 120:
        return base_sem_secao_ii
    if len(secao_ii) <= espaco_disponivel_secao_ii:
        return _compor_secoes(secao_i, secao_ii, secao_iii)

    proporcao = espaco_disponivel_secao_ii / len(secao_ii)
    alvo_secao_ii = max(120, int(len(secao_ii) * proporcao))
    alvo_secao_ii = min(alvo_secao_ii, espaco_disponivel_secao_ii)

    secao_ii_reduzida = _truncar_texto(secao_ii, alvo_secao_ii)
    resultado = _compor_secoes(secao_i, secao_ii_reduzida, secao_iii)

    while len(resultado) > max_chars and alvo_secao_ii > 120:
        alvo_secao_ii = max(120, alvo_secao_ii - max(32, len(resultado) - max_chars))
        secao_ii_reduzida = _truncar_texto(secao_ii, alvo_secao_ii)
        resultado = _compor_secoes(secao_i, secao_ii_reduzida, secao_iii)

    if len(resultado) > max_chars:
        return base_sem_secao_ii
    return resultado


def _montar_consulta_semantica(
    *,
    tipo_recurso: str,
    sumulas: list[str],
    materias: list[str],
    decisao_estimada: str,
) -> str:
    """Monta texto de consulta semântica com metadados do caso."""
    return (
        f"tipo_recurso: {tipo_recurso or 'desconhecido'}\n"
        f"decisao_estimada: {decisao_estimada or 'desconhecida'}\n"
        f"sumulas: {', '.join(sumulas) if sumulas else 'nenhuma'}\n"
        f"materias: {', '.join(materias) if materias else 'nenhuma'}"
    )


def _obter_query_embedding(
    *,
    tipo_recurso: str,
    sumulas: list[str],
    materias: list[str],
    decisao_estimada: str,
) -> list[float] | None:
    """Gera embedding semântico para o caso atual."""
    model = _carregar_modelo_embeddings()
    if model is None:
        return None

    consulta = _montar_consulta_semantica(
        tipo_recurso=tipo_recurso,
        sumulas=sumulas,
        materias=materias,
        decisao_estimada=decisao_estimada,
    )
    try:
        vector = model.encode(consulta)
        raw = vector.tolist() if hasattr(vector, "tolist") else vector
        return [float(v) for v in raw]
    except Exception as exc:
        logger.warning("Falha ao gerar embedding de consulta semântica: %s", exc)
        return None


def _cosine_similarity(vector_a: list[float], vector_b: list[float]) -> float:
    """Calcula similaridade de cosseno entre dois vetores."""
    if not vector_a or not vector_b:
        return 0.0

    limit = min(len(vector_a), len(vector_b))
    if limit == 0:
        return 0.0

    a = vector_a[:limit]
    b = vector_b[:limit]
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def selecionar_minuta_referencia(
    tipo_recurso: str = "",
    sumulas: list[str] | None = None,
    materias: list[str] | None = None,
    decisao_estimada: str = "",
    score_minimo: float = 5.0,
) -> str | None:
    """
    Seleciona a minuta de referência mais similar ao caso atual.

    Estratégia:
      1) Score linear histórico (metadados).
      2) Se embeddings disponíveis: score composto
         = 0.7 * cosine_similarity + 0.3 * score_linear_normalizado.
      3) Fallback linear quando embeddings/modelo indisponíveis.
    """
    indice = _carregar_indice()
    if not indice:
        return None

    sumulas_norm = _normalizar_sumulas(sumulas or [])
    materias_list = materias or []

    candidatos = [
        (entry, _score(entry, tipo_recurso, sumulas_norm, materias_list, decisao_estimada))
        for entry in indice
    ]
    candidatos.sort(key=lambda x: x[1], reverse=True)

    melhor_entry, melhor_score = candidatos[0]
    melhor_cosine = 0.0
    modo_selecao = "linear"

    embeddings = _carregar_embeddings()
    query_embedding = None
    if embeddings:
        query_embedding = _obter_query_embedding(
            tipo_recurso=tipo_recurso,
            sumulas=sumulas or [],
            materias=materias_list,
            decisao_estimada=decisao_estimada,
        )

    if embeddings and query_embedding:
        max_linear_score = max((max(score, 0.0) for _, score in candidatos), default=0.0)
        melhor_composto = -1.0
        melhor_semantico: tuple[dict, float, float, float] | None = None

        for entry, linear_score in candidatos:
            emb = embeddings.get(entry.get("id", ""))
            if not emb:
                continue

            cosine = _cosine_similarity(query_embedding, emb)
            cosine_norm = max(0.0, min(1.0, (cosine + 1.0) / 2.0))
            linear_norm = (
                max(0.0, linear_score) / max_linear_score
                if max_linear_score > 0.0
                else 0.0
            )
            score_composto = (0.7 * cosine_norm) + (0.3 * linear_norm)
            if score_composto > melhor_composto:
                melhor_composto = score_composto
                melhor_semantico = (entry, linear_score, cosine_norm, score_composto)

        if melhor_semantico is not None:
            entry_sem, linear_sem, cosine_sem, _comp_sem = melhor_semantico
            if linear_sem >= score_minimo or cosine_sem >= 0.70:
                melhor_entry = entry_sem
                melhor_score = linear_sem
                melhor_cosine = cosine_sem
                modo_selecao = "semantico_composto"
            else:
                logger.info(
                    "Seleção semântica não atingiu limiar (linear=%.2f, cosine=%.2f). "
                    "Prosseguindo com fallback linear.",
                    linear_sem,
                    cosine_sem,
                )

    if melhor_score < score_minimo:
        logger.info(
            "Nenhuma minuta com score suficiente (melhor=%.1f, mínimo=%.1f). "
            "Prosseguindo sem referência.",
            melhor_score,
            score_minimo,
        )
        return None

    txt_path = TEXTOS_DIR / (melhor_entry["id"] + ".txt")
    if not txt_path.exists():
        logger.warning("Texto da minuta não encontrado: %s", txt_path)
        return None

    texto = txt_path.read_text(encoding="utf-8").strip()
    texto_truncado = _truncar_por_secoes(texto, MAX_CHARS_REFERENCIA)

    logger.info(
        "📌 Minuta de referência selecionada: id=%s score_linear=%.1f "
        "score_cosine=%.3f modo=%s tipo=%s decisao=%s",
        melhor_entry["id"],
        melhor_score,
        melhor_cosine,
        modo_selecao,
        melhor_entry.get("tipo_recurso"),
        melhor_entry.get("decisao"),
    )

    return texto_truncado


def recarregar_indice() -> None:
    """Força recarregamento do índice (útil após importar novas minutas)."""
    global _INDEX
    with _INDEX_LOCK:
        _INDEX = None
    _carregar_indice()


def recarregar_embeddings() -> None:
    """Força recarregamento dos embeddings (útil após reindexação semântica)."""
    global _EMBEDDINGS
    with _EMBEDDINGS_LOCK:
        _EMBEDDINGS = None
    _carregar_embeddings()
