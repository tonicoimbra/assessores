"""Configuration and environment variables."""

import logging
import os
import sys
from pathlib import Path

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
TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.0"))

# OpenRouter settings
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# Google AI Studio API (Gemini Direct)
GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")

# LLM call settings
LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "120"))
LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))

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
CACHE_TTL_HOURS: int = int(os.getenv("CACHE_TTL_HOURS", "24"))

# Parallel processing
ETAPA2_PARALLEL_WORKERS: int = int(os.getenv("ETAPA2_PARALLEL_WORKERS", "3"))

# Stage/token tuning
MAX_TOKENS_INTERMEDIATE: int = int(os.getenv("MAX_TOKENS_INTERMEDIATE", "700"))
MAX_TOKENS_ETAPA1: int = int(os.getenv("MAX_TOKENS_ETAPA1", "1400"))
MAX_TOKENS_ETAPA2: int = int(os.getenv("MAX_TOKENS_ETAPA2", "2200"))
MAX_TOKENS_ETAPA3: int = int(os.getenv("MAX_TOKENS_ETAPA3", "3200"))

# Logging
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()


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

    return logger


def validate_api_key() -> None:
    """Validate that the correct API key is set based on provider. Exit with clear message if missing."""
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
