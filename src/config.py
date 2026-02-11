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

# LLM call settings
LLM_TIMEOUT: int = int(os.getenv("LLM_TIMEOUT", "120"))
LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))

# PDF processing
MIN_TEXT_THRESHOLD: int = 100  # Minimum chars before triggering pdfplumber fallback

# Context limits (GPT-4o = 128k tokens)
CONTEXT_LIMIT_TOKENS: int = 128_000
CONTEXT_WARNING_RATIO: float = 0.8  # Warn at 80% of limit

# Token management (new architecture)
TOKEN_BUDGET_RATIO: float = float(os.getenv("TOKEN_BUDGET_RATIO", "0.7"))  # Use 70% as safety margin
CHUNK_OVERLAP_TOKENS: int = int(os.getenv("CHUNK_OVERLAP_TOKENS", "500"))
MAX_CONTEXT_TOKENS: int = int(os.getenv("MAX_CONTEXT_TOKENS", "25000"))  # Respect TPM limit of 30k/min

# Rate limits (tokens per minute)
RATE_LIMIT_TPM: dict[str, int] = {
    # OpenAI
    "gpt-4o": 30_000,
    "gpt-4o-mini": 200_000,
    # OpenRouter (generous limits)
    "deepseek/deepseek-r1": 100_000,
    "deepseek/deepseek-chat-v3-0324:free": 50_000,
    "google/gemini-2.0-flash-001": 1_000_000,
    "google/gemini-2.5-flash-preview": 1_000_000,
    "anthropic/claude-3.5-sonnet": 80_000,
}

# Feature flags for robust architecture
ENABLE_CHUNKING: bool = os.getenv("ENABLE_CHUNKING", "true").lower() == "true"
ENABLE_HYBRID_MODELS: bool = os.getenv("ENABLE_HYBRID_MODELS", "true").lower() == "true"
ENABLE_RATE_LIMITING: bool = os.getenv("ENABLE_RATE_LIMITING", "true").lower() == "true"
ENABLE_CACHING: bool = os.getenv("ENABLE_CACHING", "false").lower() == "true"
ENABLE_PARALLEL_ETAPA2: bool = os.getenv("ENABLE_PARALLEL_ETAPA2", "false").lower() == "true"

# Hybrid model configuration
MODEL_CLASSIFICATION: str = os.getenv("MODEL_CLASSIFICATION", "gpt-4o-mini")
MODEL_LEGAL_ANALYSIS: str = os.getenv("MODEL_LEGAL_ANALYSIS", "gpt-4o")
MODEL_DRAFT_GENERATION: str = os.getenv("MODEL_DRAFT_GENERATION", "gpt-4o")

# Cache configuration
CACHE_TTL_HOURS: int = int(os.getenv("CACHE_TTL_HOURS", "24"))

# Parallel processing
ETAPA2_PARALLEL_WORKERS: int = int(os.getenv("ETAPA2_PARALLEL_WORKERS", "3"))

# Logging
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()


def setup_logging() -> logging.Logger:
    """Configure project-wide logging."""
    logger = logging.getLogger("copilot_juridico")
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
