"""Configuration and environment variables."""

import logging
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Project paths
BASE_DIR = Path(__file__).resolve().parent.parent
PROMPTS_DIR = BASE_DIR / "prompts"
OUTPUTS_DIR = BASE_DIR / "outputs"

# Load .env from project root
load_dotenv(BASE_DIR / ".env")

# LLM Provider (openai | openrouter)
LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")

# OpenAI settings
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "2048"))
MAX_TOKENS_CEILING: int = int(os.getenv("MAX_TOKENS_CEILING", "12000"))
TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.0"))

# OpenRouter settings
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# Google AI Studio API (Gemini Direct)
GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")

# LLM call settings
LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "120"))
LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))
CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = int(
    os.getenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5")
)
CIRCUIT_BREAKER_RESET_TIMEOUT: int = int(
    os.getenv("CIRCUIT_BREAKER_RESET_TIMEOUT", "60")
)
IDEMPOTENCY_BACKEND: str = os.getenv("IDEMPOTENCY_BACKEND", "memory").strip().lower()
IDEMPOTENCY_SQLITE_PATH: str = os.getenv(
    "IDEMPOTENCY_SQLITE_PATH",
    str(OUTPUTS_DIR / ".cache" / "idempotency_cache.sqlite3"),
).strip()

# Prompt profile
_prompt_profile_raw = os.getenv("PROMPT_PROFILE", "lean").strip().lower()
PROMPT_PROFILE: str = _prompt_profile_raw if _prompt_profile_raw in {"lean", "full"} else "lean"
_prompt_strategy_raw = os.getenv("PROMPT_STRATEGY", "modular").strip().lower()
PROMPT_STRATEGY: str = _prompt_strategy_raw if _prompt_strategy_raw in {"modular", "legacy"} else "modular"
ALLOW_MINIMAL_PROMPT_FALLBACK: bool = (
    os.getenv("ALLOW_MINIMAL_PROMPT_FALLBACK", "false").lower() == "true"
)

# PDF processing
MIN_TEXT_THRESHOLD: int = 100  # Minimum chars before triggering pdfplumber fallback
ENABLE_OCR_FALLBACK: bool = os.getenv("ENABLE_OCR_FALLBACK", "false").lower() == "true"
OCR_LANGUAGES: str = os.getenv("OCR_LANGUAGES", "por+eng")
OCR_TRIGGER_MIN_CHARS_PER_PAGE: int = int(os.getenv("OCR_TRIGGER_MIN_CHARS_PER_PAGE", "20"))
OCR_MAX_WORKERS: int = int(os.getenv("OCR_MAX_WORKERS", "4"))
ENABLE_OCR_PREPROCESSING: bool = os.getenv("ENABLE_OCR_PREPROCESSING", "true").lower() == "true"
OCR_DESKEW_ENABLED: bool = os.getenv("OCR_DESKEW_ENABLED", "true").lower() == "true"
OCR_DENOISE_ENABLED: bool = os.getenv("OCR_DENOISE_ENABLED", "true").lower() == "true"
OCR_BINARIZATION_ENABLED: bool = os.getenv("OCR_BINARIZATION_ENABLED", "true").lower() == "true"
OCR_BINARIZATION_THRESHOLD: int = int(os.getenv("OCR_BINARIZATION_THRESHOLD", "160"))
OCR_DENOISE_MEDIAN_SIZE: int = int(os.getenv("OCR_DENOISE_MEDIAN_SIZE", "3"))
ENABLE_EXTRACTION_QUALITY_GATE: bool = (
    os.getenv("ENABLE_EXTRACTION_QUALITY_GATE", "true").lower() == "true"
)
EXTRACTION_MIN_QUALITY_SCORE: float = float(
    os.getenv("EXTRACTION_MIN_QUALITY_SCORE", "0.2")
)
EXTRACTION_MAX_NOISE_RATIO: float = float(
    os.getenv("EXTRACTION_MAX_NOISE_RATIO", "0.95")
)

# Context limits (GPT-4o = 128k tokens)
CONTEXT_LIMIT_TOKENS: int = 128_000
CONTEXT_WARNING_RATIO: float = 0.8  # Warn at 80% of limit

