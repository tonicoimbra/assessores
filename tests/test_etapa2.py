"""Tests for Sprint 4: Etapa 2 parsing, obstacle validation, and state."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.etapa2 import (
    Etapa2Error,
    SUMULAS_STJ,
    SUMULAS_STF,
    SUMULAS_VALIDAS,
    _parse_resposta_etapa2,
    _resultado_etapa2_from_json,
    _separar_blocos_tema,
    _validar_evidencias_temas,
    _validar_obices,
    _validar_temas,
    executar_etapa2,
    validar_prerequisito_etapa1,
)
from src.models import (
    EstadoPipeline,
    ResultadoEtapa1,
    ResultadoEtapa2,
    TemaEtapa2,
)
from src.state_manager import restaurar_estado, salvar_estado
from src.sumula_taxonomy import (
    SUMULAS_STF as TAXONOMY_SUMULAS_STF,
    SUMULAS_STJ as TAXONOMY_SUMULAS_STJ,
    SUMULAS_TAXONOMY_VERSION,
    SUMULAS_VALIDAS as TAXONOMY_SUMULAS_VALIDAS,
)


SAMPLE_ETAPA2_RESPONSE = """
Tema 1: Responsabilidade Civil por Dano Moral
Matéria: Indenização por dano moral decorrente de inadimplemento contratual
Conclusão: O tribunal entendeu pela inexistência do dano, mantendo a sentença
Aplicação de Tema: Tema 952 do STJ — Sim
Óbices: Súmula 7 do STJ
Trecho: "No caso, não se verifica abalo moral indenizável, razão pela qual a sentença deve ser mantida."

Tema 2: Honorários Advocatícios
Matéria: Fixação e majoração dos honorários sucumbenciais
Conclusão: Mantidos honorários em 10% sobre o valor da causa
Aplicação de Tema: Não se aplica
Óbices: Súmula 7 do STJ, Súmula 83 do STJ
Trecho: "Os honorários foram fixados em 10% e não comportam revisão em recurso especial."

