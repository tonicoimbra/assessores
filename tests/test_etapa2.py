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
    _separar_blocos_tema,
    _validar_obices,
    _validar_temas,
    validar_prerequisito_etapa1,
)
from src.models import (
    EstadoPipeline,
    ResultadoEtapa1,
    ResultadoEtapa2,
    TemaEtapa2,
)
from src.state_manager import restaurar_estado, salvar_estado


SAMPLE_ETAPA2_RESPONSE = """
Tema 1: Responsabilidade Civil por Dano Moral
Matéria: Indenização por dano moral decorrente de inadimplemento contratual
Conclusão: O tribunal entendeu pela inexistência do dano, mantendo a sentença
Aplicação de Tema: Tema 952 do STJ — Sim
Óbices: Súmula 7 do STJ

Tema 2: Honorários Advocatícios
Matéria: Fixação e majoração dos honorários sucumbenciais
Conclusão: Mantidos honorários em 10% sobre o valor da causa
Aplicação de Tema: Não se aplica
Óbices: Súmula 7 do STJ, Súmula 83 do STJ

Tema 3: Valor da Causa
Matéria: Adequação do valor atribuído à causa
Conclusão: Valor mantido conforme fixado em primeira instância
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

    def test_stj_sumulas_complete(self) -> None:
        expected = {5, 7, 13, 83, 126, 211, 518}
        assert SUMULAS_STJ == expected

    def test_stf_sumulas_complete(self) -> None:
        expected = {279, 280, 281, 282, 283, 284, 356, 735}
        assert SUMULAS_STF == expected


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
