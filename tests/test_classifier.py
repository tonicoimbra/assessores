"""Tests for document classifier (Sprint 2.2)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.classifier import (
    CLASSIFICATION_PROMPT,
    ClassificationResult,
    DocumentClassificationError,
    _match_patterns_with_evidence,
    _classificar_por_heuristica,
    _classificar_por_verificador_barato,
    agrupar_documentos,
    classificar_documento,
    classificar_documentos,
)
from src.models import DocumentoEntrada, TipoDocumento


_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_cls006_fixture() -> dict[str, str]:
    with (_FIXTURES_DIR / "classifier_recursos_especies.json").open(
        "r",
        encoding="utf-8",
    ) as fh:
        payload = json.load(fh)
    assert isinstance(payload, dict)
    return {str(k): str(v) for k, v in payload.items()}


def _load_cls008_reference_docs() -> list[dict[str, str]]:
    with (_FIXTURES_DIR / "classifier_reference_docs_10.json").open(
        "r",
        encoding="utf-8",
    ) as fh:
        payload = json.load(fh)
    assert isinstance(payload, list)
    return [
        {
            "id": str(item["id"]),
            "texto": str(item["texto"]),
            "esperado": str(item["esperado"]),
        }
        for item in payload
    ]


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

    @pytest.mark.parametrize(
        ("fixture_key", "expected_marker"),
        [
            ("agravo_em_recurso_especial", "Agravo em Recurso Especial"),
            ("agravo_regimental", "Agravo Regimental"),
            ("agravo_interno", "Agravo Interno"),
            ("aresp", "AREsp"),
            ("embargos_declaracao", "Embargos de Declaração"),
            ("recurso_de_revista", "recurso de revista"),
        ],
    )
    def test_detects_new_recurso_species_patterns(
        self,
        fixture_key: str,
        expected_marker: str,
    ) -> None:
        exemplos = _load_cls006_fixture()
        texto = exemplos[fixture_key]
        r = _classificar_por_heuristica(texto)
        assert r.tipo == TipoDocumento.RECURSO
        assert r.confianca >= 0.7
        assert any(expected_marker.lower() in e.lower() for e in (r.evidence_snippets or []))

    @pytest.mark.parametrize(
        "fixture_key",
        [
            "agravo_em_recurso_especial",
            "agravo_regimental",
            "agravo_interno",
            "aresp",
        ],
    )
    def test_cheap_verifier_covers_new_agravo_and_aresp_patterns(
        self,
        fixture_key: str,
    ) -> None:
        exemplos = _load_cls006_fixture()
        tipo, confianca, _reason = _classificar_por_verificador_barato(exemplos[fixture_key])
        assert tipo == TipoDocumento.RECURSO
        assert confianca > 0.0


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

    def test_long_cover_detects_pattern_in_middle_window(self) -> None:
        texto = ("A" * 6200) + " Recurso Especial razões recursais art. 105, III " + ("B" * 6200)
        r = _classificar_por_heuristica(texto)
        assert r.tipo == TipoDocumento.RECURSO
        assert r.confianca >= 0.7

    def test_long_cover_detects_pattern_in_last_window(self) -> None:
        texto = ("A" * 10000) + " Recurso Extraordinário razões recursais art. 102, III "
        r = _classificar_por_heuristica(texto)
        assert r.tipo == TipoDocumento.RECURSO
        assert r.confianca >= 0.7

    def test_repeated_single_pattern_across_windows_does_not_bias_score_sum(self) -> None:
        chunk = "PROJUDI - Recurso " + ("x" * 5200)
        texto = chunk + chunk + chunk
        r = _classificar_por_heuristica(texto)
        assert r.tipo == TipoDocumento.DESCONHECIDO

    def test_pattern_matches_are_deduplicated_across_windows(self) -> None:
        chunk = "PROJUDI - Recurso " + ("x" * 5200)
        texto = chunk + chunk + " Recurso Especial "
        patterns = [
            r"PROJUDI\s*[-–—]\s*Recurso",
            r"Recurso\s+Especial",
        ]
        matched, snippets = _match_patterns_with_evidence(texto, patterns)
        assert matched.count(r"PROJUDI\s*[-–—]\s*Recurso") == 1
        assert matched.count(r"Recurso\s+Especial") == 1
        assert snippets.count("PROJUDI - Recurso") == 1


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


class TestClassifierPromptFewShot:
    """Regression tests for CLS-008 prompt enhancement."""

    def test_classification_prompt_contains_few_shot_examples(self) -> None:
        required_markers = [
            "EXEMPLO RECURSO 1",
            "EXEMPLO RECURSO 2",
            "EXEMPLO ACORDAO 1",
            "EXEMPLO ACORDAO 2",
            "EXEMPLO LIMITROFE EMBARGOS",
            "EXEMPLO LIMITROFE AGRAVO REGIMENTAL",
        ]
        for marker in required_markers:
            assert marker in CLASSIFICATION_PROMPT

    def test_regression_classifies_10_reference_docs_with_at_least_90_percent_accuracy(
        self,
        monkeypatch,
    ) -> None:
        docs = _load_cls008_reference_docs()

        monkeypatch.setattr(
            "src.classifier._classificar_por_heuristica",
            lambda _texto: ClassificationResult(
                tipo=TipoDocumento.DESCONHECIDO,
                confianca=0.15,
                metodo="heuristica",
                heuristic_score_recurso=0.0,
                heuristic_score_acordao=0.0,
            ),
        )
        monkeypatch.setattr(
            "src.model_router.get_model_for_task",
            lambda _task: "gpt-4.1-mini",
        )

        def _fake_chamar_llm_json(
            *,
            system_prompt: str,
            user_message: str,
            temperature: float,
            max_tokens: int,
            model: str,
        ) -> dict[str, object]:
            assert "EXEMPLO LIMITROFE EMBARGOS" in system_prompt
            assert "EXEMPLO LIMITROFE AGRAVO REGIMENTAL" in system_prompt
            assert model == "gpt-4.1-mini"
            assert temperature == 0.0
            assert max_tokens == 100

            text = user_message.lower()
            recurso_terms = [
                "recurso especial",
                "recurso extraordinário",
                "agravo regimental",
                "agravo interno",
                "embargos de declaração",
                "are sp",
                "aresp",
                "petição de recurso",
                "razões recursais",
            ]
            acordao_terms = [
                "acórdão",
                "ementa",
                "acordam",
                "vistos, relatados e discutidos",
                "câmara cível",
                "relator",
                "tribunal de justiça",
            ]
            if any(term in text for term in recurso_terms):
                return {"tipo": "RECURSO", "confianca": 0.96}
            if any(term in text for term in acordao_terms):
                return {"tipo": "ACORDAO", "confianca": 0.96}
            return {"tipo": "ACORDAO", "confianca": 0.51}

        monkeypatch.setattr("src.llm_client.chamar_llm_json", _fake_chamar_llm_json)

        acertos = 0
        for item in docs:
            resultado = classificar_documento(item["texto"])
            if resultado.tipo.value == item["esperado"]:
                acertos += 1

        acuracia = acertos / max(len(docs), 1)
        assert len(docs) == 10
        assert acuracia >= 0.9


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

    @patch("src.classifier._classificar_por_llm")
    def test_manual_review_mode_marks_ambiguous_documents(self, mock_llm) -> None:
        mock_llm.return_value = ClassificationResult(
            tipo=TipoDocumento.DESCONHECIDO,
            confianca=0.2,
            metodo="llm",
        )
        docs = [
            DocumentoEntrada(
                filepath="recurso.pdf",
                texto_extraido="PROJUDI - Recurso: Recurso Especial razões recursais art. 105, III",
            ),
            DocumentoEntrada(
                filepath="ambiguo.pdf",
                texto_extraido="Texto processual genérico sem padrões determinísticos.",
            ),
        ]

        result = classificar_documentos(
            docs,
            require_exactly_one_recurso=False,
            min_acordaos=0,
            manual_review_mode=True,
        )

        recurso_audit = result[0].classification_audit
        ambiguo_audit = result[1].classification_audit
        assert recurso_audit is not None
        assert ambiguo_audit is not None
        assert recurso_audit.manual_review_recommended is False
        assert ambiguo_audit.manual_review_recommended is True
        assert any("tipo_desconhecido" in m for m in ambiguo_audit.manual_review_reasons)


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
