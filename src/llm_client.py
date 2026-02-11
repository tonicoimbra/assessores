"""Reusable OpenAI API client with retry, token tracking, and timeout."""

import json
import logging
import time
from dataclasses import dataclass, field

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

from src.config import (
    ENABLE_CACHING,
    ENABLE_RATE_LIMITING,
    LLM_MAX_RETRIES,
    LLM_PROVIDER,
    LLM_TIMEOUT,
    MAX_TOKENS,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    TEMPERATURE,
    GOOGLE_API_KEY,
)

logger = logging.getLogger("copilot_juridico")


class LLMError(Exception):
    """Raised when LLM call fails after all retries."""


class LLMTruncatedResponseError(LLMError):
    """Raised when LLM response was truncated (finish_reason != 'stop')."""


@dataclass
class TokenUsage:
    """Token usage from a single LLM call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """Complete response from an LLM call."""

    content: str
    tokens: TokenUsage
    model: str
    finish_reason: str


@dataclass
class TokenTracker:
    """Aggregated token usage across multiple calls."""

    calls: list[TokenUsage] = field(default_factory=list)

    @property
    def total_prompt_tokens(self) -> int:
        return sum(t.prompt_tokens for t in self.calls)

    @property
    def total_completion_tokens(self) -> int:
        return sum(t.completion_tokens for t in self.calls)

    @property
    def total_tokens(self) -> int:
        return sum(t.total_tokens for t in self.calls)

    @property
    def total_calls(self) -> int:
        return len(self.calls)

    def registrar(self, usage: TokenUsage) -> None:
        """Register token usage from a call."""
        self.calls.append(usage)


# Global token tracker
token_tracker = TokenTracker()

# Global clients for reuse
_client = None
_google_client = None


def _get_client(model_name: str | None = None) -> OpenAI:
    """
    Get the appropriate OpenAI client based on the requested model or default provider.
    Handles distinct clients for Google (Gemini) and OpenRouter (DeepSeek/etc).
    """
    global _client, _google_client

    # 1. Google AI Studio (Direct)
    # Only use direct client if API Key is present AND model starts with google/
    if model_name and model_name.startswith("google/") and GOOGLE_API_KEY:
        if _google_client is None:
            _google_client = OpenAI(
                api_key=GOOGLE_API_KEY,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                timeout=LLM_TIMEOUT,
            )
        return _google_client

    # 2. OpenRouter (Default for everything else if configured)
    if LLM_PROVIDER == "openrouter":
        if _client is None:
            _client = OpenAI(
                api_key=OPENROUTER_API_KEY,
                base_url=OPENROUTER_BASE_URL,
                timeout=LLM_TIMEOUT,
                default_headers={
                    "HTTP-Referer": "https://copilot-juridico.tjpr.jus.br",
                    "X-Title": "Copilot Juridico TJPR",
                },
            )
        return _client

    # 3. OpenAI (Fallback)
    if _client is None:
        _client = OpenAI(api_key=OPENAI_API_KEY, timeout=LLM_TIMEOUT)
    return _client


# Import token manager and rate limiter (lazy to avoid circular imports)
def _get_token_manager():
    """Lazy import to avoid circular dependency."""
    from src.token_manager import token_manager
    return token_manager


def _get_rate_limiter():
    """Lazy import to avoid circular dependency."""
    from src.token_manager import rate_limiter
    return rate_limiter


def _get_cache_manager():
    """Lazy import to avoid circular dependency."""
    try:
        from src.cache_manager import cache_manager
        return cache_manager
    except ImportError:
        return None


def _chamar_llm_raw(
    system_prompt: str,
    user_message: str,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    model: str | None = None,
    response_format: dict | None = None,
) -> LLMResponse:
    """
    Call the LLM with retry and token tracking.

    Args:
        system_prompt: System message content.
        user_message: User message content.
        temperature: Override default temperature.
        max_tokens: Override default max tokens.
        model: Override default model.
        response_format: Optional response format (e.g. {"type": "json_object"}).

    Returns:
        LLMResponse with content, token usage, model, and finish_reason.

    Raises:
        LLMError: After all retries exhausted.
        LLMTruncatedResponseError: If response was truncated.
    """
    temp = temperature if temperature is not None else TEMPERATURE
    tokens = max_tokens or MAX_TOKENS
    modelo = model or OPENAI_MODEL
    
    # Get client based on the requested model (Google vs OpenRouter vs OpenAI)
    client = _get_client(model_name=modelo)

    # If using Google Direct, strip the 'google/' prefix from model name
    # The API expects 'gemini-2.0-flash-001', not 'google/gemini-2.0-flash-001'
    if modelo.startswith("google/") and GOOGLE_API_KEY:
        modelo = modelo.replace("google/", "")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    kwargs: dict = {
        "model": modelo,
        "messages": messages,
        "temperature": temp,
        "max_tokens": tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format

    last_error: Exception | None = None

    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            logger.info(
                "LLM chamada #%d: modelo=%s, temp=%.1f, max_tokens=%d",
                attempt, modelo, temp, tokens,
            )
            response = client.chat.completions.create(**kwargs)

            # Extract usage
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                completion_tokens=response.usage.completion_tokens if response.usage else 0,
                total_tokens=response.usage.total_tokens if response.usage else 0,
            )
            token_tracker.registrar(usage)

            choice = response.choices[0]
            finish_reason = choice.finish_reason or "unknown"
            content = choice.message.content or ""

            logger.info(
                "LLM resposta: %d prompt + %d completion = %d tokens, finish=%s",
                usage.prompt_tokens, usage.completion_tokens,
                usage.total_tokens, finish_reason,
            )

            # Warn on truncated response
            if finish_reason != "stop":
                logger.warning(
                    "⚠️  Resposta truncada (finish_reason=%s). "
                    "Considere aumentar max_tokens (atual: %d).",
                    finish_reason, tokens,
                )

            return LLMResponse(
                content=content,
                tokens=usage,
                model=modelo,
                finish_reason=finish_reason,
            )

        except RateLimitError as e:
            last_error = e
            wait = 2 ** attempt
            logger.warning(
                "Rate limit (429) na tentativa %d/%d. Aguardando %ds...",
                attempt, LLM_MAX_RETRIES, wait,
            )
            time.sleep(wait)

        except (APITimeoutError, APIConnectionError) as e:
            last_error = e
            wait = 2 ** attempt
            logger.warning(
                "Erro de conexão na tentativa %d/%d: %s. Aguardando %ds...",
                attempt, LLM_MAX_RETRIES, e, wait,
            )
            time.sleep(wait)

        except Exception as e:
            last_error = e
            logger.error("Erro inesperado na chamada LLM: %s", e)
            break

    raise LLMError(
        f"Falha na chamada LLM após {LLM_MAX_RETRIES} tentativas: {last_error}"
    )


def chamar_llm_with_rate_limit(
    system_prompt: str,
    user_message: str,
    **kwargs,
) -> LLMResponse:
    """
    Call LLM with budget check and rate limiting.

    This is the main interface that wraps _chamar_llm_raw with:
    - Token budget verification (prevents exceeding context limits)
    - Rate limit throttling (prevents 429 errors)
    - Cache support (when enabled)

    Args:
        system_prompt: System message content.
        user_message: User message content.
        **kwargs: Additional arguments passed to _chamar_llm_raw.

    Returns:
        LLMResponse with content, token usage, model, and finish_reason.

    Raises:
        TokenBudgetExceededError: If budget is insufficient.
        LLMError: After all retries exhausted.
    """
    modelo = kwargs.get("model") or OPENAI_MODEL
    token_manager = _get_token_manager()

    # Estimate tokens before calling API
    estimated_prompt = token_manager.estimate_tokens(system_prompt + user_message, modelo)
    estimated_total = estimated_prompt + (kwargs.get("max_tokens") or MAX_TOKENS)

    # Check rate limit if enabled
    if ENABLE_RATE_LIMITING:
        rate_limiter = _get_rate_limiter()

        if not rate_limiter.can_proceed(modelo, estimated_total):
            wait_time = rate_limiter.wait_time_until_available(modelo, estimated_total)
            logger.warning(
                "⏳ Limite de taxa próximo para %s. Aguardando %.1fs para evitar erro 429...",
                modelo, wait_time,
            )
            time.sleep(wait_time)

    # Check cache if enabled
    use_cache = kwargs.pop("use_cache", True) and ENABLE_CACHING
    if use_cache:
        cache_manager = _get_cache_manager()
        if cache_manager:
            cache_key = cache_manager._hash_text(system_prompt + user_message)
            cached = cache_manager.get(cache_key, category="llm_calls")

            if cached:
                logger.info("💾 Cache hit — pulando chamada LLM para economizar tokens e custo")
                tokens_data = cached.get("tokens", {})
                if isinstance(tokens_data, dict):
                    cached["tokens"] = TokenUsage(**tokens_data)
                return LLMResponse(**cached)

    # Call raw LLM function
    response = _chamar_llm_raw(system_prompt, user_message, **kwargs)

    # Register usage for rate limiting
    if ENABLE_RATE_LIMITING:
        rate_limiter = _get_rate_limiter()
        rate_limiter.add_usage(modelo, response.tokens.total_tokens)

    # Store in cache if enabled
    if use_cache:
        cache_manager = _get_cache_manager()
        if cache_manager:
            cache_manager.set(
                cache_manager._hash_text(system_prompt + user_message),
                response.model_dump() if hasattr(response, "model_dump") else {
                    "content": response.content,
                    "tokens": {
                        "prompt_tokens": response.tokens.prompt_tokens,
                        "completion_tokens": response.tokens.completion_tokens,
                        "total_tokens": response.tokens.total_tokens,
                    },
                    "model": response.model,
                    "finish_reason": response.finish_reason,
                },
                category="llm_calls",
            )

    return response


# Default interface (with all enhancements)
chamar_llm = chamar_llm_with_rate_limit


def chamar_llm_json(
    system_prompt: str,
    user_message: str,
    **kwargs,
) -> dict:
    """
    Call LLM expecting a JSON response. Parses the JSON automatically.

    Returns:
        Parsed JSON as dict.

    Raises:
        LLMError: If response is not valid JSON.
    """
    response = chamar_llm_with_rate_limit(
        system_prompt,
        user_message,
        response_format={"type": "json_object"},
        **kwargs,
    )

    try:
        return json.loads(response.content)
    except json.JSONDecodeError as e:
        raise LLMError(f"Resposta LLM não é JSON válido: {e}") from e


# Legacy interface (for backward compatibility, bypasses enhancements)
def chamar_llm_legacy(
    system_prompt: str,
    user_message: str,
    **kwargs,
) -> LLMResponse:
    """
    Legacy LLM interface without budget/rate limiting/cache.

    Only use this if you need to bypass the robust architecture features.
    Most code should use chamar_llm() instead.
    """
    return _chamar_llm_raw(system_prompt, user_message, **kwargs)
