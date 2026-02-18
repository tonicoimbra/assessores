"""Tests for configuration loading (Sprint 1.2)."""

from src.config import (
    BASE_DIR,
    ENABLE_EXTRACTION_QUALITY_GATE,
    EXTRACTION_MAX_NOISE_RATIO,
    EXTRACTION_MIN_QUALITY_SCORE,
    LOG_LEVEL,
    MAX_TOKENS,
    OPENAI_MODEL,
    OUTPUTS_DIR,
    PROMPTS_DIR,
    TEMPERATURE,
    setup_logging,
    validate_api_key,
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
