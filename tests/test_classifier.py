"""Tests for document classifier (Sprint 2.2)."""

from unittest.mock import MagicMock, patch

import pytest

from src.classifier import (
    ClassificationResult,
    DocumentClassificationError,
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
        assert r.matched_recurso_patterns
        assert r.evidence_snippets


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
        assert "llm" in resultado.metodo
        assert "score_composto" in resultado.metodo

    def test_does_not_call_llm_when_heuristic_confident(self) -> None:
        with patch("src.classifier._classificar_por_llm") as mock_llm:
            resultado = classificar_documento(
                "PROJUDI - Recurso: Recurso Especial razões recursais art. 105, III"
            )
            mock_llm.assert_not_called()
            assert resultado.tipo == TipoDocumento.RECURSO
            assert "heuristica" in resultado.metodo
            assert "score_composto" in resultado.metodo

    @patch("src.classifier._classificar_por_heuristica")
    def test_crosscheck_downgrades_conflicting_primary_classification(self, mock_heuristica) -> None:
        mock_heuristica.return_value = ClassificationResult(
            tipo=TipoDocumento.RECURSO,
            confianca=0.9,
            metodo="heuristica",
        )
        texto = (
            "ACÓRDÃO\nEMENTA\nACORDAM os desembargadores da Câmara Cível.\n"
            "Vistos, relatados e discutidos."
        )
        resultado = classificar_documento(texto)

        assert resultado.tipo == TipoDocumento.DESCONHECIDO
        assert resultado.confianca <= 0.49
        assert "crosscheck" in resultado.metodo
        assert resultado.verifier_ok is False
        assert resultado.verifier_tipo == TipoDocumento.ACORDAO

    @patch("src.classifier._classificar_por_heuristica")
    def test_composite_blocks_low_margin_decision(self, mock_heuristica) -> None:
        mock_heuristica.return_value = ClassificationResult(
            tipo=TipoDocumento.RECURSO,
            confianca=0.52,
            metodo="heuristica",
            heuristic_score_recurso=0.52,
            heuristic_score_acordao=0.48,
        )
        resultado = classificar_documento("texto curto sem outros sinais")

        assert resultado.tipo == TipoDocumento.DESCONHECIDO
        assert resultado.confianca <= 0.49
        assert resultado.consistency_flags is not None
        assert "low_composite_margin" in resultado.consistency_flags


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
        assert result[0].classification_audit is not None
        assert result[1].classification_audit is not None
        assert (
            "heuristica" in result[0].classification_audit.method
            or "llm" in result[0].classification_audit.method
        )
        assert (
            "heuristica" in result[1].classification_audit.method
            or "llm" in result[1].classification_audit.method
        )
        assert 0.0 <= result[0].classification_audit.composite_score_recurso <= 1.0
        assert 0.0 <= result[0].classification_audit.composite_score_acordao <= 1.0
        assert 0.0 <= result[0].classification_audit.decision_margin <= 1.0

    def test_persists_classification_evidence(self) -> None:
        docs = [
            DocumentoEntrada(
                filepath="recurso.pdf",
                texto_extraido="PROJUDI - Recurso: Recurso Especial razões recursais art. 105, III",
            ),
        ]
        result = classificar_documentos(docs)
        audit = result[0].classification_audit
        assert audit is not None
        assert "heuristica" in audit.method
        assert audit.heuristic_score_recurso >= 0.7
        assert len(audit.matched_recurso_patterns) > 0
        assert len(audit.evidence_snippets) > 0
        assert audit.verifier_ok is True
        assert audit.verifier_tipo in {"RECURSO", "DESCONHECIDO"}
        assert 0.0 <= audit.composite_score_recurso <= 1.0
        assert 0.0 <= audit.composite_score_acordao <= 1.0
        assert 0.0 <= audit.consistency_score <= 1.0
        assert "score_composto" in audit.method

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

    def test_strict_mode_raises_when_no_recurso(self) -> None:
        docs = [
            DocumentoEntrada(
                filepath="acordao.pdf",
                texto_extraido="ACÓRDÃO EMENTA Câmara Cível ACORDAM",
            ),
        ]
        with pytest.raises(DocumentClassificationError):
            classificar_documentos(docs, strict=True)

    def test_strict_mode_raises_when_multiple_recursos(self) -> None:
        docs = [
            DocumentoEntrada(
                filepath="recurso1.pdf",
                texto_extraido="Recurso Especial razões recursais art. 105, III",
            ),
            DocumentoEntrada(
                filepath="recurso2.pdf",
                texto_extraido="Recurso Extraordinário razões recursais art. 102, III",
            ),
            DocumentoEntrada(
                filepath="acordao.pdf",
                texto_extraido="ACÓRDÃO EMENTA Câmara Cível ACORDAM",
            ),
        ]
        with pytest.raises(DocumentClassificationError):
            classificar_documentos(docs, strict=True)


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
