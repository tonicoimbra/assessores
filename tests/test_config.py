"""Tests for configuration loading (Sprint 1.2)."""

from src.config import (
    BASE_DIR,
    CLASSIFICATION_MANUAL_REVIEW_CONFIDENCE_THRESHOLD,
    CLASSIFICATION_MANUAL_REVIEW_MARGIN_THRESHOLD,
    CONTEXT_MIN_COVERAGE_RATIO,
    ENABLE_ETAPA1_CRITICAL_FIELDS_CONSENSUS,
    ENABLE_CLASSIFICATION_MANUAL_REVIEW,
    ENABLE_CONTEXT_COVERAGE_GATE,
    ENABLE_EXTRACTION_QUALITY_GATE,
    ENABLE_RETENTION_POLICY,
    ENABLE_WEB_DOWNLOAD_ACCESS_CONTROL,
    EXTRACTION_MAX_NOISE_RATIO,
    EXTRACTION_MIN_QUALITY_SCORE,
    LOG_LEVEL,
    MAX_LOG_MESSAGE_CHARS,
    MAX_TOKENS,
    OPENAI_MODEL,
    OUTPUTS_DIR,
    PROMPTS_DIR,
    RETENTION_CHECKPOINT_DAYS,
    RETENTION_DEAD_LETTER_DAYS,
    RETENTION_OUTPUT_DAYS,
    RETENTION_WEB_UPLOAD_DAYS,
    TEMPERATURE,
    WEB_DOWNLOAD_TOKEN_TTL_SECONDS,
    sanitize_log_text,
    setup_logging,
    validate_api_key,
    validate_environment_settings,
)


class TestConfigDefaults:
    """Test 1.5.5: configuration loading with defaults."""

    def test_openai_model_has_default(self) -> None:
        assert OPENAI_MODEL == "gpt-4o"

    def test_temperature_has_default(self) -> None:
        assert TEMPERATURE == 0.0

    def test_max_tokens_has_default(self) -> None:
        assert MAX_TOKENS == 2048

    def test_log_level_has_default(self) -> None:
        assert LOG_LEVEL in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

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

    def test_log_sanitization_masks_secrets(self) -> None:
        msg = sanitize_log_text("token sk-test_1234567890 and Bearer abcdefghijklmnopqrst")
        assert "sk-test_1234567890" not in msg
        assert "abcdefghijklmnopqrst" not in msg
        assert "[REDACTED_" in msg

    def test_log_sanitization_respects_max_length(self) -> None:
        raw = "x" * (MAX_LOG_MESSAGE_CHARS + 50)
        sanitized = sanitize_log_text(raw)
        assert len(sanitized) <= MAX_LOG_MESSAGE_CHARS + len(" ... [TRUNCATED]")

    def test_validate_environment_settings_detects_invalid_provider(self, monkeypatch) -> None:
        monkeypatch.setattr("src.config.LLM_PROVIDER", "invalid-provider")
        erros = validate_environment_settings()
        assert any("LLM_PROVIDER inválido" in e for e in erros)


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


class TestValidateApiKey:
    """Test API key validation."""

    def test_exits_when_key_missing(self, monkeypatch) -> None:
        monkeypatch.setattr("src.config.LLM_PROVIDER", "openai")
        monkeypatch.setattr("src.config.OPENAI_API_KEY", "")
        import pytest

        with pytest.raises(SystemExit):
            validate_api_key()