# Token management (new architecture)
TOKEN_BUDGET_RATIO: float = float(os.getenv("TOKEN_BUDGET_RATIO", "0.7"))  # Use 70% as safety margin
CHUNK_OVERLAP_TOKENS: int = int(os.getenv("CHUNK_OVERLAP_TOKENS", "500"))
MAX_CONTEXT_TOKENS: int = int(os.getenv("MAX_CONTEXT_TOKENS", "25000"))  # Respect TPM limit of 30k/min
ENABLE_CONTEXT_COVERAGE_GATE: bool = (
    os.getenv("ENABLE_CONTEXT_COVERAGE_GATE", "true").lower() == "true"
)
CONTEXT_MIN_COVERAGE_RATIO: float = float(
    os.getenv("CONTEXT_MIN_COVERAGE_RATIO", "0.9")
)

# --- Rate Limiting (Tokens per minute per model) ---
RATE_LIMIT_TPM: dict[str, int] = {
    # OpenAI
    "gpt-4o": 30_000,
    "gpt-4.1": 30_000,
    "gpt-4.1-mini": 200_000,
    "gpt-4o-mini": 200_000,
    "o1-preview": 30_000, # Assuming this is an OpenAI model or similar
    # OpenRouter (generous limits)
    "deepseek/deepseek-r1": 100_000,
    "deepseek/deepseek-chat-v3-0324:free": 40_000, # Adjusted from 50k to 40k
    "google/gemini-2.0-flash-001": 2_000_000, # Google AI Studio (High limit)
    "google/gemini-2.0-flash-lite-preview-02-05:free": 1_000_000,
    "google/gemini-2.5-flash-preview": 1_000_000,
    "qwen/qwen-2.5-72b-instruct": 100_000,
    "anthropic/claude-3.5-sonnet": 80_000,
}

# Feature flags for robust architecture
ENABLE_CHUNKING: bool = os.getenv("ENABLE_CHUNKING", "true").lower() == "true"
ENABLE_HYBRID_MODELS: bool = os.getenv("ENABLE_HYBRID_MODELS", "true").lower() == "true"
ENABLE_RATE_LIMITING: bool = os.getenv("ENABLE_RATE_LIMITING", "true").lower() == "true"
ENABLE_CACHING: bool = os.getenv("ENABLE_CACHING", "false").lower() == "true"
ENABLE_PARALLEL_ETAPA2: bool = os.getenv("ENABLE_PARALLEL_ETAPA2", "false").lower() == "true"
ENABLE_FAIL_CLOSED: bool = os.getenv("ENABLE_FAIL_CLOSED", "true").lower() == "true"
ENABLE_DEAD_LETTER_QUEUE: bool = os.getenv("ENABLE_DEAD_LETTER_QUEUE", "true").lower() == "true"
ENABLE_CONFIDENCE_ESCALATION: bool = os.getenv("ENABLE_CONFIDENCE_ESCALATION", "true").lower() == "true"
CONFIDENCE_THRESHOLD_GLOBAL: float = float(os.getenv("CONFIDENCE_THRESHOLD_GLOBAL", "0.75"))
CONFIDENCE_THRESHOLD_FIELD: float = float(os.getenv("CONFIDENCE_THRESHOLD_FIELD", "0.75"))
CONFIDENCE_THRESHOLD_THEME: float = float(os.getenv("CONFIDENCE_THRESHOLD_THEME", "0.70"))
CONFIDENCE_WEIGHT_ETAPA1: float = float(os.getenv("CONFIDENCE_WEIGHT_ETAPA1", "0.35"))
CONFIDENCE_WEIGHT_ETAPA2: float = float(os.getenv("CONFIDENCE_WEIGHT_ETAPA2", "0.35"))
CONFIDENCE_WEIGHT_ETAPA3: float = float(os.getenv("CONFIDENCE_WEIGHT_ETAPA3", "0.30"))
CONFIDENCE_WEIGHTS_SUM_TOLERANCE: float = 0.001
ENABLE_ETAPA1_CRITICAL_FIELDS_CONSENSUS: bool = (
    os.getenv("ENABLE_ETAPA1_CRITICAL_FIELDS_CONSENSUS", "false").lower() == "true"
)

