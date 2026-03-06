"""Reusable OpenAI API client with retry, token tracking, and timeout."""

import json
import logging
import sqlite3
import time
from enum import Enum
from hashlib import sha256
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from collections.abc import Callable
from typing import Any

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError

from src.config import (
    ENABLE_CACHING,
    ENABLE_RATE_LIMITING,
    LLM_MAX_RETRIES,
    LLM_PROVIDER,
    LLM_TIMEOUT,
    CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    CIRCUIT_BREAKER_RESET_TIMEOUT,
    IDEMPOTENCY_BACKEND,
    IDEMPOTENCY_SQLITE_PATH,
    MAX_TOKENS,
    MAX_TOKENS_CEILING,
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


class CircuitBreakerState(str, Enum):
    """Circuit breaker finite states."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitBreaker:
    """Simple circuit breaker for repeated LLM API failures."""

    failure_threshold: int
    reset_timeout_seconds: int
    time_fn: Callable[[], float] = time.monotonic
    state: CircuitBreakerState = CircuitBreakerState.CLOSED
    consecutive_failures: int = 0
    opened_at: float | None = None
    circuit_opens: int = 0
    circuit_half_opens: int = 0
    _lock: Lock = field(default_factory=Lock)

    def _log_event(self, event: str, **extra: Any) -> None:
        payload: dict[str, Any] = {
            "event": event,
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "failure_threshold": self.failure_threshold,
            "reset_timeout_seconds": self.reset_timeout_seconds,
            "circuit_opens": self.circuit_opens,
            "circuit_half_opens": self.circuit_half_opens,
        }
        payload.update(extra)
        logger.warning("CIRCUIT_BREAKER %s", json.dumps(payload, ensure_ascii=False, sort_keys=True))

    def _transition_to_open(self, *, reason: str, error: str) -> None:
        self.state = CircuitBreakerState.OPEN
        self.opened_at = self.time_fn()
        self.consecutive_failures = 0
        self.circuit_opens += 1
        self._log_event("circuit_opened", reason=reason, error=error)

    def allow_request(self) -> tuple[bool, float]:
        """Return whether request is allowed and retry-after seconds if blocked."""
        with self._lock:
            if self.state != CircuitBreakerState.OPEN:
                return True, 0.0

            if self.opened_at is None:
                self.opened_at = self.time_fn()

            elapsed = max(0.0, self.time_fn() - self.opened_at)
            if elapsed >= float(self.reset_timeout_seconds):
                self.state = CircuitBreakerState.HALF_OPEN
                self.circuit_half_opens += 1
                self._log_event("circuit_half_open", elapsed_seconds=round(elapsed, 3))
                return True, 0.0

            retry_after = max(0.0, float(self.reset_timeout_seconds) - elapsed)
            return False, retry_after

    def on_success(self) -> None:
        """Record successful call, resetting breaker to CLOSED."""
        with self._lock:
            previous_state = self.state
            self.state = CircuitBreakerState.CLOSED
            self.consecutive_failures = 0
            self.opened_at = None
            if previous_state != CircuitBreakerState.CLOSED:
                self._log_event("circuit_closed", previous_state=previous_state.value)

    def on_failure(self, error: Exception) -> None:
        """Record failed call, opening circuit when threshold is reached."""
        with self._lock:
            error_text = f"{type(error).__name__}: {error}"

            if self.state == CircuitBreakerState.HALF_OPEN:
                self._transition_to_open(reason="half_open_failure", error=error_text)
                return

            if self.state == CircuitBreakerState.OPEN:
                return

            self.consecutive_failures += 1
            if self.consecutive_failures >= int(self.failure_threshold):
                self._transition_to_open(reason="failure_threshold_reached", error=error_text)


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
_IDEMPOTENCY_CACHE: dict[str, dict[str, Any]] = {}
_IDEMPOTENCY_TTL_SECONDS = 24 * 3600
_idempotency_backend: Any | None = None
_idempotency_backend_lock = Lock()
circuit_breaker = CircuitBreaker(
    failure_threshold=max(1, int(CIRCUIT_BREAKER_FAILURE_THRESHOLD)),
    reset_timeout_seconds=max(1, int(CIRCUIT_BREAKER_RESET_TIMEOUT)),
)


def _serialize_response(response: LLMResponse) -> dict[str, Any]:
    """Serialize LLMResponse to deterministic dict for idempotency cache."""
    return {
        "content": response.content,
        "tokens": {
            "prompt_tokens": response.tokens.prompt_tokens,
            "completion_tokens": response.tokens.completion_tokens,
            "total_tokens": response.tokens.total_tokens,
            "finish_reason": response.tokens.finish_reason,
            "latency_ms": response.tokens.latency_ms,
        },
        "model": response.model,
        "finish_reason": response.finish_reason,
    }


def _deserialize_response(payload: dict[str, Any]) -> LLMResponse:
    """Deserialize idempotency/cache payload into LLMResponse."""
    tokens_payload = payload.get("tokens")
    if isinstance(tokens_payload, dict):
        tokens = TokenUsage(**tokens_payload)
    else:
        tokens = TokenUsage()
    return LLMResponse(
        content=str(payload.get("content") or ""),
        tokens=tokens,
        model=str(payload.get("model") or ""),
        finish_reason=str(payload.get("finish_reason") or "unknown"),
    )


def _build_idempotency_fingerprint(
    *,
    model: str,
    messages: list[ChatMessage],
    max_tokens: int | None,
    temperature: float | None,
    response_format: dict | None,
) -> str:
    """Create deterministic request fingerprint used for request_id idempotency."""
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "response_format": response_format or {},
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return sha256(raw.encode("utf-8")).hexdigest()


class MemoryIdempotencyBackend:
    """In-memory backend compatible with legacy behavior."""

    def __init__(
        self,
        store: dict[str, dict[str, Any]],
        *,
        ttl_seconds: int,
        time_fn: Callable[[], float] = time.time,
    ):
        self._store = store
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._time_fn = time_fn
        self._lock = Lock()

    def _is_expired(self, created_at: float) -> bool:
        return (self._time_fn() - created_at) > self._ttl_seconds

    def _purge_expired_locked(self) -> None:
        expired_ids = []
        for request_id, entry in self._store.items():
            try:
                created_at = float(entry.get("created_at") or 0.0)
            except (TypeError, ValueError):
                created_at = 0.0
            if self._is_expired(created_at):
                expired_ids.append(request_id)
        for request_id in expired_ids:
            self._store.pop(request_id, None)

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._purge_expired_locked()
            entry = self._store.get(request_id)
            if not isinstance(entry, dict):
                return None

            try:
                created_at = float(entry.get("created_at") or 0.0)
            except (TypeError, ValueError):
                created_at = 0.0

            if self._is_expired(created_at):
                self._store.pop(request_id, None)
                return None

            return {
                "fingerprint": str(entry.get("fingerprint") or ""),
                "response": entry.get("response"),
            }

    def set(self, request_id: str, *, fingerprint: str, response: dict[str, Any]) -> None:
        with self._lock:
            self._purge_expired_locked()
            self._store[request_id] = {
                "fingerprint": str(fingerprint or ""),
                "response": response,
                "created_at": float(self._time_fn()),
            }


class SQLiteIdempotencyBackend:
    """SQLite-backed idempotency backend persisted across restarts."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        ttl_seconds: int,
        time_fn: Callable[[], float] = time.time,
    ):
        self._db_path = Path(db_path)
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._time_fn = time_fn
        self._lock = Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_cache (
                    request_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_idempotency_created_at "
                "ON idempotency_cache(created_at)"
            )
            conn.commit()

    def _purge_expired_locked(self, conn: sqlite3.Connection) -> None:
        cutoff = float(self._time_fn()) - float(self._ttl_seconds)
        conn.execute("DELETE FROM idempotency_cache WHERE created_at < ?", (cutoff,))

    def get(self, request_id: str) -> dict[str, Any] | None:
        with self._lock:
            try:
                with self._connect() as conn:
                    self._purge_expired_locked(conn)
                    row = conn.execute(
                        "SELECT fingerprint, response_json FROM idempotency_cache WHERE request_id = ?",
                        (request_id,),
                    ).fetchone()
                    conn.commit()
            except sqlite3.Error as exc:
                logger.warning("Falha ao ler idempotência no sqlite: %s", exc)
                return None

        if row is None:
            return None

        try:
            response = json.loads(str(row["response_json"]))
        except (TypeError, ValueError) as exc:
            logger.warning("Registro de idempotência inválido no sqlite para %s: %s", request_id, exc)
            return None

        return {
            "fingerprint": str(row["fingerprint"] or ""),
            "response": response,
        }

    def set(self, request_id: str, *, fingerprint: str, response: dict[str, Any]) -> None:
        response_json = json.dumps(response, ensure_ascii=False, sort_keys=True)
        with self._lock:
            try:
                with self._connect() as conn:
                    self._purge_expired_locked(conn)
                    conn.execute(
                        """
                        INSERT INTO idempotency_cache(request_id, fingerprint, response_json, created_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(request_id) DO UPDATE SET
                            fingerprint=excluded.fingerprint,
                            response_json=excluded.response_json,
                            created_at=excluded.created_at
                        """,
                        (request_id, fingerprint, response_json, float(self._time_fn())),
                    )
                    conn.commit()
            except sqlite3.Error as exc:
                logger.warning("Falha ao gravar idempotência no sqlite: %s", exc)


