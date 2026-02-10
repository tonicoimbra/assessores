"""Tests for Sprint 3: Etapa 1 parsing, context, and state management."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.etapa1 import (
    _detectar_alucinacao,
    _parse_dispositivos_violados,
    _parse_especie_recurso,
    _parse_flag,
    _parse_nome,
    _parse_numero_processo,
    _parse_resposta_llm,
    _validar_campos,
    estimar_tokens,
)
from src.models import (
    DocumentoEntrada,
    EstadoPipeline,
    MetadadosPipeline,
    ResultadoEtapa1,
    TipoDocumento,
)
from src.state_manager import limpar_checkpoints, restaurar_estado, salvar_estado


# --- 3.5.1: Parsing Etapa 1 output format ---


SAMPLE_RESPONSE = """
[RECURSO ESPECIAL CÍVEL] Nº 1234567-89.2024.8.16.0001

**I – RELATÓRIO**

Recorrente: **JOÃO DA SILVA**
Recorrido: **MARIA DOS SANTOS**
Câmara: 10ª Câmara Cível

Espécie: RECURSO ESPECIAL CÍVEL
Permissivo: art. 105, III, alínea a da CF

Dispositivos Violados:
- art. 5º da CF
- art. 927 do Código Civil
- art. 489 do CPC