# Hybrid model configuration
MODEL_CLASSIFICATION: str = os.getenv("MODEL_CLASSIFICATION", "gpt-4.1-mini")
MODEL_LEGAL_ANALYSIS: str = os.getenv("MODEL_LEGAL_ANALYSIS", "gpt-4.1")
MODEL_DRAFT_GENERATION: str = os.getenv("MODEL_DRAFT_GENERATION", "gpt-4.1")

# Input invariants for classification
REQUIRE_EXACTLY_ONE_RECURSO: bool = os.getenv("REQUIRE_EXACTLY_ONE_RECURSO", "true").lower() == "true"
MIN_ACORDAO_COUNT: int = int(os.getenv("MIN_ACORDAO_COUNT", "1"))
ENABLE_CLASSIFICATION_MANUAL_REVIEW: bool = (
    os.getenv("ENABLE_CLASSIFICATION_MANUAL_REVIEW", "true").lower() == "true"
)
CLASSIFICATION_MANUAL_REVIEW_CONFIDENCE_THRESHOLD: float = float(
    os.getenv("CLASSIFICATION_MANUAL_REVIEW_CONFIDENCE_THRESHOLD", "0.65")
)
CLASSIFICATION_MANUAL_REVIEW_MARGIN_THRESHOLD: float = float(
    os.getenv("CLASSIFICATION_MANUAL_REVIEW_MARGIN_THRESHOLD", "0.15")
)

# Cache configuration
_cache_ttl_seconds_raw = os.getenv("CACHE_TTL_SECONDS", "").strip()
if _cache_ttl_seconds_raw:
    CACHE_TTL_SECONDS: int = int(_cache_ttl_seconds_raw)
else:
    # Backward compatibility with legacy CACHE_TTL_HOURS.
    CACHE_TTL_SECONDS = int(float(os.getenv("CACHE_TTL_HOURS", "24")) * 3600)
CACHE_TTL_HOURS: float = CACHE_TTL_SECONDS / 3600.0
CACHE_PURGE_ON_START: bool = os.getenv("CACHE_PURGE_ON_START", "true").lower() == "true"
CACHE_ENCRYPTION_KEY: str = os.getenv("CACHE_ENCRYPTION_KEY", "").strip()

# Parallel processing
ETAPA2_PARALLEL_WORKERS: int = int(os.getenv("ETAPA2_PARALLEL_WORKERS", "3"))

# Stage/token tuning
MAX_TOKENS_INTERMEDIATE: int = int(os.getenv("MAX_TOKENS_INTERMEDIATE", "1500"))
MAX_TOKENS_ETAPA1: int = int(os.getenv("MAX_TOKENS_ETAPA1", "1400"))
MAX_TOKENS_ETAPA2: int = int(os.getenv("MAX_TOKENS_ETAPA2", "2200"))
MAX_TOKENS_ETAPA3: int = int(os.getenv("MAX_TOKENS_ETAPA3", "3200"))

# Logging
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
MAX_LOG_MESSAGE_CHARS: int = int(os.getenv("MAX_LOG_MESSAGE_CHARS", "1200"))
_log_sanitize_level_raw = os.getenv("LOG_SANITIZE_LEVEL", "full").strip().lower()
LOG_SANITIZE_LEVEL: str = (
    _log_sanitize_level_raw if _log_sanitize_level_raw in {"full", "partial", "off"} else "full"
)

# Web download access control
ENABLE_WEB_DOWNLOAD_ACCESS_CONTROL: bool = (
    os.getenv("ENABLE_WEB_DOWNLOAD_ACCESS_CONTROL", "true").lower() == "true"
)
WEB_DOWNLOAD_TOKEN_TTL_SECONDS: int = int(
    os.getenv("WEB_DOWNLOAD_TOKEN_TTL_SECONDS", "900")
)
# Web authentication and abuse protection
WEB_AUTH_ENABLED: bool = os.getenv("WEB_AUTH_ENABLED", "false").lower() == "true"
WEB_AUTH_TOKEN: str = os.getenv("WEB_AUTH_TOKEN", "")
UPLOAD_RATE_LIMIT_PER_MINUTE: int = int(os.getenv("UPLOAD_RATE_LIMIT_PER_MINUTE", "10"))