class CacheManagerIdempotencyBackend:
    """Alternative persistent backend based on existing CacheManager."""

    def __init__(
        self,
        cache_manager: Any,
        *,
        ttl_seconds: int,
        time_fn: Callable[[], float] = time.time,
        category: str = "idempotency_cache",
    ):
        self._cache_manager = cache_manager
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._time_fn = time_fn
        self._category = category
        self._lock = Lock()

    def _key(self, request_id: str) -> str:
        return self._cache_manager.hash_payload({"request_id": request_id})

    def _is_expired(self, created_at: float) -> bool:
        return (self._time_fn() - created_at) > self._ttl_seconds

    def get(self, request_id: str) -> dict[str, Any] | None:
        key = self._key(request_id)
        with self._lock:
            payload = self._cache_manager.get(key, category=self._category)

        if not isinstance(payload, dict):
            return None

        try:
            created_at = float(payload.get("created_at") or 0.0)
        except (TypeError, ValueError):
            created_at = 0.0

        if created_at > 0.0 and self._is_expired(created_at):
            self._cache_manager.invalidate(key, category=self._category)
            return None

        return {
            "fingerprint": str(payload.get("fingerprint") or ""),
            "response": payload.get("response"),
        }

    def set(self, request_id: str, *, fingerprint: str, response: dict[str, Any]) -> None:
        key = self._key(request_id)
        payload = {
            "fingerprint": str(fingerprint or ""),
            "response": response,
            "created_at": float(self._time_fn()),
        }
        with self._lock:
            self._cache_manager.set(key, payload, category=self._category)


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


