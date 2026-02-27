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
from pathlib import Path

logger = logging.getLogger("assessor_ai")

BASE_DIR    = Path(__file__).resolve().parent.parent
INDEX_FILE  = BASE_DIR / "minutas_referencia" / "index.json"
TEXTOS_DIR  = BASE_DIR / "minutas_referencia" / "textos"

# Cache em memória (carregado uma vez)
_INDEX: list[dict] | None = None
MAX_CHARS_REFERENCIA = 6_000  # ~1500 tokens — suficiente sem estourar contexto


def _carregar_indice() -> list[dict]:
    """Carrega o índice em memória (lazy, singleton)."""
    global _INDEX
    if _INDEX is None:
        if not INDEX_FILE.exists():
            logger.warning("Índice de minutas não encontrado: %s", INDEX_FILE)
            _INDEX = []
        else:
            _INDEX = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
            logger.info("📚 %d minutas de referência carregadas.", len(_INDEX))
    return _INDEX


def _normalizar_sumulas(sumulas: list[str]) -> set[str]:
    """Normaliza súmulas para comparação: '7/STJ' → {'7', '7/STJ'}."""
    resultado = set()
    for s in sumulas:
        resultado.add(s.strip())
        resultado.add(s.split("/")[0].strip().lstrip("0"))  # '07' → '7'
    return resultado


def _score(
    candidato: dict,
    tipo_recurso: str,
    sumulas_norm: set[str],
    materias: list[str],
    decisao_estimada: str,
) -> float:
    """
    Calcula score de similaridade entre um candidato e o caso atual.

    Critérios (pesos):
      - Mesmo tipo de recurso : 10 (eliminatório-ish)
      - Mesma decisão estimada:  5
      - Súmulas em comum      :  3 por súmula
      - Matérias em comum     :  1 por matéria
    """
    score = 0.0

    # Tipo de recurso (eliminatório — peso alto)
    if candidato.get("tipo_recurso") == tipo_recurso:
        score += 10
    elif tipo_recurso and candidato.get("tipo_recurso") == "desconhecido":
        score += 2  # aceitar desconhecidos com bonus pequeno

    # Decisão estimada
    if decisao_estimada and candidato.get("decisao") == decisao_estimada:
        score += 5
    # Diligências não servem como referência de decisão final
    if candidato.get("decisao") == "diligencia":
        score -= 3

    # Súmulas em comum
    cand_sumulas = _normalizar_sumulas(candidato.get("sumulas", []))
    comuns_sumulas = sumulas_norm & cand_sumulas
    score += len(comuns_sumulas) * 3

    # Matérias em comum
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


def selecionar_minuta_referencia(
    tipo_recurso: str = "",
    sumulas: list[str] | None = None,
    materias: list[str] | None = None,
    decisao_estimada: str = "",
    score_minimo: float = 5.0,
) -> str | None:
    """
    Seleciona a minuta de referência mais similar ao caso atual.

    Args:
        tipo_recurso:     'recurso_especial', 'recurso_extraordinario', etc.
        sumulas:          Súmulas identificadas na Etapa 2.
        materias:         Matérias identificadas (lista de tags).
        decisao_estimada: 'inadmitido', 'admitido' ou ''.
        score_minimo:     Score mínimo para considerar pertinente (default 5.0).

    Returns:
        Texto da minuta de referência (str) ou None se nenhuma for suficientemente similar.
    """
    indice = _carregar_indice()
    if not indice:
        return None

    sumulas_norm = _normalizar_sumulas(sumulas or [])
    materias_list = materias or []

    # Calcular score para cada candidato
    candidatos = [
        (entry, _score(entry, tipo_recurso, sumulas_norm, materias_list, decisao_estimada))
        for entry in indice
    ]

    # Ordenar por score decrescente
    candidatos.sort(key=lambda x: x[1], reverse=True)

    melhor_entry, melhor_score = candidatos[0]

    if melhor_score < score_minimo:
        logger.info(
            "Nenhuma minuta com score suficiente (melhor=%.1f, mínimo=%.1f). "
            "Prosseguindo sem referência.",
            melhor_score, score_minimo,
        )
        return None

    # Carregar texto da minuta selecionada
    txt_path = TEXTOS_DIR / (melhor_entry["id"] + ".txt")
    if not txt_path.exists():
        logger.warning("Texto da minuta não encontrado: %s", txt_path)
        return None

    texto = txt_path.read_text(encoding="utf-8").strip()
    texto_truncado = _truncar_texto(texto, MAX_CHARS_REFERENCIA)

    logger.info(
        "📌 Minuta de referência selecionada: id=%s score=%.1f tipo=%s decisao=%s",
        melhor_entry["id"], melhor_score,
        melhor_entry.get("tipo_recurso"), melhor_entry.get("decisao"),
    )

    return texto_truncado


def recarregar_indice() -> None:
    """Força recarregamento do índice (útil após importar novas minutas)."""
    global _INDEX
    _INDEX = None
    _carregar_indice()
