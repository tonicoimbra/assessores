"""Tests for dead-letter queue persistence of non-transient failures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import src.dead_letter_queue as dlq
import src.crypto_utils as cu
from src.models import EstadoPipeline, MetadadosPipeline, ResultadoEtapa1


# ---------------------------------------------------------------------------
# Existing tests — kept intact for regression
# ---------------------------------------------------------------------------


class TestDeadLetterQueue:
    """Validate DLQ classification and snapshot persistence."""

    def test_is_non_transient_error_detects_permanent_failure(self, monkeypatch) -> None:
        monkeypatch.setattr(dlq, "ENABLE_DEAD_LETTER_QUEUE", True)
        assert dlq.is_non_transient_error(ValueError("falha estrutural")) is True

    def test_is_non_transient_error_rejects_transient_by_name(self, monkeypatch) -> None:
        monkeypatch.setattr(dlq, "ENABLE_DEAD_LETTER_QUEUE", True)
        RateLimitError = type("RateLimitError", (Exception,), {})
        assert dlq.is_non_transient_error(RateLimitError("quota excedida")) is False

    def test_salvar_dead_letter_persists_snapshot(self, tmp_path: Path, monkeypatch) -> None:
        key = cu.generate_key()
        monkeypatch.setattr(dlq, "ENABLE_DEAD_LETTER_QUEUE", True)
        monkeypatch.setattr(dlq, "DLQ_ENCRYPTION_ENABLED", True)
        monkeypatch.setattr(dlq, "DLQ_ENCRYPTION_KEY", key)
        estado = EstadoPipeline(
            metadata=MetadadosPipeline(execucao_id="exec-123"),
            resultado_etapa1=ResultadoEtapa1(numero_processo="123"),
        )

        path = dlq.salvar_dead_letter(
            ValueError("payload inválido"),
            processo_id="proc/123",
            estado=estado,
            metricas={"tempo_total": 2.3},
            contexto={"origem": "teste"},
            output_dir=tmp_path,
        )

        assert path is not None
        assert path.exists()
        assert path.suffix == ".dlq"
        payload = dlq.ler_dead_letter(path)
        assert payload["processo_id"] == "proc/123"
        assert payload["execucao_id"] == "exec-123"
        assert payload["erro"]["tipo"] == "ValueError"
        assert payload["erro"]["non_transient"] is True
        assert payload["contexto"]["origem"] == "teste"
        assert payload["metricas"]["tempo_total"] == 2.3
        assert payload["estado_pipeline"]["resultado_etapa1"]["numero_processo"] == "123"

    def test_salvar_dead_letter_ignores_transient_error(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(dlq, "ENABLE_DEAD_LETTER_QUEUE", True)
        APITimeoutError = type("APITimeoutError", (Exception,), {})
        path = dlq.salvar_dead_letter(
            APITimeoutError("timeout"),
            processo_id="proc-timeout",
            output_dir=tmp_path,
        )
        assert path is None
        assert list(tmp_path.glob("*.json")) == []
        assert list(tmp_path.glob("*.dlq")) == []


# ---------------------------------------------------------------------------
# New tests — DLQ encryption (SEC-005)
# ---------------------------------------------------------------------------


class TestDLQEncryption:
    """Validate encrypted DLQ save/read with Fernet."""

    def _make_estado(self) -> EstadoPipeline:
        return EstadoPipeline(
            metadata=MetadadosPipeline(execucao_id="exec-enc-001"),
            resultado_etapa1=ResultadoEtapa1(numero_processo="9999999-99.2024.8.16.0000"),
        )

    def test_salvar_dlq_criptografado_cria_arquivo_dlq(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Com DLQ_ENCRYPTION_KEY configurada, deve gerar arquivo .dlq binário."""
        key = cu.generate_key()
        monkeypatch.setattr(dlq, "ENABLE_DEAD_LETTER_QUEUE", True)
        monkeypatch.setattr(dlq, "DLQ_ENCRYPTION_ENABLED", True)
        monkeypatch.setattr(dlq, "DLQ_ENCRYPTION_KEY", key)

        path = dlq.salvar_dead_letter(
            RuntimeError("erro estrutural"),
            processo_id="enc-test",
            estado=self._make_estado(),
            output_dir=tmp_path,
        )

        assert path is not None
        assert path.suffix == ".dlq", "Arquivo criptografado deve ter extensão .dlq"
        # Content must NOT be valid JSON (it is encrypted binary)
        with pytest.raises(Exception):
            json.loads(path.read_bytes())

    def test_salvar_dlq_sem_chave_nao_persiste_arquivo(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Sem DLQ_ENCRYPTION_KEY, deve bloquear persistência para evitar texto plano."""
        monkeypatch.setattr(dlq, "ENABLE_DEAD_LETTER_QUEUE", True)
        monkeypatch.setattr(dlq, "DLQ_ENCRYPTION_ENABLED", False)
        monkeypatch.setattr(dlq, "DLQ_ENCRYPTION_KEY", "")

        path = dlq.salvar_dead_letter(
            RuntimeError("erro legacy"),
            processo_id="legacy-test",
            output_dir=tmp_path,
        )

        assert path is None
        assert list(tmp_path.glob("*")) == []

    def test_ler_dead_letter_decripta_arquivo_dlq(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Round-trip: salvar criptografado e ler de volta com ler_dead_letter."""
        key = cu.generate_key()
        monkeypatch.setattr(dlq, "ENABLE_DEAD_LETTER_QUEUE", True)
        monkeypatch.setattr(dlq, "DLQ_ENCRYPTION_ENABLED", True)
        monkeypatch.setattr(dlq, "DLQ_ENCRYPTION_KEY", key)

        path = dlq.salvar_dead_letter(
            ValueError("falha no pipeline"),
            processo_id="round-trip",
            estado=self._make_estado(),
            contexto={"teste": "criptografia"},
            output_dir=tmp_path,
        )

        # Now read back
        data = dlq.ler_dead_letter(path)
        assert data["processo_id"] == "round-trip"
        assert data["contexto"]["teste"] == "criptografia"
        assert data["erro"]["tipo"] == "ValueError"
        assert data["encrypted"] is True

    def test_ler_dead_letter_le_arquivo_json_legado(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """ler_dead_letter deve transportar arquivos .json legados sem criptografia."""
        monkeypatch.setattr(dlq, "ENABLE_DEAD_LETTER_QUEUE", True)
        monkeypatch.setattr(dlq, "DLQ_ENCRYPTION_ENABLED", False)
        monkeypatch.setattr(dlq, "DLQ_ENCRYPTION_KEY", "")

        path = tmp_path / "legacy.json"
        path.write_text(
            json.dumps(
                {
                    "encrypted": False,
                    "processo_id": "legado",
                    "erro": {"tipo": "ValueError"},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        data = dlq.ler_dead_letter(path)
        assert data["processo_id"] == "legado"

    def test_ler_dlq_sem_chave_lanca_value_error(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Tentar ler .dlq sem DLQ_ENCRYPTION_KEY deve falhar explicitamente."""
        key = cu.generate_key()
        monkeypatch.setattr(dlq, "ENABLE_DEAD_LETTER_QUEUE", True)
        monkeypatch.setattr(dlq, "DLQ_ENCRYPTION_ENABLED", True)
        monkeypatch.setattr(dlq, "DLQ_ENCRYPTION_KEY", key)

        path = dlq.salvar_dead_letter(
            ValueError("sem chave"),
            processo_id="no-key",
            output_dir=tmp_path,
        )

        # Now simulate environment without the key
        monkeypatch.setattr(dlq, "DLQ_ENCRYPTION_KEY", "")
        with pytest.raises(ValueError, match="DLQ_ENCRYPTION_KEY não está configurada"):
            dlq.ler_dead_letter(path)

    def test_ler_dlq_com_chave_errada_lanca_value_error(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Chave incorreta ao descriptografar deve levantar ValueError claro."""
        key1 = cu.generate_key()
        key2 = cu.generate_key()
        monkeypatch.setattr(dlq, "ENABLE_DEAD_LETTER_QUEUE", True)
        monkeypatch.setattr(dlq, "DLQ_ENCRYPTION_ENABLED", True)
        monkeypatch.setattr(dlq, "DLQ_ENCRYPTION_KEY", key1)

        path = dlq.salvar_dead_letter(
            ValueError("chave errada"),
            processo_id="wrong-key",
            output_dir=tmp_path,
        )

        # Try reading with wrong key
        monkeypatch.setattr(dlq, "DLQ_ENCRYPTION_KEY", key2)
        with pytest.raises(ValueError, match="chave incorreta"):
            dlq.ler_dead_letter(path)