# Max size for PDF uploads (default 50 MB)
MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50"))
# Time-to-live for in-memory job entries (default 2 hours)
JOB_TTL_HOURS: int = int(os.getenv("JOB_TTL_HOURS", "2"))

# DLQ encryption
DLQ_ENCRYPTION_KEY: str = os.getenv("DLQ_ENCRYPTION_KEY", "")
DLQ_ENCRYPTION_ENABLED: bool = bool(DLQ_ENCRYPTION_KEY)
if not CACHE_ENCRYPTION_KEY:
    CACHE_ENCRYPTION_KEY = DLQ_ENCRYPTION_KEY

# Data retention policy
ENABLE_RETENTION_POLICY: bool = (
    os.getenv("ENABLE_RETENTION_POLICY", "true").lower() == "true"
)
RETENTION_OUTPUT_DAYS: int = int(os.getenv("RETENTION_OUTPUT_DAYS", "30"))
RETENTION_CHECKPOINT_DAYS: int = int(os.getenv("RETENTION_CHECKPOINT_DAYS", "7"))
RETENTION_WEB_UPLOAD_DAYS: int = int(os.getenv("RETENTION_WEB_UPLOAD_DAYS", "2"))
RETENTION_DEAD_LETTER_DAYS: int = int(os.getenv("RETENTION_DEAD_LETTER_DAYS", "30"))

RedactionReplacement = str | Callable[[re.Match[str]], str]
RedactionRule = tuple[re.Pattern[str], RedactionReplacement]


def _redact_party_name(match: re.Match[str]) -> str:
    return f"{match.group(1)}{match.group(2)}[REDACTED_PARTY_NAME]"


_PARTIAL_REDACTION_RULES: tuple[RedactionRule, ...] = (
    (re.compile(r"sk-or-[A-Za-z0-9_\-]{8,}", re.IGNORECASE), "[REDACTED_OPENROUTER_KEY]"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}", re.IGNORECASE), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"), r"\1[REDACTED_TOKEN]"),
    (re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b"), "[REDACTED_PROCESSO]"),
    (re.compile(r"\b\d{20}\b"), "[REDACTED_PROCESSO]"),
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "[REDACTED_CPF]"),
    (re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b"), "[REDACTED_CNPJ]"),
)

_FULL_REDACTION_RULES: tuple[RedactionRule, ...] = (
    (
        re.compile(
            r"(?i)\b("
            r"recorrente|recorrido|agravante|agravado|apelante|apelado|"
            r"embargante|embargado|impetrante|impetrado|autor(?:a)?|r[ée]u|"
            r"exequente|executado|parte\s+autora|parte\s+r[ée]"
            r")\b(\s*[:=\-]\s*)([^\n,;|]{3,120})"
        ),
        _redact_party_name,
    ),
    (
        re.compile(r"(?i)\b(nome(?:\s+da)?\s+parte)\b(\s*[:=\-]\s*)([^\n,;|]{3,120})"),
        _redact_party_name,
    ),
)


def sanitize_log_text(text: str) -> str:
    """Redact sensitive material from log text."""
    sanitized = str(text or "")

    if LOG_SANITIZE_LEVEL != "off":
        rules: tuple[RedactionRule, ...] = _PARTIAL_REDACTION_RULES
        if LOG_SANITIZE_LEVEL == "full":
            rules = _PARTIAL_REDACTION_RULES + _FULL_REDACTION_RULES
        for pattern, replacement in rules:
            sanitized = pattern.sub(replacement, sanitized)

    if MAX_LOG_MESSAGE_CHARS > 0 and len(sanitized) > MAX_LOG_MESSAGE_CHARS:
        suffix = " ... [TRUNCATED]"
        keep = max(0, MAX_LOG_MESSAGE_CHARS - len(suffix))
        sanitized = sanitized[:keep] + suffix
    return sanitized


def _handler_has_sensitive_filter(handler: logging.Handler) -> bool:
    return any(isinstance(f, SensitiveDataFilter) for f in handler.filters)