def _build_idempotency_backend() -> Any:
    """Instantiate configured idempotency backend with safe fallbacks."""
    backend_name = (IDEMPOTENCY_BACKEND or "memory").strip().lower()
    if backend_name == "memory":
        return MemoryIdempotencyBackend(
            _IDEMPOTENCY_CACHE,
            ttl_seconds=_IDEMPOTENCY_TTL_SECONDS,
        )

    if backend_name == "sqlite":
        try:
            return SQLiteIdempotencyBackend(
                IDEMPOTENCY_SQLITE_PATH,
                ttl_seconds=_IDEMPOTENCY_TTL_SECONDS,
            )
        except Exception as exc:
            logger.warning(
                "Falha ao inicializar backend sqlite de idempotência (%s). "
                "Fallback para cache_manager/memory.",
                exc,
            )
            cache_manager = _get_cache_manager()
            if cache_manager is not None:
                return CacheManagerIdempotencyBackend(
                    cache_manager,
                    ttl_seconds=_IDEMPOTENCY_TTL_SECONDS,
                )
            return MemoryIdempotencyBackend(
                _IDEMPOTENCY_CACHE,
                ttl_seconds=_IDEMPOTENCY_TTL_SECONDS,
            )

    logger.warning(
        "IDEMPOTENCY_BACKEND inválido '%s'. Usando backend memory.",
        backend_name,
    )
    return MemoryIdempotencyBackend(
        _IDEMPOTENCY_CACHE,
        ttl_seconds=_IDEMPOTENCY_TTL_SECONDS,
    )


