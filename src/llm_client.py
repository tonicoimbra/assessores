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

logger = logging.getLogger("assessor_ai")

ChatMessage = dict[str, str]


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
    finish_reason: str = "unknown"
    latency_ms: float = 0.0


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

    @property
    def total_truncated_calls(self) -> int:
        return sum(1 for t in self.calls if (t.finish_reason or "") != "stop")

    @property
    def average_latency_ms(self) -> float:
        if not self.calls:
            return 0.0
        return sum(float(t.latency_ms or 0.0) for t in self.calls) / len(self.calls)

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


def _prepare_messages(
    system_prompt: str | None = None,
    user_message: str | None = None,
    messages: list[ChatMessage] | None = None,
) -> list[ChatMessage]:
    """Normalize chat messages, preserving backward compatibility."""
    if messages:
        prepared: list[ChatMessage] = []
        for msg in messages:
            role = str(msg.get("role", "user")).strip().lower()
            content = str(msg.get("content", "")).strip()
            if not content:
                continue
            if role not in {"system", "developer", "user", "assistant"}:
                role = "user"
            prepared.append({"role": role, "content": content})
        if prepared:
            return prepared

    # Backward-compatible mode
    sys_prompt = (system_prompt or "").strip()
    usr_msg = (user_message or "").strip()
    if not sys_prompt and not usr_msg:
        raise LLMError("Nenhuma mensagem fornecida para chamada LLM.")

    normalized: list[ChatMessage] = []
    if sys_prompt:
        normalized.append({"role": "system", "content": sys_prompt})
    if usr_msg:
        normalized.append({"role": "user", "content": usr_msg})
    return normalized


def _messages_to_text(messages: list[ChatMessage]) -> str:
    """Serialize messages into deterministic text for token estimate/cache."""
    return "\n".join(f"[{m['role']}]\n{m['content']}" for m in messages)


def _extract_prompt_and_schema_cache_context(
    prepared_messages: list[ChatMessage],
    cache_context: dict[str, object],
    response_format: dict | None,
) -> tuple[str, str, str]:
    """Resolve prompt/schema identifiers used for cache isolation."""
    prompt_version = str(cache_context.get("prompt_version") or "").strip()
    prompt_hash = str(cache_context.get("prompt_hash_sha256") or "").strip()

    if not prompt_hash:
        prompt_seed = "\n".join(
            m.get("content", "")
            for m in prepared_messages
            if m.get("role") in {"system", "developer"}
        ).strip()
        if prompt_seed:
            cache_manager = _get_cache_manager()
            if cache_manager:
                prompt_hash = cache_manager._hash_text(prompt_seed)

    if response_format and isinstance(response_format, dict):
        schema_version = str(response_format.get("type") or "json_object").strip()
    else:
        schema_version = str(cache_context.get("schema_version") or "raw").strip()

    return prompt_version, prompt_hash, schema_version