Tema 3: Valor da Causa
Matéria: Adequação do valor atribuído à causa
Conclusão: Valor mantido conforme fixado em primeira instância
Óbices: Súmula 7 do STJ
Trecho: "A revisão do valor da causa demanda revolvimento fático-probatório."
"""


# --- 4.5.1: Parsing Etapa 2 output ---


class TestParsingEtapa2:
    """Test parsing of Stage 2 output format."""

    def test_parses_multiple_themes(self) -> None:
        resultado = _parse_resposta_etapa2(SAMPLE_ETAPA2_RESPONSE)
        assert len(resultado.temas) >= 2
        assert resultado.texto_formatado == SAMPLE_ETAPA2_RESPONSE

    def test_extracts_materia(self) -> None:
        resultado = _parse_resposta_etapa2(SAMPLE_ETAPA2_RESPONSE)
        assert "dano moral" in resultado.temas[0].materia_controvertida.lower()

    def test_extracts_conclusao(self) -> None:
        resultado = _parse_resposta_etapa2(SAMPLE_ETAPA2_RESPONSE)
        assert len(resultado.temas[0].conclusao_fundamentos) > 10

    def test_extracts_obices(self) -> None:
        resultado = _parse_resposta_etapa2(SAMPLE_ETAPA2_RESPONSE)
        assert len(resultado.temas[0].obices_sumulas) >= 1


# --- 4.5.2: Súmula validation ---


class TestValidacaoSumulas:
    """Test obstacle validation against allowed list."""

    def test_valid_sumulas_pass(self) -> None:
        tema = TemaEtapa2(obices_sumulas=["Súmula 7", "Súmula 83"])
        alertas = _validar_obices([tema], "texto com Súmula 7 e Súmula 83")
        invalid = [a for a in alertas if "não está na lista" in a]
        assert len(invalid) == 0

    def test_invalid_sumula_detected(self) -> None:
        tema = TemaEtapa2(obices_sumulas=["Súmula 999"])
        alertas = _validar_obices([tema], "texto")
        assert any("999" in a and "lista permitida" in a for a in alertas)

    def test_obice_lastro_accepts_normalized_variant(self) -> None:
        tema = TemaEtapa2(obices_sumulas=["Súmula 7/STJ"])
        alertas = _validar_obices([tema], "Incide a sumula n 7 do stj no caso concreto.")
        assert not any("sem lastro" in a for a in alertas)

    def test_stj_sumulas_complete(self) -> None:
        expected = {5, 7, 13, 83, 126, 211, 518}
        assert SUMULAS_STJ == expected
        assert TAXONOMY_SUMULAS_STJ == expected

    def test_stf_sumulas_complete(self) -> None:
        expected = {279, 280, 281, 282, 283, 284, 356, 735}
        assert SUMULAS_STF == expected
        assert TAXONOMY_SUMULAS_STF == expected

    def test_sumulas_taxonomy_is_versioned(self) -> None:
        assert SUMULAS_TAXONOMY_VERSION == "2026.02.13"
        assert TAXONOMY_SUMULAS_VALIDAS == SUMULAS_VALIDAS


# --- 4.5.3: Multiple theme extraction ---


class TestMultiplosTemas:
    """Test extraction of multiple themes."""

    def test_separates_three_themes(self) -> None:
        blocos = _separar_blocos_tema(SAMPLE_ETAPA2_RESPONSE)
        assert len(blocos) == 3

    def test_each_theme_has_materia(self) -> None:
        resultado = _parse_resposta_etapa2(SAMPLE_ETAPA2_RESPONSE)
        for i, tema in enumerate(resultado.temas):
            assert tema.materia_controvertida, f"Tema {i+1} sem matéria"


# --- 4.5.4: Missing fields handling ---


class TestCamposAusentes:
    """Test handling of themes with missing fields."""

    def test_detects_missing_materia(self) -> None:
        tema = TemaEtapa2(conclusao_fundamentos="algo")
        alertas = _validar_temas([tema])
        assert any("matéria" in a for a in alertas)

    def test_detects_missing_conclusao(self) -> None:
        tema = TemaEtapa2(materia_controvertida="algo")
        alertas = _validar_temas([tema])
        assert any("conclusão" in a for a in alertas)

    def test_detects_missing_obices(self) -> None:
        tema = TemaEtapa2(
            materia_controvertida="algo",
            conclusao_fundamentos="conclusao",
            trecho_transcricao="trecho",
        )
        alertas = _validar_temas([tema])
        assert any("óbices" in a for a in alertas)

    def test_detects_missing_trecho_literal(self) -> None:
        tema = TemaEtapa2(
            materia_controvertida="algo",
            conclusao_fundamentos="conclusao",
            obices_sumulas=["Súmula 7"],
        )
        alertas = _validar_temas([tema])
        assert any("trecho literal" in a for a in alertas)

    def test_detects_no_themes(self) -> None:
        alertas = _validar_temas([])
        assert any("Nenhum tema" in a for a in alertas)

    def test_prerequisite_fails_without_etapa1(self) -> None:
        with pytest.raises(Etapa2Error, match="Etapa 1 não executada"):
            validar_prerequisito_etapa1(None)

    def test_prerequisite_fails_with_empty_etapa1(self) -> None:
        with pytest.raises(Etapa2Error, match="incompleta"):
            validar_prerequisito_etapa1(ResultadoEtapa1())

    def test_prerequisite_passes_with_valid_etapa1(self) -> None:
        r1 = ResultadoEtapa1(numero_processo="123", recorrente="TESTE")
        validar_prerequisito_etapa1(r1)  # Should not raise


# --- 4.5.5: Integration (slow) ---


@pytest.mark.slow
class TestEtapa2Integration:
    """Integration test for full Stage 2. Run with: pytest -m slow"""

    def test_full_etapa2(self) -> None:
        from src.config import OPENAI_API_KEY

        if not OPENAI_API_KEY:
            pytest.skip("OPENAI_API_KEY not set")

        from src.etapa2 import executar_etapa2

        resultado = executar_etapa2(
            texto_acordao="ACÓRDÃO. Vistos, relatados e discutidos. EMENTA: Dano moral.",
            resultado_etapa1=ResultadoEtapa1(
                numero_processo="123",
                recorrente="TESTE",
                dispositivos_violados=["art. 927 do CC"],
            ),
            prompt_sistema="Analise o acórdão e identifique temas.",
        )
        assert isinstance(resultado, ResultadoEtapa2)


class TestEtapa2StructuredJson:
    """Test structured JSON conversion and fallback behavior."""

    def test_resultado_from_json_payload(self) -> None:
        payload = {
            "temas": [
                {
                    "materia_controvertida": "Dano moral",
                    "conclusao_fundamentos": "Indeferido por ausência de prova.",
                    "base_vinculante": "Tema 952/STJ",
                    "obices_sumulas": ["Súmula 7"],
                    "trecho_transcricao": "Trecho literal do acórdão.",
                    "evidencias_campos": {
                        "materia_controvertida": {
                            "citacao_literal": "Dano moral no inadimplemento",
                            "pagina": 1,
                            "ancora": "Tema 1",
                            "offset_inicio": 12,
                        }
                    },
                }
            ]
        }
        resultado = _resultado_etapa2_from_json(payload)
        assert len(resultado.temas) == 1
        assert resultado.temas[0].materia_controvertida == "Dano moral"
        assert resultado.temas[0].obices_sumulas == ["Súmula 7"]
        assert "materia_controvertida" in resultado.temas[0].evidencias_campos
        assert resultado.temas[0].evidencias_campos["materia_controvertida"].pagina == 1

    def test_executar_etapa2_structured_success(self, monkeypatch) -> None:
        payload = {
            "temas": [
                {
                    "materia_controvertida": "Dano moral",
                    "conclusao_fundamentos": "Improcedência mantida por ausência de abalo.",
                    "base_vinculante": "",
                    "obices_sumulas": ["Súmula 7"],
                    "trecho_transcricao": "Não se verifica dano moral indenizável.",
                }
            ]
        }
        monkeypatch.setattr("src.etapa2.chamar_llm_json", lambda **kwargs: payload)

        def _should_not_call_llm(**kwargs):
            raise AssertionError("fallback legacy should not be called")

        monkeypatch.setattr("src.etapa2.chamar_llm", _should_not_call_llm)

        r1 = ResultadoEtapa1(numero_processo="123", recorrente="TESTE")
        resultado = executar_etapa2(
            texto_acordao=(
                "ACÓRDÃO sobre dano moral. Não se verifica dano moral indenizável. "
                "Improcedência mantida por ausência de abalo. Incide a Súmula 7."
            ),
            resultado_etapa1=r1,
            prompt_sistema="prompt",
            modelo_override="gpt-4o",
        )
        assert len(resultado.temas) == 1
        assert resultado.temas[0].materia_controvertida == "Dano moral"
        evidencias = resultado.temas[0].evidencias_campos
        for campo in ("materia_controvertida", "conclusao_fundamentos", "obices_sumulas", "trecho_transcricao"):
            assert campo in evidencias
            assert evidencias[campo].pagina is not None

    def test_validar_evidencias_temas_detects_missing_evidence(self) -> None:
        tema = TemaEtapa2(
            materia_controvertida="Dano moral",
            conclusao_fundamentos="Improcedência",
            obices_sumulas=["Súmula 7"],
            trecho_transcricao="não se verifica dano moral",
        )
        alertas = _validar_evidencias_temas([tema], "texto do acórdão com súmula 7")
        assert any("sem evidência" in a for a in alertas)

    def test_executar_etapa2_structured_failure_fallback(self, monkeypatch) -> None:
        calls = {"json": 0}

        def _fail_json(**kwargs):
            calls["json"] += 1
            raise RuntimeError("json inválido")

        monkeypatch.setattr("src.etapa2.chamar_llm_json", _fail_json)

        class _FakeResponse:
            content = SAMPLE_ETAPA2_RESPONSE
            tokens = type("T", (), {"total_tokens": 200, "prompt_tokens": 120, "completion_tokens": 80})()

        monkeypatch.setattr("src.etapa2.chamar_llm", lambda **kwargs: _FakeResponse())

        r1 = ResultadoEtapa1(numero_processo="123", recorrente="TESTE")
        resultado = executar_etapa2(
            texto_acordao="ACÓRDÃO com múltiplos temas e súmulas",
            resultado_etapa1=r1,
            prompt_sistema="prompt",
            modelo_override="gpt-4o",
        )
        assert calls["json"] == 2
        assert len(resultado.temas) >= 2