Justiça Gratuita: Sim
Efeito Suspensivo: Não
"""


class TestParsingEtapa1:
    """Test 3.5.1: parsing the Stage 1 output format."""

    def test_full_parse(self) -> None:
        r = _parse_resposta_llm(SAMPLE_RESPONSE)
        assert "1234567" in r.numero_processo
        assert "JOÃO" in r.recorrente
        assert "MARIA" in r.recorrido
        assert len(r.dispositivos_violados) >= 2
        assert r.justica_gratuita is True
        assert r.efeito_suspensivo is False
        assert r.texto_formatado == SAMPLE_RESPONSE

    def test_parse_process_number_formats(self) -> None:
        assert _parse_numero_processo("Nº 123-45.2024.8.16.0001")
        assert _parse_numero_processo("Processo: 999/2024")
        assert _parse_numero_processo("Nº 1234567-89.2024.8.16.0001")

    def test_parse_especie(self) -> None:
        assert "RECURSO ESPECIAL" in _parse_especie_recurso("RECURSO ESPECIAL CÍVEL")
        assert "EXTRAORDINÁRIO" in _parse_especie_recurso("RECURSO EXTRAORDINÁRIO")

    def test_parse_dispositivos(self) -> None:
        texto = "Dispositivos Violados:\n- art. 5 da CF\n- art. 927 do CC\n"
        result = _parse_dispositivos_violados(texto)
        assert len(result) >= 2

    def test_parse_flags(self) -> None:
        assert _parse_flag("Justiça Gratuita: Sim", "Justiça [Gg]ratuita") is True
        assert _parse_flag("Justiça Gratuita: Não", "Justiça [Gg]ratuita") is False
        assert _parse_flag("Efeito Suspensivo: Não", "Efeito [Ss]uspensivo") is False


# --- 3.5.2: Missing field detection ---


class TestCamposAusentes:
    """Test 3.5.2: detection of missing fields."""

    def test_detects_missing_processo(self) -> None:
        r = ResultadoEtapa1(recorrente="TESTE", especie_recurso="RE")
        alertas = _validar_campos(r, "texto")
        assert any("numero_processo" in a for a in alertas)

    def test_detects_missing_recorrente(self) -> None:
        r = ResultadoEtapa1(numero_processo="123", especie_recurso="RE")
        alertas = _validar_campos(r, "texto")
        assert any("recorrente" in a for a in alertas)

    def test_no_alerts_when_all_present(self) -> None:
        r = ResultadoEtapa1(
            numero_processo="123",
            recorrente="TESTE",
            especie_recurso="RE",
        )
        alertas = _validar_campos(r, "texto")
        assert len(alertas) == 0

    def test_hallucination_detected(self) -> None:
        r = ResultadoEtapa1(numero_processo="9999999-99", recorrente="FAKE NAME")
        alertas = _detectar_alucinacao(r, "texto completamente diferente sem dados")
        assert len(alertas) >= 1


# --- 3.5.3: Token estimation with tiktoken ---


class TestEstimativaTokens:
    """Test 3.5.3: token estimation."""

    def test_estimates_positive_count(self) -> None:
        tokens = estimar_tokens("Hello world, this is a test.")
        assert tokens > 0

    def test_empty_string_returns_zero(self) -> None:
        assert estimar_tokens("") == 0

    def test_longer_text_more_tokens(self) -> None:
        short = estimar_tokens("Hello")
        long = estimar_tokens("Hello world, this is a much longer piece of text for testing.")
        assert long > short

    def test_portuguese_text(self) -> None:
        tokens = estimar_tokens(
            "Trata-se de recurso especial interposto contra acórdão do TJPR."
        )
        assert tokens > 5


# --- 3.5.4: State serialization/deserialization ---


class TestSerializacaoEstado:
    """Test 3.5.4: pipeline state checkpoint save/restore."""

    def test_save_and_restore(self, tmp_path: Path) -> None:
        estado = EstadoPipeline(
            documentos_entrada=[DocumentoEntrada(filepath="test.pdf")],
            resultado_etapa1=ResultadoEtapa1(
                numero_processo="123",
                recorrente="TESTE",
                dispositivos_violados=["art. 5"],
            ),
        )

        # Save
        filepath = tmp_path / "estado_test.json"
        filepath.write_text(estado.model_dump_json(indent=2))

        # Restore
        restored = EstadoPipeline.model_validate_json(filepath.read_text())
        assert restored.resultado_etapa1.numero_processo == "123"
        assert restored.resultado_etapa1.recorrente == "TESTE"
        assert len(restored.documentos_entrada) == 1

    def test_save_via_state_manager(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("src.state_manager.CHECKPOINT_DIR", tmp_path)

        estado = EstadoPipeline(
            resultado_etapa1=ResultadoEtapa1(numero_processo="456"),
        )
        path = salvar_estado(estado, "test_proc")
        assert path.exists()

        restored = restaurar_estado(filepath=path)
        assert restored is not None
        assert restored.resultado_etapa1.numero_processo == "456"

    def test_restore_nonexistent_returns_none(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("src.state_manager.CHECKPOINT_DIR", tmp_path)
        result = restaurar_estado(processo_id="nonexistent")
        assert result is None

    def test_cleanup_checkpoints(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr("src.state_manager.CHECKPOINT_DIR", tmp_path)

        estado = EstadoPipeline()
        salvar_estado(estado, "proc1")
        salvar_estado(estado, "proc2")

        removed = limpar_checkpoints()
        assert removed == 2


# --- 3.5.5: Integration test (slow) ---


@pytest.mark.slow
class TestEtapa1Integration:
    """Integration test for full Stage 1. Run with: pytest -m slow"""

    def test_full_etapa1(self) -> None:
        from src.config import OPENAI_API_KEY

        if not OPENAI_API_KEY:
            pytest.skip("OPENAI_API_KEY not set")

        from src.etapa1 import executar_etapa1

        texto_recurso = (
            "PROJUDI - Recurso Especial Cível\n"
            "Processo Nº 1234567-89.2024.8.16.0001\n"
            "Recorrente: JOÃO DA SILVA\n"
            "Recorrido: MARIA DOS SANTOS\n"
            "Razões recursais fundadas no art. 105, III, a da CF.\n"
            "Alega violação ao art. 927 do Código Civil.\n"
        )

        resultado = executar_etapa1(
            texto_recurso=texto_recurso,
            prompt_sistema="Analise o recurso e extraia dados estruturados.",
        )

        assert isinstance(resultado, ResultadoEtapa1)
        assert resultado.texto_formatado