def _chamar_llm_raw(
    system_prompt: str | None = None,
    user_message: str | None = None,
    *,
    messages: list[ChatMessage] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    model: str | None = None,
    response_format: dict | None = None,
) -> LLMResponse:
    """
    Call the LLM with retry and token tracking.

    Args:
        system_prompt: System message content (legacy mode).
        user_message: User message content (legacy mode).
        messages: Full list of chat messages (preferred mode).
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

    prepared_messages = _prepare_messages(
        system_prompt=system_prompt,
        user_message=user_message,
        messages=messages,
    )

    kwargs: dict = {
        "model": modelo,
        "messages": prepared_messages,
        "temperature": temp,
        "max_tokens": tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format

    last_error: Exception | None = None

    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            logger.info(
                "LLM chamada #%d: modelo=%s, temp=%.1f, max_tokens=%d, mensagens=%d",
                attempt, modelo, temp, tokens, len(prepared_messages),
            )
            t0 = time.perf_counter()
            response = client.chat.completions.create(**kwargs)
            latency_ms = (time.perf_counter() - t0) * 1000

            # Extract usage
            choice = response.choices[0]
            finish_reason = choice.finish_reason or "unknown"
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                completion_tokens=response.usage.completion_tokens if response.usage else 0,
                total_tokens=response.usage.total_tokens if response.usage else 0,
                finish_reason=finish_reason,
                latency_ms=round(latency_ms, 2),
            )
            token_tracker.registrar(usage)

            content = choice.message.content or ""

            logger.info(
                "LLM resposta: %d prompt + %d completion = %d tokens, finish=%s",
                usage.prompt_tokens, usage.completion_tokens,
                usage.total_tokens, finish_reason,
            )

            # Warn on truncated response
            if finish_reason != "stop":
                msg = (
                    "Resposta truncada "
                    f"(finish_reason={finish_reason}, max_tokens={tokens})"
                )
                logger.warning("⚠️  %s", msg)
                if attempt < LLM_MAX_RETRIES:
                    # Increase completion budget progressively and retry.
                    tokens = min(tokens + max(256, tokens // 2), 8192)
                    kwargs["max_tokens"] = tokens
                    logger.warning(
                        "🔁 Repetindo chamada após truncamento com max_tokens=%d "
                        "(tentativa %d/%d).",
                        tokens, attempt + 1, LLM_MAX_RETRIES,
                    )
                    continue
                raise LLMTruncatedResponseError(msg)

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

    if isinstance(last_error, LLMTruncatedResponseError):
        raise last_error

    raise LLMError(
        f"Falha na chamada LLM após {LLM_MAX_RETRIES} tentativas: {last_error}"
    )


def chamar_llm_with_rate_limit(
    system_prompt: str | None = None,
    user_message: str | None = None,
    *,
    messages: list[ChatMessage] | None = None,
    **kwargs,
) -> LLMResponse:
    """
    Call LLM with budget check and rate limiting.

    This is the main interface that wraps _chamar_llm_raw with:
    - Token budget verification (prevents exceeding context limits)
    - Rate limit throttling (prevents 429 errors)
    - Cache support (when enabled)

    Args:
        system_prompt: System message content (legacy mode).
        user_message: User message content (legacy mode).
        messages: Full list of chat messages (preferred mode).
        **kwargs: Additional arguments passed to _chamar_llm_raw.

    Returns:
        LLMResponse with content, token usage, model, and finish_reason.

    Raises:
        TokenBudgetExceededError: If budget is insufficient.
        LLMError: After all retries exhausted.
    """
    modelo = kwargs.get("model") or OPENAI_MODEL
    token_manager = _get_token_manager()
    prepared_messages = _prepare_messages(
        system_prompt=system_prompt,
        user_message=user_message,
        messages=messages,
    )
    prompt_blob = _messages_to_text(prepared_messages)

    # Estimate tokens before calling API
    estimated_prompt = token_manager.estimate_tokens(prompt_blob, modelo)
    estimated_total = estimated_prompt + (kwargs.get("max_tokens") or MAX_TOKENS)
    logger.info(
        "Token estimate antes da chamada: modelo=%s, prompt=%d, total_previsto=%d",
        modelo, estimated_prompt, estimated_total,
    )

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
    cache_context = kwargs.pop("cache_context", {}) or {}
    if not isinstance(cache_context, dict):
        cache_context = {"value": str(cache_context)}

    response_format = kwargs.get("response_format")
    use_cache = kwargs.pop("use_cache", True) and ENABLE_CACHING
    cache_identity: tuple[str, str] | None = None
    if use_cache:
        cache_manager = _get_cache_manager()
        if cache_manager:
            prompt_version, prompt_hash, schema_version = _extract_prompt_and_schema_cache_context(
                prepared_messages,
                cache_context,
                response_format,
            )

            category, cache_key = cache_manager.build_multilevel_cache_identity(
                model=modelo,
                input_payload=prepared_messages,
                prompt_version=prompt_version,
                prompt_hash=prompt_hash,
                schema_version=schema_version,
                temperature=kwargs.get("temperature"),
                max_tokens=kwargs.get("max_tokens") or MAX_TOKENS,
                provider=LLM_PROVIDER,
                extra={
                    "response_format": response_format,
                    "cache_context": cache_context,
                },
            )
            cache_identity = (category, cache_key)
            cached = cache_manager.get(cache_key, category=category)

            if cached:
                logger.info("💾 Cache hit — pulando chamada LLM para economizar tokens e custo")
                tokens_data = cached.get("tokens", {})
                if isinstance(tokens_data, dict):
                    cached["tokens"] = TokenUsage(**tokens_data)
                return LLMResponse(**cached)

    # Call raw LLM function
    response = _chamar_llm_raw(
        messages=prepared_messages,
        system_prompt=system_prompt,
        user_message=user_message,
        **kwargs,
    )

    # Register usage for rate limiting
    if ENABLE_RATE_LIMITING:
        rate_limiter = _get_rate_limiter()
        rate_limiter.add_usage(modelo, response.tokens.total_tokens)

    # Store in cache if enabled
    if use_cache:
        cache_manager = _get_cache_manager()
        if cache_manager:
            category, cache_key = cache_identity or cache_manager.build_multilevel_cache_identity(
                model=modelo,
                input_payload=prepared_messages,
                prompt_version="",
                prompt_hash="",
                schema_version="raw",
                temperature=kwargs.get("temperature"),
                max_tokens=kwargs.get("max_tokens") or MAX_TOKENS,
                provider=LLM_PROVIDER,
                extra={"response_format": response_format, "cache_context": cache_context},
            )
            cache_manager.set(
                cache_key,
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
                category=category,
            )

    return response


# Default interface (with all enhancements)
chamar_llm = chamar_llm_with_rate_limit


def chamar_llm_json(
    system_prompt: str | None = None,
    user_message: str | None = None,
    *,
    messages: list[ChatMessage] | None = None,
    response_schema: dict | None = None,
    schema_name: str = "structured_response",
    schema_strict: bool = True,
    **kwargs,
) -> dict:
    """
    Call LLM expecting a JSON response. Parses the JSON automatically.

    Returns:
        Parsed JSON as dict.

    Raises:
        LLMError: If response is not valid JSON.
    """
    response_format: dict = {"type": "json_object"}
    if isinstance(response_schema, dict) and response_schema:
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": bool(schema_strict),
                "schema": response_schema,
            },
        }

    try:
        response = chamar_llm_with_rate_limit(
            system_prompt=system_prompt,
            user_message=user_message,
            messages=messages,
            response_format=response_format,
            **kwargs,
        )
    except Exception as e:
        raw_message = str(e).lower()
        unsupported_schema = (
            bool(response_schema)
            and "schema" in raw_message
            and ("unsupported" in raw_message or "response_format" in raw_message)
        )
        if not unsupported_schema:
            raise

        logger.warning(
            "response_format=json_schema não suportado pelo provider/modelo atual; "
            "fallback para json_object. erro=%s",
            e,
        )
        response = chamar_llm_with_rate_limit(
            system_prompt=system_prompt,
            user_message=user_message,
            messages=messages,
            response_format={"type": "json_object"},
            **kwargs,
        )

    try:
        return json.loads(response.content)
    except json.JSONDecodeError as e:
        raise LLMError(f"Resposta LLM não é JSON válido: {e}") from e


# Legacy interface (for backward compatibility, bypasses enhancements)
def chamar_llm_legacy(
    system_prompt: str | None = None,
    user_message: str | None = None,
    *,
    messages: list[ChatMessage] | None = None,
    **kwargs,
) -> LLMResponse:
    """
    Legacy LLM interface without budget/rate limiting/cache.

    Only use this if you need to bypass the robust architecture features.
    Most code should use chamar_llm() instead.
    """
    return _chamar_llm_raw(
        system_prompt=system_prompt,
        user_message=user_message,
        messages=messages,
        **kwargs,
    )