def ensure_sensitive_filter_all_handlers(logger: logging.Logger) -> None:
    """Apply SensitiveDataFilter to all logger handlers when sanitization is enabled."""
    if LOG_SANITIZE_LEVEL == "off":
        return
    for handler in logger.handlers:
        if not _handler_has_sensitive_filter(handler):
            handler.addFilter(SensitiveDataFilter())


def _sanitize_log_arg(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_log_text(value)
    if isinstance(value, dict):
        return {k: _sanitize_log_arg(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_log_arg(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_log_arg(v) for v in value)
    return value


class SensitiveDataFilter(logging.Filter):
    """Logging filter that redacts sensitive payloads before emission."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = sanitize_log_text(str(record.msg))
            if record.args:
                if isinstance(record.args, tuple):
                    record.args = tuple(_sanitize_log_arg(v) for v in record.args)
                elif isinstance(record.args, dict):
                    record.args = {k: _sanitize_log_arg(v) for k, v in record.args.items()}
                else:
                    record.args = (_sanitize_log_arg(record.args),)
        except Exception:
            return True
        return True


def validate_environment_settings() -> list[str]:
    """Return environment/config validation errors for secure execution."""
    erros: list[str] = []
    if LLM_PROVIDER not in {"openai", "openrouter"}:
        erros.append(f"LLM_PROVIDER inválido: '{LLM_PROVIDER}'. Use 'openai' ou 'openrouter'.")
    if LLM_TIMEOUT <= 0:
        erros.append("LLM_TIMEOUT deve ser > 0.")
    if LLM_MAX_RETRIES < 1:
        erros.append("LLM_MAX_RETRIES deve ser >= 1.")
    if CIRCUIT_BREAKER_FAILURE_THRESHOLD < 1:
        erros.append("CIRCUIT_BREAKER_FAILURE_THRESHOLD deve ser >= 1.")
    if CIRCUIT_BREAKER_RESET_TIMEOUT < 1:
        erros.append("CIRCUIT_BREAKER_RESET_TIMEOUT deve ser >= 1.")
    if IDEMPOTENCY_BACKEND not in {"memory", "sqlite"}:
        erros.append("IDEMPOTENCY_BACKEND deve ser 'memory' ou 'sqlite'.")
    if MAX_TOKENS_CEILING <= 0:
        erros.append("MAX_TOKENS_CEILING deve ser > 0.")
    if _log_sanitize_level_raw not in {"full", "partial", "off"}:
        erros.append("LOG_SANITIZE_LEVEL deve ser 'full', 'partial' ou 'off'.")

    for nome, valor in (
        ("TOKEN_BUDGET_RATIO", TOKEN_BUDGET_RATIO),
        ("CONFIDENCE_THRESHOLD_GLOBAL", CONFIDENCE_THRESHOLD_GLOBAL),
        ("CONFIDENCE_THRESHOLD_FIELD", CONFIDENCE_THRESHOLD_FIELD),
        ("CONFIDENCE_THRESHOLD_THEME", CONFIDENCE_THRESHOLD_THEME),
        ("CONFIDENCE_WEIGHT_ETAPA1", CONFIDENCE_WEIGHT_ETAPA1),
        ("CONFIDENCE_WEIGHT_ETAPA2", CONFIDENCE_WEIGHT_ETAPA2),
        ("CONFIDENCE_WEIGHT_ETAPA3", CONFIDENCE_WEIGHT_ETAPA3),
    ):
        if not (0.0 <= float(valor) <= 1.0):
            erros.append(f"{nome} deve estar entre 0 e 1.")

    confidence_weight_sum = (
        CONFIDENCE_WEIGHT_ETAPA1
        + CONFIDENCE_WEIGHT_ETAPA2
        + CONFIDENCE_WEIGHT_ETAPA3
    )
    if abs(confidence_weight_sum - 1.0) > CONFIDENCE_WEIGHTS_SUM_TOLERANCE:
        erros.append(
            "CONFIDENCE_WEIGHT_ETAPA1 + CONFIDENCE_WEIGHT_ETAPA2 + CONFIDENCE_WEIGHT_ETAPA3 "
            f"deve somar 1.0 (±{CONFIDENCE_WEIGHTS_SUM_TOLERANCE:.3f}). "
            f"Valor atual: {confidence_weight_sum:.3f}."
        )

    if ENABLE_WEB_DOWNLOAD_ACCESS_CONTROL and WEB_DOWNLOAD_TOKEN_TTL_SECONDS < 60:
        erros.append("WEB_DOWNLOAD_TOKEN_TTL_SECONDS deve ser >= 60 quando controle de download está ativo.")

    if WEB_AUTH_ENABLED and not WEB_AUTH_TOKEN:
        erros.append("WEB_AUTH_TOKEN deve ser configurado quando WEB_AUTH_ENABLED=true.")
    if UPLOAD_RATE_LIMIT_PER_MINUTE < 1:
        erros.append("UPLOAD_RATE_LIMIT_PER_MINUTE deve ser >= 1.")
    if OCR_MAX_WORKERS < 1:
        erros.append("OCR_MAX_WORKERS deve ser >= 1.")
    if CACHE_TTL_SECONDS < 60:
        erros.append("CACHE_TTL_SECONDS deve ser >= 60.")
    if MAX_TOKENS_CEILING < MAX_TOKENS:
        logging.getLogger("assessor_ai").warning(
            "MAX_TOKENS_CEILING (%d) está abaixo de MAX_TOKENS (%d). "
            "Retries por truncamento não poderão ampliar a resposta além do teto.",
            MAX_TOKENS_CEILING,
            MAX_TOKENS,
        )

    if ENABLE_DEAD_LETTER_QUEUE and not DLQ_ENCRYPTION_KEY:
        logging.getLogger("assessor_ai").warning(
            "AVISO LGPD: ENABLE_DEAD_LETTER_QUEUE=true mas DLQ_ENCRYPTION_KEY não configurada. "
            "Snapshots de DLQ não serão persistidos para evitar texto plano em disco."
        )
    if ENABLE_CACHING and not CACHE_ENCRYPTION_KEY:
        logging.getLogger("assessor_ai").warning(
            "AVISO LGPD: ENABLE_CACHING=true sem CACHE_ENCRYPTION_KEY/DLQ_ENCRYPTION_KEY. "
            "Cache será criptografado com chave efêmera e não persistirá entre reinicializações."
        )

    for nome, valor in (
        ("RETENTION_OUTPUT_DAYS", RETENTION_OUTPUT_DAYS),
        ("RETENTION_CHECKPOINT_DAYS", RETENTION_CHECKPOINT_DAYS),
        ("RETENTION_WEB_UPLOAD_DAYS", RETENTION_WEB_UPLOAD_DAYS),
        ("RETENTION_DEAD_LETTER_DAYS", RETENTION_DEAD_LETTER_DAYS),
    ):
        if int(valor) < 1:
            erros.append(f"{nome} deve ser >= 1.")

    return erros


def setup_logging() -> logging.Logger:
    """Configure project-wide logging."""
    logger = logging.getLogger("assessor_ai")
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    ensure_sensitive_filter_all_handlers(logger)
    return logger


def validate_api_key() -> None:
    """Validate that the correct API key is set based on provider. Exit with clear message if missing."""
    erros_env = validate_environment_settings()
    if erros_env:
        print("\n❌ ERRO de configuração de ambiente:")
        for erro in erros_env:
            print(f"  - {erro}")
        sys.exit(1)

    if LLM_PROVIDER == "openrouter":
        if not OPENROUTER_API_KEY:
            print(
                "\n❌ ERRO: OPENROUTER_API_KEY não configurada.\n"
                "\n"
                "Configure a variável de ambiente:\n"
                "  1. Edite .env e adicione: OPENROUTER_API_KEY=sk-or-...\n"
                "  2. Crie sua key em: https://openrouter.ai/keys\n"
            )
            sys.exit(1)
    elif not OPENAI_API_KEY:
        print(
            "\n❌ ERRO: OPENAI_API_KEY não configurada.\n"
            "\n"
            "Configure a variável de ambiente:\n"
            "  1. Copie o arquivo de exemplo: cp .env.example .env\n"
            "  2. Edite .env e adicione sua chave: OPENAI_API_KEY=sk-...\n"
        )
        sys.exit(1)


# Initialize logging on import
logger = setup_logging()
