"""Tests for configuration loading (Sprint 1.2)."""

import logging

from src.config import (
    BASE_DIR,
    CLASSIFICATION_MANUAL_REVIEW_CONFIDENCE_THRESHOLD,
    CLASSIFICATION_MANUAL_REVIEW_MARGIN_THRESHOLD,
    CACHE_PURGE_ON_START,
    CACHE_TTL_SECONDS,
    CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    CIRCUIT_BREAKER_RESET_TIMEOUT,
    CONFIDENCE_WEIGHT_ETAPA1,
    CONFIDENCE_WEIGHT_ETAPA2,
    CONFIDENCE_WEIGHT_ETAPA3,
    CONTEXT_MIN_COVERAGE_RATIO,
    ENABLE_ETAPA1_CRITICAL_FIELDS_CONSENSUS,
    ENABLE_CLASSIFICATION_MANUAL_REVIEW,
    ENABLE_CONTEXT_COVERAGE_GATE,
    ENABLE_EXTRACTION_QUALITY_GATE,
    ENABLE_RETENTION_POLICY,
    ENABLE_WEB_DOWNLOAD_ACCESS_CONTROL,
    EXTRACTION_MAX_NOISE_RATIO,
    EXTRACTION_MIN_QUALITY_SCORE,
    IDEMPOTENCY_BACKEND,
    LOG_LEVEL,
    LOG_SANITIZE_LEVEL,
    MAX_LOG_MESSAGE_CHARS,
    MAX_TOKENS,
    MAX_TOKENS_CEILING,
    OPENAI_MODEL,
    OUTPUTS_DIR,
    PROMPTS_DIR,
    RETENTION_CHECKPOINT_DAYS,
    RETENTION_DEAD_LETTER_DAYS,
    RETENTION_OUTPUT_DAYS,
    RETENTION_WEB_UPLOAD_DAYS,
    SensitiveDataFilter,
    TEMPERATURE,
    WEB_DOWNLOAD_TOKEN_TTL_SECONDS,
    WEB_AUTH_ENABLED,
    UPLOAD_RATE_LIMIT_PER_MINUTE,
    sanitize_log_text,
    setup_logging,
    validate_api_key,
    validate_environment_settings,
)


