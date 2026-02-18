"""Tests for dead-letter queue persistence of non-transient failures."""

from __future__ import annotations

import json
from pathlib import Path

import src.dead_letter_queue as dlq
from src.models import EstadoPipeline, MetadadosPipeline, ResultadoEtapa1


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
        monkeypatch.setattr(dlq, "ENABLE_DEAD_LETTER_QUEUE", True)
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
        payload = json.loads(path.read_text(encoding="utf-8"))
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
