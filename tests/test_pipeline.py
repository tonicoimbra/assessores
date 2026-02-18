"""Tests for Sprint 6: Pipeline orchestrator, CLI, and error handling."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.main import build_parser
from src.models import (
    CampoEvidencia,
    Decisao,
    DocumentoEntrada,
    EstadoPipeline,
    MetadadosPipeline,
    ResultadoEtapa1,
    ResultadoEtapa2,
    ResultadoEtapa3,
    TemaEtapa2,
    TipoDocumento,
)
from src.pipeline import (
    FRIENDLY_ERRORS,
    PipelineValidationError,
    PipelineAdmissibilidade,
    _avaliar_politica_escalonamento,
    _build_structured_log_event,
    _calcular_confiancas_pipeline,
    _validar_etapa1,
    _validar_etapa2,
    _validar_etapa3,
    _estimar_custo,
    get_friendly_error,
    handle_pipeline_error,
)
from src.state_manager import restaurar_estado, salvar_estado


# --- 6.4.1: Pipeline with mocks ---


class TestPipelineMocked:
    """Test pipeline orchestrator with mocked LLM/PDF calls."""

    def test_pipeline_instantiation(self) -> None:
        p = PipelineAdmissibilidade()
        assert p.modelo == "gpt-4o"
        assert p.formato_saida == "md"
        assert callable(p.progress)

    def test_pipeline_instantiation_docx(self) -> None:
        p = PipelineAdmissibilidade(formato_saida="docx")
        assert p.formato_saida == "docx"

    def test_pipeline_invalid_output_format(self) -> None:
        with pytest.raises(ValueError):
            PipelineAdmissibilidade(formato_saida="pdf")

    def test_cost_estimation(self) -> None:
        cost = _estimar_custo(10_000, 5_000, "gpt-4o")
        expected = (10_000 * 2.50 + 5_000 * 10.00) / 1_000_000
        assert abs(cost - expected) < 0.0001

    def test_cost_estimation_mini(self) -> None:
        cost = _estimar_custo(10_000, 5_000, "gpt-4o-mini")
        expected = (10_000 * 0.15 + 5_000 * 0.60) / 1_000_000
        assert cost < _estimar_custo(10_000, 5_000, "gpt-4o")

    def test_custom_progress_callback(self) -> None:
        calls = []
        def tracker(msg, step, total):
            calls.append((msg, step, total))
        p = PipelineAdmissibilidade(progress=tracker)
        p._notify("test", 1, 5)
        assert len(calls) == 1
        assert calls[0] == ("test", 1, 5)

    def test_build_structured_log_event_contains_correlation_fields(self) -> None:
        payload = _build_structured_log_event(
            evento="etapa1_concluida",
            processo_id="proc-1",
            execucao_id="exec-1",
            etapa="etapa1",
            extra={"duracao_s": 1.23},
        )
        assert payload["evento"] == "etapa1_concluida"
        assert payload["processo_id"] == "proc-1"
        assert payload["execucao_id"] == "exec-1"
        assert payload["etapa"] == "etapa1"
        assert payload["duracao_s"] == 1.23
        assert payload["timestamp"]


# --- 6.4.2: State recovery ---


class TestStateRecovery:
    """Test state recovery after interruption."""

    def test_save_and_restore(self, tmp_path: Path) -> None:
        with patch("src.state_manager.CHECKPOINT_DIR", tmp_path):
            estado = EstadoPipeline(
                resultado_etapa1=ResultadoEtapa1(numero_processo="123"),
            )
            salvar_estado(estado, "test_recovery")
            restored = restaurar_estado(processo_id="test_recovery")
            assert restored is not None
            assert restored.resultado_etapa1.numero_processo == "123"

    def test_restore_nonexistent(self, tmp_path: Path) -> None:
        with patch("src.state_manager.CHECKPOINT_DIR", tmp_path):
            restored = restaurar_estado(processo_id="nonexistent")
            assert restored is None

    def test_error_handler_saves_state(self, tmp_path: Path) -> None:
        with patch("src.state_manager.CHECKPOINT_DIR", tmp_path):
            estado = EstadoPipeline(
                resultado_etapa1=ResultadoEtapa1(numero_processo="err_test"),
            )
            handle_pipeline_error(ValueError("test"), estado, "err_test")
            restored = restaurar_estado(processo_id="err_test")
            assert restored is not None

    def test_error_handler_persists_dead_letter_for_non_transient(self, tmp_path: Path) -> None:
        checkpoint_dir = tmp_path / "checkpoints"
        dead_letter_dir = tmp_path / "dead_letter"
        with (
            patch("src.state_manager.CHECKPOINT_DIR", checkpoint_dir),
            patch("src.dead_letter_queue.DEAD_LETTER_DIR", dead_letter_dir),
        ):
            estado = EstadoPipeline(
                metadata=MetadadosPipeline(execucao_id="exec-dlq"),
                resultado_etapa1=ResultadoEtapa1(numero_processo="err_dlq"),
            )
            path = handle_pipeline_error(
                ValueError("erro persistente"),
                estado,
                "err_dlq",
                metricas={"tempo_total": 1.1},
                contexto={"origem": "teste"},
            )

            assert path is not None
            assert path.exists()
            payload = json.loads(path.read_text(encoding="utf-8"))
            assert payload["processo_id"] == "err_dlq"
            assert payload["execucao_id"] == "exec-dlq"
            assert payload["erro"]["tipo"] == "ValueError"
            assert payload["metricas"]["tempo_total"] == 1.1

    def test_error_handler_ignores_dead_letter_for_transient(self, tmp_path: Path) -> None:
        checkpoint_dir = tmp_path / "checkpoints"
        dead_letter_dir = tmp_path / "dead_letter"
        with (
            patch("src.state_manager.CHECKPOINT_DIR", checkpoint_dir),
            patch("src.dead_letter_queue.DEAD_LETTER_DIR", dead_letter_dir),
        ):
            estado = EstadoPipeline(
                resultado_etapa1=ResultadoEtapa1(numero_processo="err_transient"),
            )
            APITimeoutError = type("APITimeoutError", (Exception,), {})
            path = handle_pipeline_error(APITimeoutError("timeout"), estado, "err_transient")
            assert path is None
            assert list(dead_letter_dir.glob("*.json")) == []


# --- 6.4.3: CLI arguments ---


class TestCLIArgs:
    """Test CLI argument parsing."""

    def test_processar_with_defaults(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["processar", "file.pdf"])
        assert args.pdfs == ["file.pdf"]
        assert args.modelo == "gpt-4o"
        assert args.formato == "md"
        assert args.verbose is False

    def test_processar_with_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "processar", "a.pdf", "b.pdf",
            "--modelo", "gpt-4o-mini",
            "--temperatura", "0.5",
            "--saida", "/tmp/out",
            "--formato", "docx",
            "--verbose",
            "--continuar",
        ])
        assert args.pdfs == ["a.pdf", "b.pdf"]
        assert args.modelo == "gpt-4o-mini"
        assert args.temperatura == 0.5
        assert args.saida == "/tmp/out"
        assert args.formato == "docx"
        assert args.verbose is True
        assert args.continuar is True

    def test_processar_invalid_format(self) -> None:
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["processar", "a.pdf", "--formato", "pdf"])

    def test_status_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["status"])
        assert args.comando == "status"

    def test_limpar_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["limpar"])
        assert args.comando == "limpar"

    def test_dashboard_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["dashboard", "--entrada", "outputs", "--saida", "outputs"])
        assert args.comando == "dashboard"
        assert args.entrada == "outputs"
        assert args.saida == "outputs"

    def test_baseline_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["baseline", "--entrada", "tests/fixtures/golden", "--saida", "outputs"])
        assert args.comando == "baseline"
        assert args.entrada == "tests/fixtures/golden"
        assert args.saida == "outputs"

    def test_quality_gate_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            ["quality-gate", "--baseline", "outputs/baseline_dataset_ouro_x.json", "--saida", "outputs"]
        )
        assert args.comando == "quality-gate"
        assert args.baseline == "outputs/baseline_dataset_ouro_x.json"
        assert args.saida == "outputs"

    def test_alerts_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "alerts",
                "--baseline",
                "outputs/baseline_dataset_ouro_new.json",
                "--previous-baseline",
                "outputs/baseline_dataset_ouro_old.json",
                "--saida",
                "outputs",
            ]
        )
        assert args.comando == "alerts"
        assert args.baseline == "outputs/baseline_dataset_ouro_new.json"
        assert args.previous_baseline == "outputs/baseline_dataset_ouro_old.json"
        assert args.saida == "outputs"

    def test_no_command_exits(self) -> None:
        parser = build_parser()
        args = parser.parse_args([])
        assert args.comando is None


# --- 6.4.4: Error handling ---


class TestErrorHandling:
    """Test friendly error messages and error handling."""

    def test_friendly_auth_error(self) -> None:
        exc = type("AuthenticationError", (Exception,), {})()
        msg = get_friendly_error(exc)
        assert "API key" in msg

    def test_friendly_rate_limit(self) -> None:
        exc = type("RateLimitError", (Exception,), {})()
        msg = get_friendly_error(exc)
        assert "Quota" in msg or "quota" in msg

    def test_friendly_timeout(self) -> None:
        exc = type("APITimeoutError", (Exception,), {})()
        msg = get_friendly_error(exc)
        assert "Timeout" in msg or "timeout" in msg

    def test_friendly_file_not_found(self) -> None:
        msg = get_friendly_error(FileNotFoundError("test.pdf"))
        assert "não encontrado" in msg

    def test_unknown_error_fallback(self) -> None:
        msg = get_friendly_error(RuntimeError("boom"))
        assert "boom" in msg

    def test_all_friendly_errors_defined(self) -> None:
        assert len(FRIENDLY_ERRORS) >= 5


class TestFailClosedValidation:
    """Test fail-closed stage validations."""

    def test_validar_etapa1_detects_required_fields(self) -> None:
        erros = _validar_etapa1(ResultadoEtapa1())
        assert any("numero_processo" in e for e in erros)
        assert any("recorrente" in e for e in erros)
        assert any("especie_recurso" in e for e in erros)

    def test_validar_etapa1_detects_inconclusive_flag(self) -> None:
        erros = _validar_etapa1(
            ResultadoEtapa1(
                numero_processo="123",
                recorrente="JOÃO",
                especie_recurso="RECURSO ESPECIAL",
                inconclusivo=True,
                motivo_inconclusivo="campo sem lastro",
            )
        )
        assert any("inconclusiva" in e for e in erros)

    def test_validar_etapa1_detects_missing_evidence(self) -> None:
        erros = _validar_etapa1(
            ResultadoEtapa1(
                numero_processo="123",
                recorrente="JOÃO",
                especie_recurso="RECURSO ESPECIAL",
            )
        )
        assert any("sem evidência para numero_processo" in e for e in erros)
        assert any("sem evidência para recorrente" in e for e in erros)
        assert any("sem evidência para especie_recurso" in e for e in erros)

    def test_validar_etapa1_accepts_complete_evidence(self) -> None:
        erros = _validar_etapa1(
            ResultadoEtapa1(
                numero_processo="123",
                recorrente="JOÃO",
                especie_recurso="RECURSO ESPECIAL",
                evidencias_campos={
                    "numero_processo": CampoEvidencia(
                        citacao_literal="Processo nº 123",
                        pagina=1,
                        ancora="Processo nº 123",
                        offset_inicio=0,
                    ),
                    "recorrente": CampoEvidencia(
                        citacao_literal="Recorrente: JOÃO",
                        pagina=1,
                        ancora="Recorrente: JOÃO",
                        offset_inicio=10,
                    ),
                    "especie_recurso": CampoEvidencia(
                        citacao_literal="Espécie: RECURSO ESPECIAL",
                        pagina=1,
                        ancora="Espécie: RECURSO ESPECIAL",
                        offset_inicio=20,
                    ),
                },
                verificacao_campos={
                    "numero_processo": True,
                    "recorrente": True,
                    "especie_recurso": True,
                },
            )
        )
        assert erros == []

    def test_validar_etapa1_detects_missing_independent_verification(self) -> None:
        erros = _validar_etapa1(
            ResultadoEtapa1(
                numero_processo="123",
                recorrente="JOÃO",
                especie_recurso="RECURSO ESPECIAL",
                evidencias_campos={
                    "numero_processo": CampoEvidencia(
                        citacao_literal="Processo nº 123",
                        pagina=1,
                        ancora="Processo nº 123",
                    ),
                    "recorrente": CampoEvidencia(
                        citacao_literal="Recorrente: JOÃO",
                        pagina=1,
                        ancora="Recorrente: JOÃO",
                    ),
                    "especie_recurso": CampoEvidencia(
                        citacao_literal="Espécie: RECURSO ESPECIAL",
                        pagina=1,
                        ancora="Espécie: RECURSO ESPECIAL",
                    ),
                },
                verificacao_campos={"numero_processo": True},
            )
        )
        assert any("sem verificação independente positiva para recorrente" in e for e in erros)
        assert any("sem verificação independente positiva para especie_recurso" in e for e in erros)

    def test_pipeline_blocks_etapa2_when_etapa1_inconclusive(self, monkeypatch) -> None:
        estado = EstadoPipeline(
            documentos_entrada=[
                DocumentoEntrada(filepath="recurso.pdf", texto_extraido="texto recurso", tipo=TipoDocumento.RECURSO),
                DocumentoEntrada(filepath="acordao.pdf", texto_extraido="texto acordao", tipo=TipoDocumento.ACORDAO),
            ],
            resultado_etapa1=ResultadoEtapa1(
                numero_processo="123",
                recorrente="JOÃO",
                especie_recurso="RECURSO ESPECIAL",
                inconclusivo=True,
                motivo_inconclusivo="Campo obrigatório ausente: recorrente",
            ),
        )

        monkeypatch.setattr("src.pipeline.restaurar_estado", lambda processo_id=None: estado)

        def _should_not_call_etapa2(*args, **kwargs):
            raise AssertionError("Etapa 2 should be blocked when Etapa 1 is inconclusive")

        monkeypatch.setattr("src.pipeline.executar_etapa2", _should_not_call_etapa2)
        monkeypatch.setattr("src.pipeline.executar_etapa2_com_chunking", _should_not_call_etapa2)
        monkeypatch.setattr("src.pipeline.executar_etapa2_paralelo", _should_not_call_etapa2)

        pipeline = PipelineAdmissibilidade()
        with pytest.raises(PipelineValidationError) as exc:
            pipeline.executar(pdfs=[], processo_id="test_inconclusivo", continuar=True)

        msg = str(exc.value)
        assert msg.startswith("MOTIVO_BLOQUEIO[E1_INCONCLUSIVA]")
        assert "Campo obrigatório ausente: recorrente" in msg

    def test_validar_etapa2_detects_missing_themes(self) -> None:
        erros = _validar_etapa2(ResultadoEtapa2(temas=[]))
        assert any("sem temas" in e for e in erros)

    def test_validar_etapa2_detects_missing_theme_evidence(self) -> None:
        erros = _validar_etapa2(
            ResultadoEtapa2(
                temas=[
                    TemaEtapa2(
                        materia_controvertida="Responsabilidade civil",
                        conclusao_fundamentos="Improcedência mantida",
                        obices_sumulas=["Súmula 7"],
                        trecho_transcricao="Trecho literal",
                        evidencias_campos={},
                    )
                ]
            )
        )
        assert any("sem evidência para materia_controvertida" in e for e in erros)
        assert any("sem evidência para conclusao_fundamentos" in e for e in erros)
        assert any("sem evidência para obices_sumulas" in e for e in erros)
        assert any("sem evidência para trecho_transcricao" in e for e in erros)

    def test_validar_etapa2_accepts_complete_theme_evidence(self) -> None:
        erros = _validar_etapa2(
            ResultadoEtapa2(
                temas=[
                    TemaEtapa2(
                        materia_controvertida="Responsabilidade civil",
                        conclusao_fundamentos="Improcedência mantida",
                        obices_sumulas=["Súmula 7"],
                        trecho_transcricao="Trecho literal",
                        evidencias_campos={
                            "materia_controvertida": CampoEvidencia(
                                citacao_literal="Tema: responsabilidade civil",
                                pagina=1,
                                ancora="tema 1",
                            ),
                            "conclusao_fundamentos": CampoEvidencia(
                                citacao_literal="Improcedência mantida",
                                pagina=1,
                                ancora="conclusão",
                            ),
                            "obices_sumulas": CampoEvidencia(
                                citacao_literal="Incide a Súmula 7",
                                pagina=1,
                                ancora="óbice",
                            ),
                            "trecho_transcricao": CampoEvidencia(
                                citacao_literal="Trecho literal do acórdão",
                                pagina=2,
                                ancora="trecho",
                            ),
                        },
                    )
                ]
            )
        )
        assert erros == []

    def test_pipeline_blocks_etapa3_when_etapa2_missing_evidence(self, monkeypatch) -> None:
        estado = EstadoPipeline(
            documentos_entrada=[
                DocumentoEntrada(filepath="recurso.pdf", texto_extraido="texto recurso", tipo=TipoDocumento.RECURSO),
                DocumentoEntrada(filepath="acordao.pdf", texto_extraido="texto acordao", tipo=TipoDocumento.ACORDAO),
            ],
            resultado_etapa1=ResultadoEtapa1(
                numero_processo="123",
                recorrente="JOÃO",
                especie_recurso="RECURSO ESPECIAL",
            ),
            resultado_etapa2=ResultadoEtapa2(
                temas=[
                    TemaEtapa2(
                        materia_controvertida="Responsabilidade civil",
                        conclusao_fundamentos="Improcedência mantida",
                        obices_sumulas=["Súmula 7"],
                        trecho_transcricao="Trecho literal",
                        evidencias_campos={},
                    )
                ]
            ),
        )

        monkeypatch.setattr("src.pipeline.restaurar_estado", lambda processo_id=None: estado)

        def _should_not_call_etapa3(*args, **kwargs):
            raise AssertionError("Etapa 3 should be blocked when Etapa 2 evidence is incomplete")

        monkeypatch.setattr("src.pipeline.executar_etapa3", _should_not_call_etapa3)
        monkeypatch.setattr("src.pipeline.executar_etapa3_com_chunking", _should_not_call_etapa3)

        pipeline = PipelineAdmissibilidade()
        with pytest.raises(PipelineValidationError) as exc:
            pipeline.executar(pdfs=[], processo_id="test_e2_sem_evid", continuar=True)

        assert "Etapa 2 tema 1 sem evidência" in str(exc.value)

    def test_validar_etapa3_detects_missing_decision(self) -> None:
        erros = _validar_etapa3(ResultadoEtapa3(minuta_completa="texto", decisao=None))
        assert any("sem decisão estruturada" in e for e in erros)

    def test_validar_etapa3_detects_missing_structured_fields(self) -> None:
        erros = _validar_etapa3(
            ResultadoEtapa3(
                minuta_completa="Seção I\nSeção II\nSeção III\nINADMITO o recurso",
                decisao=Decisao.INADMITIDO,
            )
        )
        assert any("sem fundamentos_decisao" in e for e in erros)
        assert any("sem itens_evidencia_usados" in e for e in erros)

    def test_validar_etapa3_accepts_inconclusivo_with_explicit_warning(self) -> None:
        erros = _validar_etapa3(
            ResultadoEtapa3(
                minuta_completa="AVISO: Decisão jurídica inconclusiva: Requer análise adicional.",
                decisao=Decisao.INCONCLUSIVO,
                fundamentos_decisao=["Dados insuficientes."],
                itens_evidencia_usados=["Etapa 2/tema 1 sem evidência suficiente"],
                aviso_inconclusivo=True,
                motivo_bloqueio_codigo="E3_INCONCLUSIVO",
                motivo_bloqueio_descricao="Dados insuficientes para decisão conclusiva.",
            )
        )
        assert erros == []

    def test_validar_etapa3_rejects_inconclusivo_without_warning(self) -> None:
        erros = _validar_etapa3(
            ResultadoEtapa3(
                minuta_completa="Seção III – Decisão ainda pendente.",
                decisao=Decisao.INCONCLUSIVO,
                fundamentos_decisao=["Dados insuficientes."],
                itens_evidencia_usados=["Tema 1 sem conclusao."],
                aviso_inconclusivo=False,
                motivo_bloqueio_codigo="E3_INCONCLUSIVO",
                motivo_bloqueio_descricao="Dados insuficientes para decisão conclusiva.",
            )
        )
        assert any("inconclusiva sem aviso explícito" in e for e in erros)

    def test_calcular_confiancas_pipeline_high_when_clean(self) -> None:
        estado = EstadoPipeline(
            resultado_etapa1=ResultadoEtapa1(
                numero_processo="123",
                recorrente="JOÃO",
                especie_recurso="RECURSO ESPECIAL",
                permissivo_constitucional="art. 105, III, a, CF",
                dispositivos_violados=["art. 489 do CPC"],
                evidencias_campos={
                    "numero_processo": CampoEvidencia(
                        citacao_literal="Processo nº 123",
                        pagina=1,
                        ancora="Processo nº 123",
                    ),
                    "recorrente": CampoEvidencia(
                        citacao_literal="Recorrente: JOÃO",
                        pagina=1,
                        ancora="Recorrente: JOÃO",
                    ),
                    "especie_recurso": CampoEvidencia(
                        citacao_literal="Espécie: RECURSO ESPECIAL",
                        pagina=1,
                        ancora="Espécie: RECURSO ESPECIAL",
                    ),
                },
                verificacao_campos={
                    "numero_processo": True,
                    "recorrente": True,
                    "especie_recurso": True,
                },
            ),
            resultado_etapa2=ResultadoEtapa2(
                temas=[
                    TemaEtapa2(
                        materia_controvertida="Responsabilidade civil",
                        conclusao_fundamentos="Improcedência mantida",
                        obices_sumulas=["Súmula 7"],
                        trecho_transcricao="Trecho literal",
                        evidencias_campos={
                            "materia_controvertida": CampoEvidencia(
                                citacao_literal="Tema: responsabilidade civil",
                                pagina=1,
                                ancora="tema 1",
                            ),
                            "conclusao_fundamentos": CampoEvidencia(
                                citacao_literal="Improcedência mantida",
                                pagina=1,
                                ancora="conclusão",
                            ),
                            "obices_sumulas": CampoEvidencia(
                                citacao_literal="Incide a Súmula 7",
                                pagina=1,
                                ancora="óbice",
                            ),
                            "trecho_transcricao": CampoEvidencia(
                                citacao_literal="Trecho literal do acórdão",
                                pagina=2,
                                ancora="trecho",
                            ),
                        },
                    )
                ]
            ),
            resultado_etapa3=ResultadoEtapa3(
                minuta_completa="Seção I\nSeção II\nSeção III\nINADMITO o recurso.",
                decisao=Decisao.INADMITIDO,
                fundamentos_decisao=["Óbice sumular."],
                itens_evidencia_usados=["Tema 1/obices_sumulas: Súmula 7 (p.1)"],
            ),
        )
        confiancas, global_conf, validacoes = _calcular_confiancas_pipeline(estado)
        assert confiancas["etapa1"] >= 0.9
        assert confiancas["etapa2"] >= 0.9
        assert confiancas["etapa3"] >= 0.9
        assert global_conf >= 0.9
        assert validacoes["etapa1"] == []
        assert validacoes["etapa2"] == []
        assert validacoes["etapa3"] == []

    def test_calcular_confiancas_pipeline_caps_inconclusivo(self) -> None:
        estado = EstadoPipeline(
            resultado_etapa1=ResultadoEtapa1(numero_processo="123", recorrente="JOÃO", especie_recurso="RE"),
            resultado_etapa2=ResultadoEtapa2(
                temas=[TemaEtapa2(materia_controvertida="Tema", conclusao_fundamentos="")]
            ),
            resultado_etapa3=ResultadoEtapa3(
                minuta_completa="AVISO: Decisão jurídica inconclusiva: Requer análise adicional.",
                decisao=Decisao.INCONCLUSIVO,
                fundamentos_decisao=["Dados insuficientes."],
                itens_evidencia_usados=["Tema 1 sem conclusão."],
                aviso_inconclusivo=True,
                motivo_bloqueio_codigo="E3_INCONCLUSIVO",
                motivo_bloqueio_descricao="Dados insuficientes para decisão conclusiva.",
            ),
        )
        _, global_conf, _ = _calcular_confiancas_pipeline(estado)
        assert global_conf <= 0.49

    def test_pipeline_confidence_details_present_after_execution(self, monkeypatch, tmp_path: Path) -> None:
        estado = EstadoPipeline(
            documentos_entrada=[
                DocumentoEntrada(filepath="recurso.pdf", texto_extraido="texto recurso", tipo=TipoDocumento.RECURSO),
                DocumentoEntrada(filepath="acordao.pdf", texto_extraido="texto acordao", tipo=TipoDocumento.ACORDAO),
            ],
            resultado_etapa1=ResultadoEtapa1(
                numero_processo="123",
                recorrente="JOÃO",
                especie_recurso="RECURSO ESPECIAL",
                evidencias_campos={
                    "numero_processo": CampoEvidencia(citacao_literal="Processo 123", pagina=1, ancora="Processo"),
                    "recorrente": CampoEvidencia(citacao_literal="Recorrente JOÃO", pagina=1, ancora="Recorrente"),
                    "especie_recurso": CampoEvidencia(citacao_literal="RECURSO ESPECIAL", pagina=1, ancora="Espécie"),
                },
                verificacao_campos={
                    "numero_processo": True,
                    "recorrente": True,
                    "especie_recurso": True,
                },
            ),
            resultado_etapa2=ResultadoEtapa2(
                temas=[
                    TemaEtapa2(
                        materia_controvertida="Responsabilidade civil",
                        conclusao_fundamentos="Improcedência mantida",
                        obices_sumulas=["Súmula 7"],
                        trecho_transcricao="Trecho",
                        evidencias_campos={
                            "materia_controvertida": CampoEvidencia(
                                citacao_literal="Responsabilidade civil", pagina=1, ancora="Tema"
                            ),
                            "conclusao_fundamentos": CampoEvidencia(
                                citacao_literal="Improcedência mantida", pagina=1, ancora="Conclusão"
                            ),
                            "obices_sumulas": CampoEvidencia(
                                citacao_literal="Súmula 7", pagina=1, ancora="Óbice"
                            ),
                            "trecho_transcricao": CampoEvidencia(
                                citacao_literal="Trecho", pagina=1, ancora="Trecho"
                            ),
                        },
                    )
                ]
            ),
            resultado_etapa3=ResultadoEtapa3(
                minuta_completa="Seção I\nSeção II\nSeção III\nINADMITO o recurso.",
                decisao=Decisao.INADMITIDO,
                fundamentos_decisao=["Óbice sumular."],
                itens_evidencia_usados=["Tema 1/obices_sumulas: Súmula 7 (p.1)"],
            ),
        )

        monkeypatch.setattr("src.pipeline.restaurar_estado", lambda processo_id=None: estado)

        p = PipelineAdmissibilidade(formato_saida="md", saida_dir=str(tmp_path))
        p.executar(pdfs=[], processo_id="test_conf_details", continuar=True)

        assert "confianca_campos_etapa1" in p.metricas
        assert "confianca_temas_etapa2" in p.metricas
        assert "politica_escalonamento" in p.metricas
        assert "chunking_auditoria" in p.metricas
        assert p.metricas["politica_escalonamento"]["ativo"] is True
        assert p.metricas["confianca_campos_etapa1"]["numero_processo"] >= 0.9
        assert p.metricas["confianca_temas_etapa2"]["tema_1"] >= 0.9

    def test_avaliar_politica_escalonamento_flags_low_confidence(self) -> None:
        policy = _avaliar_politica_escalonamento(
            confianca_global=0.5,
            confianca_campos_etapa1={"numero_processo": 0.4, "recorrente": 0.9},
            confianca_temas_etapa2={"tema_1": 0.6},
        )
        assert policy["ativo"] is True
        assert policy["escalonar"] is True
        assert len(policy["motivos"]) >= 2

    def test_pipeline_validation_error_message(self) -> None:
        exc = PipelineValidationError("dados inconsistentes")
        msg = get_friendly_error(exc)
        assert "inconsistência" in msg or "qualidade" in msg