def _get_idempotency_backend() -> Any:
    """Return singleton idempotency backend."""
    global _idempotency_backend
    if _idempotency_backend is not None:
        return _idempotency_backend

    with _idempotency_backend_lock:
        if _idempotency_backend is None:
            _idempotency_backend = _build_idempotency_backend()
    return _idempotency_backend


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
    
    allowed, retry_after = circuit_breaker.allow_request()
    if not allowed:
        raise LLMError(
            "Circuit breaker OPEN para chamadas LLM. "
            f"Tente novamente em aproximadamente {retry_after:.1f}s."
        )

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
                    tokens = min(tokens + max(256, tokens // 2), MAX_TOKENS_CEILING)
                    kwargs["max_tokens"] = tokens
                    logger.warning(
                        "🔁 Repetindo chamada após truncamento com max_tokens=%d "
                        "(tentativa %d/%d).",
                        tokens, attempt + 1, LLM_MAX_RETRIES,
                    )
                    continue
                raise LLMTruncatedResponseError(msg)

            response_payload = LLMResponse(
                content=content,
                tokens=usage,
                model=modelo,
                finish_reason=finish_reason,
            )
            circuit_breaker.on_success()
            return response_payload

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

    if last_error is not None:
        circuit_breaker.on_failure(last_error)

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
    request_id = str(kwargs.pop("request_id", "") or "").strip()
    token_manager = _get_token_manager()
    prepared_messages = _prepare_messages(
        system_prompt=system_prompt,
        user_message=user_message,
        messages=messages,
    )
    prompt_blob = _messages_to_text(prepared_messages)
    response_format = kwargs.get("response_format")
    request_fingerprint = ""
    idempotency_backend = None
    if request_id:
        idempotency_backend = _get_idempotency_backend()
        request_fingerprint = _build_idempotency_fingerprint(
            model=str(modelo),
            messages=prepared_messages,
            max_tokens=kwargs.get("max_tokens"),
            temperature=kwargs.get("temperature"),
            response_format=response_format if isinstance(response_format, dict) else None,
        )
        cached_idempotent = idempotency_backend.get(request_id)
        if cached_idempotent:
            cached_fp = str(cached_idempotent.get("fingerprint") or "")
            if cached_fp and cached_fp != request_fingerprint:
                raise LLMError(
                    "request_id reutilizado com payload diferente. "
                    "Use um novo request_id para esta chamada."
                )
            cached_response = cached_idempotent.get("response")
            if isinstance(cached_response, dict):
                logger.info(
                    "♻️ Idempotência ativada: retornando resposta já registrada para request_id=%s",
                    request_id,
                )
                return _deserialize_response(cached_response)

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
                response = LLMResponse(**cached)
                if request_id:
                    idempotency_backend = idempotency_backend or _get_idempotency_backend()
                    idempotency_backend.set(
                        request_id,
                        fingerprint=request_fingerprint,
                        response=_serialize_response(response),
                    )
                return response

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

    if request_id:
        idempotency_backend = idempotency_backend or _get_idempotency_backend()
        idempotency_backend.set(
            request_id,
            fingerprint=request_fingerprint,
            response=_serialize_response(response),
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
