"""Tests for LLM client and prompt loading (Sprint 2.3 + 2.1 validation)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.cache_manager import CacheManager
from src.config import PROMPTS_DIR
from src.llm_client import (
    LLMError,
    LLMResponse,
    LLMTruncatedResponseError,
    TokenTracker,
    TokenUsage,
)


# --- 2.4.1: Prompt loading and section extraction ---


class TestPromptLoading:
    """Test that SYSTEM_PROMPT.md exists and has required sections."""

    def test_system_prompt_file_exists(self) -> None:
        prompt_path = PROMPTS_DIR / "SYSTEM_PROMPT.md"
        assert prompt_path.exists(), f"SYSTEM_PROMPT.md not found at {prompt_path}"

    def test_system_prompt_not_empty(self) -> None:
        prompt_path = PROMPTS_DIR / "SYSTEM_PROMPT.md"
        content = prompt_path.read_text(encoding="utf-8")
        assert len(content) > 100, "SYSTEM_PROMPT.md is too short"

    def test_system_prompt_has_etapa_sections(self) -> None:
        prompt_path = PROMPTS_DIR / "SYSTEM_PROMPT.md"
        content = prompt_path.read_text(encoding="utf-8")
        assert "Etapa 1" in content or "ETAPA 1" in content or "etapa 1" in content
        assert "Etapa 2" in content or "ETAPA 2" in content or "etapa 2" in content
        assert "Etapa 3" in content or "ETAPA 3" in content or "etapa 3" in content

    def test_system_prompt_has_markdown_headers(self) -> None:
        prompt_path = PROMPTS_DIR / "SYSTEM_PROMPT.md"
        content = prompt_path.read_text(encoding="utf-8")
        assert content.count("#") >= 3, "Expected markdown headers in prompt"


# --- 2.4.2: Invalid/incomplete prompt detection ---


class TestPromptValidation:
    """Test detection of invalid or incomplete prompts."""

    def test_empty_prompt_detected(self, tmp_path: Path) -> None:
        empty_file = tmp_path / "empty.md"
        empty_file.write_text("")
        content = empty_file.read_text()
        assert len(content) == 0

    def test_prompt_without_etapas_detected(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad_prompt.md"
        bad_file.write_text("# Prompt\n\nSome content without stages.")
        content = bad_file.read_text()
        has_etapas = all(
            f"Etapa {i}" in content or f"ETAPA {i}" in content
            for i in [1, 2, 3]
        )
        assert not has_etapas, "Bad prompt should not have all 3 etapas"


# --- Token tracking ---


class TestTokenTracker:
    """Test token usage tracking."""

    def test_empty_tracker(self) -> None:
        tracker = TokenTracker()
        assert tracker.total_tokens == 0
        assert tracker.total_calls == 0
        assert tracker.total_truncated_calls == 0
        assert tracker.average_latency_ms == 0.0

    def test_registers_usage(self) -> None:
        tracker = TokenTracker()
        tracker.registrar(
            TokenUsage(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                finish_reason="stop",
                latency_ms=100.0,
            )
        )
        tracker.registrar(
            TokenUsage(
                prompt_tokens=200,
                completion_tokens=100,
                total_tokens=300,
                finish_reason="length",
                latency_ms=300.0,
            )
        )

        assert tracker.total_prompt_tokens == 300
        assert tracker.total_completion_tokens == 150
        assert tracker.total_tokens == 450
        assert tracker.total_calls == 2
        assert tracker.total_truncated_calls == 1
        assert tracker.average_latency_ms == 200.0


# --- LLM client with mocks ---


class TestChamarLLM:
    """Test LLM call function with mocked OpenAI client."""

    @patch("src.llm_client._get_client")
    def test_successful_call(self, mock_get_client) -> None:
        # Mock OpenAI response
        mock_choice = MagicMock()
        mock_choice.finish_reason = "stop"
        mock_choice.message.content = "resposta do modelo"

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 50
        mock_usage.completion_tokens = 20
        mock_usage.total_tokens = 70

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        from src.llm_client import chamar_llm

        result = chamar_llm("system prompt", "user message")

        assert isinstance(result, LLMResponse)
        assert result.content == "resposta do modelo"
        assert result.tokens.total_tokens == 70
        assert result.finish_reason == "stop"

    @patch("src.llm_client._get_client")
    def test_truncated_response_retries_and_raises(self, mock_get_client, caplog) -> None:
        mock_choice = MagicMock()
        mock_choice.finish_reason = "length"
        mock_choice.message.content = "resposta truncada..."

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 50
        mock_usage.completion_tokens = 4096
        mock_usage.total_tokens = 4146

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        from src.llm_client import chamar_llm

        with caplog.at_level("WARNING"):
            with pytest.raises(LLMTruncatedResponseError):
                chamar_llm("system", "user")

        assert any("truncada" in r.message for r in caplog.records)
        assert mock_client.chat.completions.create.call_count >= 2

    @patch("src.llm_client._get_client")
    def test_cache_hit_when_signature_is_identical(self, mock_get_client, tmp_path: Path, monkeypatch) -> None:
        mock_choice = MagicMock()
        mock_choice.finish_reason = "stop"
        mock_choice.message.content = "resposta cacheável"

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 10
        mock_usage.completion_tokens = 5
        mock_usage.total_tokens = 15

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        from src.llm_client import chamar_llm_with_rate_limit

        cache = CacheManager(cache_dir=tmp_path / ".cache", ttl_hours=1)
        monkeypatch.setattr("src.llm_client.ENABLE_CACHING", True)
        monkeypatch.setattr("src.llm_client._get_cache_manager", lambda: cache)

        kwargs = {
            "model": "gpt-4o-mini",
            "max_tokens": 32,
            "cache_context": {
                "prompt_version": "v1",
                "prompt_hash_sha256": "abc123",
                "schema_version": "json_object",
            },
        }
        r1 = chamar_llm_with_rate_limit("sys", "user", **kwargs)
        r2 = chamar_llm_with_rate_limit("sys", "user", **kwargs)

        assert r1.content == "resposta cacheável"
        assert r2.content == "resposta cacheável"
        assert mock_client.chat.completions.create.call_count == 1

    @patch("src.llm_client._get_client")
    def test_cache_isolated_by_prompt_version(self, mock_get_client, tmp_path: Path, monkeypatch) -> None:
        mock_choice = MagicMock()
        mock_choice.finish_reason = "stop"
        mock_choice.message.content = "resposta com isolamento"

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 10
        mock_usage.completion_tokens = 5
        mock_usage.total_tokens = 15

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        from src.llm_client import chamar_llm_with_rate_limit

        cache = CacheManager(cache_dir=tmp_path / ".cache", ttl_hours=1)
        monkeypatch.setattr("src.llm_client.ENABLE_CACHING", True)
        monkeypatch.setattr("src.llm_client._get_cache_manager", lambda: cache)

        chamar_llm_with_rate_limit(
            "sys",
            "user",
            model="gpt-4o-mini",
            max_tokens=32,
            cache_context={
                "prompt_version": "v1",
                "prompt_hash_sha256": "abc123",
                "schema_version": "json_object",
            },
        )
        chamar_llm_with_rate_limit(
            "sys",
            "user",
            model="gpt-4o-mini",
            max_tokens=32,
            cache_context={
                "prompt_version": "v2",
                "prompt_hash_sha256": "abc123",
                "schema_version": "json_object",
            },
        )

        assert mock_client.chat.completions.create.call_count == 2


# --- 2.4.6: Integration test (slow, requires API key) ---


@pytest.mark.slow
class TestLLMIntegration:
    """Integration test with real OpenAI API. Run with: pytest -m slow"""

    def test_real_api_call(self) -> None:
        """Requires OPENAI_API_KEY to be set."""
        from src.config import OPENAI_API_KEY

        if not OPENAI_API_KEY:
            pytest.skip("OPENAI_API_KEY not set")

        from src.llm_client import chamar_llm

        result = chamar_llm(
            system_prompt="You are a helpful assistant.",
            user_message="Reply with exactly: OK",
            temperature=0.0,
            max_tokens=10,
        )

        assert result.content.strip()
        assert result.tokens.total_tokens > 0
        assert result.finish_reason == "stop"
