"""Tests for Sprint 3: Etapa 1 parsing, context, and state management."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.etapa1 import (
    _converter_texto_livre_para_resultado_etapa1,
    _detectar_alucinacao,
    _extrair_json_de_texto_livre,
    _parse_dispositivos_violados,
    _parse_especie_recurso,
    _parse_flag,
    _parse_nome,
    _parse_numero_processo,
    _parse_resposta_llm,
    _resultado_etapa1_from_json,
    _validar_evidencias_campos_criticos,
    _verificador_independente_etapa1,
    _verificar_contexto,
    _validar_campos,
    executar_etapa1,
    estimar_tokens,
)
from src.models import (
    CampoEvidencia,
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


class TestEtapa1StructuredJson:
    """Test conversion from structured JSON payload to ResultadoEtapa1."""

    def test_structured_json_conversion(self) -> None:
        payload = {
            "numero_processo": "1234567-89.2024.8.16.0001",
            "recorrente": "JOÃO DA SILVA",
            "recorrido": "MARIA DOS SANTOS",
            "especie_recurso": "RECURSO ESPECIAL",
            "permissivo_constitucional": "art. 105, III",
            "camara_civel": "10ª Câmara Cível",
            "dispositivos_violados": ["art. 5º CF", "art. 927 CC"],
            "justica_gratuita": "Sim",
            "efeito_suspensivo": False,
            "evidencias_campos": {
                "numero_processo": {
                    "citacao_literal": "Processo nº 1234567-89.2024.8.16.0001",
                    "pagina": 1,
                    "ancora": "cabeçalho da petição",
                    "offset_inicio": 42,
                }
            },
        }
        resultado = _resultado_etapa1_from_json(payload)
        assert resultado.numero_processo.startswith("1234567")
        assert resultado.recorrente == "JOÃO DA SILVA"
        assert len(resultado.dispositivos_violados) == 2
        assert resultado.justica_gratuita is True
        assert resultado.efeito_suspensivo is False
        assert "numero_processo" in resultado.evidencias_campos
        assert resultado.evidencias_campos["numero_processo"].pagina == 1

    def test_structured_json_placeholder_is_treated_as_missing(self) -> None:
        payload = {
            "numero_processo": "[NÃO CONSTA NO DOCUMENTO]",
            "recorrente": " ",
            "especie_recurso": "N/A",
            "dispositivos_violados": ["[NÃO CONSTA NO DOCUMENTO]"],
        }
        resultado = _resultado_etapa1_from_json(payload)
        assert resultado.numero_processo == ""
        assert resultado.recorrente == ""
        assert resultado.especie_recurso == ""
        assert resultado.dispositivos_violados == []

    def test_extrair_json_de_texto_livre_inline(self) -> None:
        raw = (
            "Resposta:\n```json\n"
            '{"numero_processo":"123","recorrente":"JOAO","especie_recurso":"RECURSO ESPECIAL"}'
            "\n```"
        )
        payload = _extrair_json_de_texto_livre(raw)
        assert payload is not None
        assert payload["numero_processo"] == "123"

    def test_validar_evidencias_campos_criticos_warns_when_missing(self) -> None:
        resultado = ResultadoEtapa1(
            numero_processo="1234567-89.2024.8.16.0001",
            recorrente="JOÃO DA SILVA",
            especie_recurso="RECURSO ESPECIAL",
            evidencias_campos={},
        )
        alertas = _validar_evidencias_campos_criticos(resultado, "texto sem os dados")
        assert any("numero_processo" in a for a in alertas)
        assert any("recorrente" in a for a in alertas)
        assert any("especie_recurso" in a for a in alertas)

    def test_validar_evidencias_campos_criticos_ok(self) -> None:
        resultado = ResultadoEtapa1(
            numero_processo="1234567-89.2024.8.16.0001",
            recorrente="JOÃO DA SILVA",
            especie_recurso="RECURSO ESPECIAL",
            evidencias_campos={
                "numero_processo": CampoEvidencia(
                    citacao_literal="Processo nº 1234567-89.2024.8.16.0001",
                    pagina=1,
                    ancora="Processo nº 1234567-89.2024.8.16.0001",
                    offset_inicio=0,
                ),
                "recorrente": CampoEvidencia(
                    citacao_literal="Recorrente: JOÃO DA SILVA",
                    pagina=1,
                    ancora="Recorrente: JOÃO DA SILVA",
                    offset_inicio=10,
                ),
                "especie_recurso": CampoEvidencia(
                    citacao_literal="Espécie: RECURSO ESPECIAL",
                    pagina=1,
                    ancora="Espécie: RECURSO ESPECIAL",
                    offset_inicio=20,
                ),
            },
        )
        alertas = _validar_evidencias_campos_criticos(resultado, "texto")
        assert alertas == []

    def test_verificador_independente_confirma_campos(self) -> None:
        texto = (
            "Processo nº 1234567-89.2024.8.16.0001\n"
            "Recorrente: JOÃO DA SILVA\n"
            "Espécie: RECURSO ESPECIAL\n"
        )
        resultado = ResultadoEtapa1(
            numero_processo="1234567-89.2024.8.16.0001",
            recorrente="JOÃO DA SILVA",
            especie_recurso="RECURSO ESPECIAL",
        )
        alertas = _verificador_independente_etapa1(resultado, texto)
        assert alertas == []
        assert resultado.verificacao_campos["numero_processo"] is True
        assert resultado.verificacao_campos["recorrente"] is True
        assert resultado.verificacao_campos["especie_recurso"] is True

    def test_verificador_independente_detecta_inconsistencia(self) -> None:
        texto = "Processo nº 1111111-11.2024.8.16.0001"
        resultado = ResultadoEtapa1(
            numero_processo="9999999-99.2024.8.16.0001",
            recorrente="NOME QUE NÃO CONSTA",
            especie_recurso="RECURSO ESPECIAL",
        )
        alertas = _verificador_independente_etapa1(resultado, texto)
        assert len(alertas) >= 1
        assert resultado.verificacao_campos["numero_processo"] is False


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


class TestContextManagement:
    """Test context reduction behavior."""

    def test_verificar_contexto_preserves_head_and_tail(self, monkeypatch) -> None:
        original = (
            "INICIO_IMPORTANTE " + ("A" * 6000) + " MEIO " + ("B" * 6000) + " FIM_IMPORTANTE"
        )
        monkeypatch.setattr("src.etapa1.CONTEXT_LIMIT_TOKENS", 1000)
        monkeypatch.setattr("src.etapa1.CONTEXT_WARNING_RATIO", 0.8)
        monkeypatch.setattr("src.etapa1.estimar_tokens", lambda texto: 2000)

        reduced = _verificar_contexto(original)

        assert "INICIO_IMPORTANTE" in reduced
        assert "FIM_IMPORTANTE" in reduced
        assert "CONTEÚDO INTERMEDIÁRIO OMITIDO" in reduced


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


class TestExecutarEtapa1Flow:
    """Test structured-first execution and fallback behavior."""

    def test_structured_first_success(self, monkeypatch) -> None:
        payload = {
            "numero_processo": "1234567-89.2024.8.16.0001",
            "recorrente": "JOÃO DA SILVA",
            "recorrido": "MARIA",
            "especie_recurso": "RECURSO ESPECIAL",
            "permissivo_constitucional": "art. 105, III",
            "camara_civel": "10ª Câmara Cível",
            "dispositivos_violados": ["art. 927 CC"],
            "justica_gratuita": True,
            "efeito_suspensivo": False,
        }

        monkeypatch.setattr("src.etapa1.chamar_llm_json", lambda **kwargs: payload)

        def _should_not_call_llm(**kwargs):
            raise AssertionError("fallback legacy should not be called")

        monkeypatch.setattr("src.etapa1.chamar_llm", _should_not_call_llm)

        resultado = executar_etapa1(
            texto_recurso="Processo 1234567-89.2024.8.16.0001 Recorrente JOÃO DA SILVA Recurso Especial",
            prompt_sistema="prompt",
            modelo_override="gpt-4o",
        )
        assert resultado.numero_processo.startswith("1234567")
        assert resultado.recorrente == "JOÃO DA SILVA"
        assert resultado.inconclusivo is False

    def test_structured_failure_falls_back_to_legacy(self, monkeypatch) -> None:
        calls = {"json": 0}

        def _fail_json(**kwargs):
            calls["json"] += 1
            raise RuntimeError("json inválido")

        monkeypatch.setattr("src.etapa1.chamar_llm_json", _fail_json)

        class _FakeResponse:
            content = SAMPLE_RESPONSE
            tokens = type("T", (), {"total_tokens": 100, "prompt_tokens": 60, "completion_tokens": 40})()

        monkeypatch.setattr("src.etapa1.chamar_llm", lambda **kwargs: _FakeResponse())

        resultado = executar_etapa1(
            texto_recurso="Processo 1234567-89.2024.8.16.0001 Recorrente JOÃO DA SILVA",
            prompt_sistema="prompt",
            modelo_override="gpt-4o",
        )

        assert calls["json"] == 4
        assert "1234567" in resultado.numero_processo

    def test_structured_retry_orientado_por_erro(self, monkeypatch) -> None:
        call_data = {"count": 0, "developer_prompts": []}

        def _llm_json_retry(**kwargs):
            call_data["count"] += 1
            messages = kwargs.get("messages") or []
            for m in messages:
                if m.get("role") == "developer":
                    call_data["developer_prompts"].append(m.get("content", ""))
                    break
            if call_data["count"] == 1:
                return {
                    "numero_processo": "",
                    "recorrente": "JOÃO DA SILVA",
                    "recorrido": "MARIA",
                    "especie_recurso": "RECURSO ESPECIAL",
                    "permissivo_constitucional": "art. 105, III",
                    "camara_civel": "10ª Câmara Cível",
                    "dispositivos_violados": ["art. 927 CC"],
                    "justica_gratuita": True,
                    "efeito_suspensivo": False,
                    "evidencias_campos": {},
                }
            return {
                "numero_processo": "1234567-89.2024.8.16.0001",
                "recorrente": "JOÃO DA SILVA",
                "recorrido": "MARIA",
                "especie_recurso": "RECURSO ESPECIAL",
                "permissivo_constitucional": "art. 105, III",
                "camara_civel": "10ª Câmara Cível",
                "dispositivos_violados": ["art. 927 CC"],
                "justica_gratuita": True,
                "efeito_suspensivo": False,
                "evidencias_campos": {},
            }

        monkeypatch.setattr("src.etapa1.chamar_llm_json", _llm_json_retry)

        def _should_not_call_llm(**kwargs):
            raise AssertionError("fallback legacy should not be called")

        monkeypatch.setattr("src.etapa1.chamar_llm", _should_not_call_llm)

        texto = (
            "Processo nº 1234567-89.2024.8.16.0001\n"
            "Recorrente: JOÃO DA SILVA\n"
            "Espécie: RECURSO ESPECIAL\n"
        )
        resultado = executar_etapa1(
            texto_recurso=texto,
            prompt_sistema="",
            modelo_override="gpt-4o",
        )
        assert call_data["count"] == 2
        assert resultado.numero_processo.startswith("1234567")
        assert any("Correções obrigatórias nesta tentativa" in p for p in call_data["developer_prompts"][1:])
        assert any("Corrija campos obrigatórios ausentes" in p for p in call_data["developer_prompts"][1:])

    def test_fallback_free_text_uses_json_normalizer_before_regex(self, monkeypatch) -> None:
        calls = {"json": 0}

        def _json_with_conversion(**kwargs):
            calls["json"] += 1
            if calls["json"] <= 3:
                raise RuntimeError("structured fail")
            return {
                "numero_processo": "1234567-89.2024.8.16.0001",
                "recorrente": "JOÃO DA SILVA",
                "recorrido": "MARIA",
                "especie_recurso": "RECURSO ESPECIAL",
                "permissivo_constitucional": "art. 105, III",
                "camara_civel": "10ª Câmara Cível",
                "dispositivos_violados": ["art. 927 CC"],
                "justica_gratuita": True,
                "efeito_suspensivo": False,
                "evidencias_campos": {},
            }

        monkeypatch.setattr("src.etapa1.chamar_llm_json", _json_with_conversion)

        class _FakeResponse:
            content = "Saída livre não estruturada."
            tokens = type("T", (), {"total_tokens": 100, "prompt_tokens": 60, "completion_tokens": 40})()

        monkeypatch.setattr("src.etapa1.chamar_llm", lambda **kwargs: _FakeResponse())
        monkeypatch.setattr(
            "src.etapa1._parse_resposta_llm",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("regex parser should not run")),
        )

        resultado = executar_etapa1(
            texto_recurso=(
                "Processo nº 1234567-89.2024.8.16.0001\n"
                "Recorrente: JOÃO DA SILVA\n"
                "Espécie: RECURSO ESPECIAL\n"
            ),
            prompt_sistema="prompt",
            modelo_override="gpt-4o",
        )

        assert calls["json"] == 4
        assert resultado.numero_processo.startswith("1234567")

    def test_structured_flow_backfills_missing_evidence(self, monkeypatch) -> None:
        payload = {
            "numero_processo": "1234567-89.2024.8.16.0001",
            "recorrente": "JOÃO DA SILVA",
            "recorrido": "MARIA",
            "especie_recurso": "RECURSO ESPECIAL",
            "permissivo_constitucional": "art. 105, III",
            "camara_civel": "10ª Câmara Cível",
            "dispositivos_violados": ["art. 927 CC"],
            "justica_gratuita": True,
            "efeito_suspensivo": False,
            "evidencias_campos": {},
        }
        monkeypatch.setattr("src.etapa1.chamar_llm_json", lambda **kwargs: payload)

        def _should_not_call_llm(**kwargs):
            raise AssertionError("fallback legacy should not be called")

        monkeypatch.setattr("src.etapa1.chamar_llm", _should_not_call_llm)

        texto = (
            "Processo nº 1234567-89.2024.8.16.0001\n"
            "Recorrente: JOÃO DA SILVA\n"
            "Espécie: RECURSO ESPECIAL\n"
        )
        resultado = executar_etapa1(
            texto_recurso=texto,
            prompt_sistema="prompt",
            modelo_override="gpt-4o",
        )

        for campo in ("numero_processo", "recorrente", "especie_recurso"):
            assert campo in resultado.evidencias_campos
            evid = resultado.evidencias_campos[campo]
            assert evid.citacao_literal
            assert evid.ancora
            assert evid.pagina is not None
            assert resultado.verificacao_campos.get(campo) is True
        assert resultado.inconclusivo is False

    def test_marks_inconclusivo_when_still_invalid_after_retries(self, monkeypatch) -> None:
        def _always_invalid_json(**kwargs):
            return {
                "numero_processo": "",
                "recorrente": "",
                "recorrido": "",
                "especie_recurso": "",
                "permissivo_constitucional": "",
                "camara_civel": "",
                "dispositivos_violados": [],
                "justica_gratuita": False,
                "efeito_suspensivo": False,
                "evidencias_campos": {},
            }

        monkeypatch.setattr("src.etapa1.chamar_llm_json", _always_invalid_json)

        class _FakeResponse:
            content = "Texto insuficiente para extração."
            tokens = type("T", (), {"total_tokens": 40, "prompt_tokens": 25, "completion_tokens": 15})()

        monkeypatch.setattr("src.etapa1.chamar_llm", lambda **kwargs: _FakeResponse())

        resultado = executar_etapa1(
            texto_recurso="Documento sem dados suficientes.",
            prompt_sistema="prompt",
            modelo_override="gpt-4o",
        )

        assert resultado.inconclusivo is True
        assert resultado.motivo_inconclusivo
        assert "Campo obrigatório ausente" in resultado.motivo_inconclusivo

    def test_consenso_n2_aplica_valor_convergente_em_baixa_confianca(self, monkeypatch) -> None:
        monkeypatch.setattr("src.etapa1.ENABLE_ETAPA1_CRITICAL_FIELDS_CONSENSUS", True)
        call_state = {"structured": 0, "consenso": 0}

        def _llm_json_stub(**kwargs):
            messages = kwargs.get("messages") or []
            developer_prompt = ""
            for msg in messages:
                if msg.get("role") == "developer":
                    developer_prompt = msg.get("content", "")
                    break

            if "CONSENSO_N2_ETAPA1" in developer_prompt:
                call_state["consenso"] += 1
                return {
                    "numero_processo": "1234567-89.2024.8.16.0001",
                    "recorrente": "JOÃO DA SILVA",
                    "especie_recurso": "RECURSO ESPECIAL",
                    "evidencias_campos": {},
                }

            call_state["structured"] += 1
            if call_state["structured"] == 1:
                return {
                    "numero_processo": "",
                    "recorrente": "JOÃO",
                    "especie_recurso": "RECURSO ESPECIAL",
                    "evidencias_campos": {},
                }
            return {
                "numero_processo": "1234567-89.2024.8.16.0001",
                "recorrente": "JOÃO",
                "especie_recurso": "RECURSO ESPECIAL",
                "evidencias_campos": {},
            }

        monkeypatch.setattr("src.etapa1.chamar_llm_json", _llm_json_stub)
        monkeypatch.setattr(
            "src.etapa1.chamar_llm",
            lambda **kwargs: (_ for _ in ()).throw(AssertionError("fallback legacy should not be called")),
        )

        texto = (
            "Processo nº 1234567-89.2024.8.16.0001\n"
            "Recorrente: JOÃO DA SILVA\n"
            "Espécie: RECURSO ESPECIAL\n"
        )
        resultado = executar_etapa1(
            texto_recurso=texto,
            prompt_sistema="",
            modelo_override="gpt-4o",
        )

        assert call_state["structured"] >= 2
        assert call_state["consenso"] == 2
        assert resultado.recorrente == "JOÃO DA SILVA"
        assert resultado.inconclusivo is False

    def test_consenso_n2_nao_sobrescreve_quando_diverge(self, monkeypatch) -> None:
        monkeypatch.setattr("src.etapa1.ENABLE_ETAPA1_CRITICAL_FIELDS_CONSENSUS", True)
        call_state = {"structured": 0, "consenso": 0}

        def _llm_json_stub(**kwargs):
            messages = kwargs.get("messages") or []
            developer_prompt = ""
            for msg in messages:
                if msg.get("role") == "developer":
                    developer_prompt = msg.get("content", "")
                    break

            if "CONSENSO_N2_ETAPA1" in developer_prompt:
                call_state["consenso"] += 1
                nome = "JOÃO DA SILVA" if call_state["consenso"] == 1 else "JOÃO PEDRO"
                return {
                    "numero_processo": "1234567-89.2024.8.16.0001",
                    "recorrente": nome,
                    "especie_recurso": "RECURSO ESPECIAL",
                    "evidencias_campos": {},
                }

            call_state["structured"] += 1
            if call_state["structured"] == 1:
                return {
                    "numero_processo": "",
                    "recorrente": "JOÃO",
                    "especie_recurso": "RECURSO ESPECIAL",
                    "evidencias_campos": {},
                }
            return {
                "numero_processo": "1234567-89.2024.8.16.0001",
                "recorrente": "JOÃO",
                "especie_recurso": "RECURSO ESPECIAL",
                "evidencias_campos": {},
            }

        monkeypatch.setattr("src.etapa1.chamar_llm_json", _llm_json_stub)
        monkeypatch.setattr(
            "src.etapa1.chamar_llm",
            lambda **kwargs: (_ for _ in ()).throw(AssertionError("fallback legacy should not be called")),
        )

        texto = (
            "Processo nº 1234567-89.2024.8.16.0001\n"
            "Recorrente: JOÃO DA SILVA\n"
            "Espécie: RECURSO ESPECIAL\n"
        )
        resultado = executar_etapa1(
            texto_recurso=texto,
            prompt_sistema="",
            modelo_override="gpt-4o",
        )

        assert call_state["structured"] >= 2
        assert call_state["consenso"] == 2
        assert resultado.recorrente == "JOÃO"
        assert resultado.inconclusivo is False