class TestConfigDefaults:
    """Test 1.5.5: configuration loading with defaults."""

    def test_openai_model_has_default(self) -> None:
        assert isinstance(OPENAI_MODEL, str)
        assert len(OPENAI_MODEL) > 3

    def test_temperature_has_default(self) -> None:
        assert TEMPERATURE == 0.0

    def test_max_tokens_has_default(self) -> None:
        assert MAX_TOKENS == 2048

    def test_max_tokens_ceiling_default(self) -> None:
        assert MAX_TOKENS_CEILING >= MAX_TOKENS

    def test_circuit_breaker_defaults(self) -> None:
        assert CIRCUIT_BREAKER_FAILURE_THRESHOLD >= 1
        assert CIRCUIT_BREAKER_RESET_TIMEOUT >= 1

    def test_idempotency_backend_default(self) -> None:
        assert IDEMPOTENCY_BACKEND in {"memory", "sqlite"}

    def test_log_level_has_default(self) -> None:
        assert LOG_LEVEL in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

    def test_log_sanitize_level_has_default(self) -> None:
        assert LOG_SANITIZE_LEVEL in ("full", "partial", "off")

    def test_extraction_quality_gate_defaults(self) -> None:
        assert isinstance(ENABLE_EXTRACTION_QUALITY_GATE, bool)
        assert 0.0 <= EXTRACTION_MIN_QUALITY_SCORE <= 1.0
        assert 0.0 <= EXTRACTION_MAX_NOISE_RATIO <= 1.0

    def test_classification_manual_review_defaults(self) -> None:
        assert isinstance(ENABLE_CLASSIFICATION_MANUAL_REVIEW, bool)
        assert 0.0 <= CLASSIFICATION_MANUAL_REVIEW_CONFIDENCE_THRESHOLD <= 1.0
        assert 0.0 <= CLASSIFICATION_MANUAL_REVIEW_MARGIN_THRESHOLD <= 1.0

    def test_context_coverage_gate_defaults(self) -> None:
        assert isinstance(ENABLE_CONTEXT_COVERAGE_GATE, bool)
        assert 0.0 <= CONTEXT_MIN_COVERAGE_RATIO <= 1.0

    def test_confidence_weight_defaults(self) -> None:
        assert 0.0 <= CONFIDENCE_WEIGHT_ETAPA1 <= 1.0
        assert 0.0 <= CONFIDENCE_WEIGHT_ETAPA2 <= 1.0
        assert 0.0 <= CONFIDENCE_WEIGHT_ETAPA3 <= 1.0
        assert abs(
            CONFIDENCE_WEIGHT_ETAPA1
            + CONFIDENCE_WEIGHT_ETAPA2
            + CONFIDENCE_WEIGHT_ETAPA3
            - 1.0
        ) <= 0.001

    def test_etapa1_consensus_flag_default(self) -> None:
        assert isinstance(ENABLE_ETAPA1_CRITICAL_FIELDS_CONSENSUS, bool)

    def test_retention_defaults(self) -> None:
        assert isinstance(ENABLE_RETENTION_POLICY, bool)
        assert RETENTION_OUTPUT_DAYS >= 1
        assert RETENTION_CHECKPOINT_DAYS >= 1
        assert RETENTION_WEB_UPLOAD_DAYS >= 1
        assert RETENTION_DEAD_LETTER_DAYS >= 1

    def test_web_download_access_control_defaults(self) -> None:
        assert isinstance(ENABLE_WEB_DOWNLOAD_ACCESS_CONTROL, bool)
        assert WEB_DOWNLOAD_TOKEN_TTL_SECONDS >= 60

    def test_web_auth_defaults(self) -> None:
        assert isinstance(WEB_AUTH_ENABLED, bool)
        assert UPLOAD_RATE_LIMIT_PER_MINUTE >= 1

    def test_cache_retention_defaults(self) -> None:
        assert CACHE_TTL_SECONDS >= 60
        assert isinstance(CACHE_PURGE_ON_START, bool)

    def test_log_sanitization_masks_secrets(self) -> None:
        msg = sanitize_log_text("token sk-test_1234567890 and Bearer abcdefghijklmnopqrst")
        assert "sk-test_1234567890" not in msg
        assert "abcdefghijklmnopqrst" not in msg
        assert "[REDACTED_" in msg

    def test_log_sanitization_respects_max_length(self) -> None:
        raw = "x" * (MAX_LOG_MESSAGE_CHARS + 50)
        sanitized = sanitize_log_text(raw)
        assert len(sanitized) <= MAX_LOG_MESSAGE_CHARS + len(" ... [TRUNCATED]")

    def test_log_sanitization_masks_pii(self) -> None:
        msg = sanitize_log_text(
            "Processo 1234567-89.2024.8.16.0001 CPF 123.456.789-09 CNPJ 12.345.678/0001-99"
        )
        assert "1234567-89.2024.8.16.0001" not in msg
        assert "123.456.789-09" not in msg
        assert "12.345.678/0001-99" not in msg
        assert "[REDACTED_PROCESSO]" in msg
        assert "[REDACTED_CPF]" in msg
        assert "[REDACTED_CNPJ]" in msg

    def test_log_sanitization_masks_party_names_on_full(self, monkeypatch) -> None:
        monkeypatch.setattr("src.config.LOG_SANITIZE_LEVEL", "full")
        msg = sanitize_log_text("Recorrente: João da Silva")
        assert "João da Silva" not in msg
        assert "[REDACTED_PARTY_NAME]" in msg

    def test_log_sanitization_off_keeps_original_text(self, monkeypatch) -> None:
        monkeypatch.setattr("src.config.LOG_SANITIZE_LEVEL", "off")
        raw = "Recorrente: João da Silva CPF 123.456.789-09"
        assert sanitize_log_text(raw) == raw

    def test_validate_environment_settings_detects_invalid_provider(self, monkeypatch) -> None:
        monkeypatch.setattr("src.config.LLM_PROVIDER", "invalid-provider")
        erros = validate_environment_settings()
        assert any("LLM_PROVIDER inválido" in e for e in erros)

    def test_validate_environment_settings_requires_web_auth_token(self, monkeypatch) -> None:
        monkeypatch.setattr("src.config.WEB_AUTH_ENABLED", True)
        monkeypatch.setattr("src.config.WEB_AUTH_TOKEN", "")
        erros = validate_environment_settings()
        assert any("WEB_AUTH_TOKEN" in e for e in erros)

    def test_validate_environment_settings_requires_confidence_weight_sum_1(self, monkeypatch) -> None:
        monkeypatch.setattr("src.config.CONFIDENCE_WEIGHT_ETAPA1", 0.60)
        monkeypatch.setattr("src.config.CONFIDENCE_WEIGHT_ETAPA2", 0.30)
        monkeypatch.setattr("src.config.CONFIDENCE_WEIGHT_ETAPA3", 0.30)
        erros = validate_environment_settings()
        assert any("CONFIDENCE_WEIGHT_ETAPA1 + CONFIDENCE_WEIGHT_ETAPA2 + CONFIDENCE_WEIGHT_ETAPA3" in e for e in erros)

    def test_validate_environment_settings_warns_when_ceiling_is_below_max_tokens(
        self,
        monkeypatch,
        caplog,
    ) -> None:
        monkeypatch.setattr("src.config.MAX_TOKENS", 4096)
        monkeypatch.setattr("src.config.MAX_TOKENS_CEILING", 2048)
        with caplog.at_level(logging.WARNING, logger="assessor_ai"):
            erros = validate_environment_settings()
        assert erros == []
        assert any("MAX_TOKENS_CEILING" in r.message for r in caplog.records)

    def test_validate_environment_settings_requires_valid_circuit_breaker_params(
        self,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr("src.config.CIRCUIT_BREAKER_FAILURE_THRESHOLD", 0)
        monkeypatch.setattr("src.config.CIRCUIT_BREAKER_RESET_TIMEOUT", 0)
        erros = validate_environment_settings()
        assert any("CIRCUIT_BREAKER_FAILURE_THRESHOLD" in e for e in erros)
        assert any("CIRCUIT_BREAKER_RESET_TIMEOUT" in e for e in erros)

    def test_validate_environment_settings_requires_valid_idempotency_backend(
        self,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr("src.config.IDEMPOTENCY_BACKEND", "redis")
        erros = validate_environment_settings()
        assert any("IDEMPOTENCY_BACKEND" in e for e in erros)


class TestConfigPaths:
    """Test that project paths are resolved correctly."""

    def test_base_dir_exists(self) -> None:
        assert BASE_DIR.exists()

    def test_prompts_dir_is_under_base(self) -> None:
        assert str(PROMPTS_DIR).startswith(str(BASE_DIR))

    def test_outputs_dir_is_under_base(self) -> None:
        assert str(OUTPUTS_DIR).startswith(str(BASE_DIR))


class TestSetupLogging:
    """Test logging configuration."""

    def test_returns_logger(self) -> None:
        logger = setup_logging()
        assert logger.name == "assessor_ai"

    def test_logger_has_handler(self) -> None:
        logger = setup_logging()
        assert len(logger.handlers) > 0

    def test_setup_logging_applies_sensitive_filter_to_existing_handlers(self) -> None:
        logger = setup_logging()
        extra_handler = logging.StreamHandler()
        logger.addHandler(extra_handler)
        try:
            assert not any(isinstance(f, SensitiveDataFilter) for f in extra_handler.filters)
            setup_logging()
            assert any(isinstance(f, SensitiveDataFilter) for f in extra_handler.filters)
        finally:
            logger.removeHandler(extra_handler)
            extra_handler.close()


class TestValidateApiKey:
    """Test API key validation."""

    def test_exits_when_key_missing(self, monkeypatch) -> None:
        monkeypatch.setattr("src.config.LLM_PROVIDER", "openai")
        monkeypatch.setattr("src.config.OPENAI_API_KEY", "")
        import pytest

        with pytest.raises(SystemExit):
            validate_api_key()
