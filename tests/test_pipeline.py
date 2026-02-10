"""Tests for Sprint 6: Pipeline orchestrator, CLI, and error handling."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.main import build_parser
from src.models import (
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
    PipelineAdmissibilidade,
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
