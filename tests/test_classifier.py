"""Tests for document classifier (Sprint 2.2)."""

from unittest.mock import MagicMock, patch

import pytest

from src.classifier import (
    ClassificationResult,
    _classificar_por_heuristica,
    agrupar_documentos,
    classificar_documento,
    classificar_documentos,
)
from src.models import DocumentoEntrada, TipoDocumento


# --- 2.4.3: Heuristic classification — recurso ---


class TestHeuristicaRecurso:
    """Test heuristic classification of recurso documents."""

    def test_detects_recurso_especial(self) -> None:
        texto = "PROJUDI - Recurso: Recurso Especial interposto pelo réu"
        r = _classificar_por_heuristica(texto)
        assert r.tipo == TipoDocumento.RECURSO
        assert r.confianca > 0.5

    def test_detects_razoes_recursais(self) -> None:
        texto = "Seguem as razões recursais conforme art. 105, III, alínea a"
        r = _classificar_por_heuristica(texto)
        assert r.tipo == TipoDocumento.RECURSO

    def test_detects_recurso_extraordinario(self) -> None:
        texto = "Recurso Extraordinário fundado no art. 102, III da CF"
        r = _classificar_por_heuristica(texto)
        assert r.tipo == TipoDocumento.RECURSO

    def test_high_confidence_with_multiple_patterns(self) -> None:
        texto = (
            "PROJUDI - Recurso: Recurso Especial. "
            "razões recursais art. 105, III"
        )
        r = _classificar_por_heuristica(texto)
        assert r.tipo == TipoDocumento.RECURSO
        assert r.confianca >= 0.7


# --- 2.4.4: Heuristic classification — acórdão ---


class TestHeuristicaAcordao:
    """Test heuristic classification of acórdão documents."""

    def test_detects_acordao_keyword(self) -> None:
        texto = "ACÓRDÃO proferido pela 10ª Câmara Cível"
        r = _classificar_por_heuristica(texto)
        assert r.tipo == TipoDocumento.ACORDAO

    def test_detects_ementa_acordam(self) -> None:
        texto = "EMENTA: Apelação cível. ACORDAM os desembargadores."
        r = _classificar_por_heuristica(texto)
        assert r.tipo == TipoDocumento.ACORDAO

    def test_detects_vistos_relatados(self) -> None:
        texto = "Vistos, relatados e discutidos estes autos. Relatora: Des. Maria."
        r = _classificar_por_heuristica(texto)
        assert r.tipo == TipoDocumento.ACORDAO

    def test_high_confidence_with_multiple_patterns(self) -> None:
        texto = (
            "ACÓRDÃO\n"
            "Vistos, relatados e discutidos\n"
            "EMENTA: Direito civil\n"
            "Câmara Cível\n"
            "ACORDAM"
        )
        r = _classificar_por_heuristica(texto)
        assert r.tipo == TipoDocumento.ACORDAO
        assert r.confianca >= 0.7


class TestHeuristicaDesconhecido:
    """Test heuristic with ambiguous or generic text."""

    def test_returns_desconhecido_for_generic_text(self) -> None:
        texto = "Este é um texto qualquer sem termos jurídicos relevantes."
        r = _classificar_por_heuristica(texto)
        assert r.tipo == TipoDocumento.DESCONHECIDO

    def test_returns_desconhecido_for_empty_text(self) -> None:
        r = _classificar_por_heuristica("")
        assert r.tipo == TipoDocumento.DESCONHECIDO
        assert r.confianca == 0.0


# --- 2.4.5: LLM fallback ---


class TestFallbackLLM:
    """Test that LLM fallback is triggered for ambiguous documents."""

    @patch("src.classifier._classificar_por_llm")
    def test_calls_llm_when_heuristic_inconclusive(self, mock_llm) -> None:
        mock_llm.return_value = ClassificationResult(
            tipo=TipoDocumento.RECURSO,
            confianca=0.85,
            metodo="llm",
        )
        resultado = classificar_documento("texto genérico sem padrões")

        mock_llm.assert_called_once()
        assert resultado.tipo == TipoDocumento.RECURSO
        assert resultado.metodo == "llm"

    def test_does_not_call_llm_when_heuristic_confident(self) -> None:
        with patch("src.classifier._classificar_por_llm") as mock_llm:
            resultado = classificar_documento(
                "PROJUDI - Recurso: Recurso Especial razões recursais art. 105, III"
            )
            mock_llm.assert_not_called()
            assert resultado.tipo == TipoDocumento.RECURSO
            assert resultado.metodo == "heuristica"


# --- Classification of multiple documents ---


class TestClassificarDocumentos:
    """Test batch classification and validation."""

    def test_classifies_multiple_documents(self) -> None:
        docs = [
            DocumentoEntrada(
                filepath="recurso.pdf",
                texto_extraido="Recurso Especial razões recursais art. 105, III",
            ),
            DocumentoEntrada(
                filepath="acordao.pdf",
                texto_extraido="ACÓRDÃO EMENTA Câmara Cível ACORDAM",
            ),
        ]
        result = classificar_documentos(docs)
        assert result[0].tipo == TipoDocumento.RECURSO
        assert result[1].tipo == TipoDocumento.ACORDAO

    def test_warns_when_no_recurso(self, caplog) -> None:
        docs = [
            DocumentoEntrada(
                filepath="acordao.pdf",
                texto_extraido="ACÓRDÃO EMENTA Câmara Cível ACORDAM",
            ),
        ]
        with caplog.at_level("WARNING"):
            classificar_documentos(docs)
        assert any("Nenhum RECURSO" in r.message for r in caplog.records)


class TestAgruparDocumentos:
    """Test document grouping by type."""

    def test_groups_by_type(self) -> None:
        docs = [
            DocumentoEntrada(filepath="a.pdf", tipo=TipoDocumento.RECURSO),
            DocumentoEntrada(filepath="b.pdf", tipo=TipoDocumento.ACORDAO),
            DocumentoEntrada(filepath="c.pdf", tipo=TipoDocumento.RECURSO),
        ]
        grupos = agrupar_documentos(docs)
        assert len(grupos[TipoDocumento.RECURSO]) == 2
        assert len(grupos[TipoDocumento.ACORDAO]) == 1
        assert len(grupos[TipoDocumento.DESCONHECIDO]) == 0
