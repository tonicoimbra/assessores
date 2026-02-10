"""Token management: budget tracking, chunking, and rate limiting."""

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

import tiktoken

from src.config import (
    CONTEXT_LIMIT_TOKENS,
    CONTEXT_WARNING_RATIO,
)

logger = logging.getLogger("copilot_juridico")


class TokenBudgetExceededError(Exception):
    """Raised when token budget is exceeded."""


class TokenManager:
    """Centralized token budget management and estimation."""

    def __init__(self):
        # Track budget usage per model
        self._budgets: dict[str, int] = {}
        self._limits: dict[str, int] = {}
        self._encoding_cache: dict[str, Any] = {}

    def estimate_tokens(self, text: str, model: str = "gpt-4o") -> int:
        """
        Estimate token count using tiktoken.

        Args:
            text: Text to estimate.
            model: Model name for encoding selection.

        Returns:
            Estimated token count.
        """
        if model not in self._encoding_cache:
            try:
                self._encoding_cache[model] = tiktoken.encoding_for_model(model)
            except KeyError:
                self._encoding_cache[model] = tiktoken.get_encoding("cl100k_base")

        encoding = self._encoding_cache[model]
        return len(encoding.encode(text))

    def reserve_budget(self, tokens: int, model: str) -> bool:
        """
        Reserve tokens from budget. Returns False if insufficient budget.

        Args:
            tokens: Number of tokens to reserve.
            model: Model name.

        Returns:
            True if reservation succeeded, False if budget exceeded.
        """
        # Get or initialize budget for model
        if model not in self._limits:
            # Use context limit as default budget
            self._limits[model] = int(CONTEXT_LIMIT_TOKENS * CONTEXT_WARNING_RATIO)
            self._budgets[model] = 0

        current = self._budgets[model]
        limit = self._limits[model]

        if current + tokens > limit:
            logger.warning(
                "⚠️  Orçamento de tokens insuficiente: %d usado + %d necessário > %d limite",
                current, tokens, limit,
            )
            return False

        self._budgets[model] += tokens
        logger.debug("Reservado %d tokens para %s (%d/%d usado)", tokens, model, self._budgets[model], limit)
        return True

    def release_budget(self, tokens: int, model: str) -> None:
        """
        Release tokens back to budget after call completion.

        Args:
            tokens: Number of tokens to release.
            model: Model name.
        """
        if model in self._budgets:
            self._budgets[model] = max(0, self._budgets[model] - tokens)
            logger.debug("Liberado %d tokens de %s (%d/%d usado)", tokens, model, self._budgets[model], self._limits.get(model, 0))

    def get_budget_status(self, model: str) -> dict[str, int]:
        """
        Get current budget status for a model.

        Args:
            model: Model name.

        Returns:
            Dict with 'used', 'limit', and 'available' keys.
        """
        limit = self._limits.get(model, int(CONTEXT_LIMIT_TOKENS * CONTEXT_WARNING_RATIO))
        used = self._budgets.get(model, 0)
        return {
            "used": used,
            "limit": limit,
            "available": limit - used,
        }

    def reset_budget(self, model: str | None = None) -> None:
        """
        Reset budget tracking (useful for new pipeline runs).

        Args:
            model: If specified, reset only this model. Otherwise reset all.
        """
        if model:
            self._budgets[model] = 0
        else:
            self._budgets.clear()
        logger.info("Orçamento resetado: %s", model or "todos os modelos")


class TextChunker:
    """Intelligent text chunking with semantic boundaries and overlap."""

    def __init__(self, max_tokens: int = 100_000, overlap_tokens: int = 500):
        """
        Initialize chunker.

        Args:
            max_tokens: Maximum tokens per chunk.
            overlap_tokens: Token overlap between chunks for context continuity.
        """
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.token_manager = TokenManager()

    def chunk_text(self, text: str, model: str = "gpt-4o") -> list[str]:
        """
        Divide text into semantic chunks with overlap.

        Strategy:
        1. Estimate total tokens
        2. If < max_tokens, return [text] (no chunking)
        3. Otherwise, split by paragraphs maintaining overlap
        4. Preserve section headers across chunks

        Args:
            text: Text to chunk.
            model: Model for token estimation.

        Returns:
            List of text chunks with semantic boundaries.
        """
        total_tokens = self.token_manager.estimate_tokens(text, model)

        # No chunking needed
        if total_tokens <= self.max_tokens:
            logger.debug("Texto cabe em um chunk (%d tokens)", total_tokens)
            return [text]

        logger.info(
            "📦 Chunking necessário: %d tokens → chunks de %d tokens com overlap de %d",
            total_tokens, self.max_tokens, self.overlap_tokens,
        )

        # Split by double newlines (paragraphs)
        paragraphs = text.split("\n\n")
        chunks: list[str] = []
        current_chunk: list[str] = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = self.token_manager.estimate_tokens(para, model)

            # If single paragraph exceeds limit, hard split it
            if para_tokens > self.max_tokens:
                logger.warning(
                    "⚠️  Parágrafo grande (%d tokens) excede limite — aplicando split forçado",
                    para_tokens,
                )
                # Save current chunk if any
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = []
                    current_tokens = 0

                # Hard split this paragraph
                chunks.extend(self._hard_split_text(para, model))
                continue

            # Check if adding this paragraph exceeds limit
            if current_tokens + para_tokens > self.max_tokens and current_chunk:
                # Save current chunk
                chunks.append("\n\n".join(current_chunk))

                # Start new chunk with overlap from previous
                overlap_text = self._get_overlap_text(current_chunk, model)
                current_chunk = [overlap_text, para] if overlap_text else [para]
                current_tokens = self.token_manager.estimate_tokens("\n\n".join(current_chunk), model)
            else:
                # Add to current chunk
                current_chunk.append(para)
                current_tokens += para_tokens

        # Add final chunk
        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        logger.info("✅ Texto dividido em %d chunks", len(chunks))
        return chunks

    def _hard_split_text(self, text: str, model: str) -> list[str]:
        """
        Force split text by characters when paragraph is too large.

        Args:
            text: Text to split.
            model: Model for token estimation.

        Returns:
            List of text chunks.
        """
        # Estimate chars per token ratio
        total_tokens = self.token_manager.estimate_tokens(text, model)
        chars_per_token = len(text) / total_tokens if total_tokens > 0 else 4

        # Calculate target chunk size in characters
        target_chars = int(self.max_tokens * chars_per_token * 0.9)  # 90% safety margin

        chunks: list[str] = []
        start = 0

        while start < len(text):
            end = start + target_chars

            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence end markers within next 200 chars
                search_end = min(end + 200, len(text))
                sentence_markers = [". ", ".\n", "! ", "?\n"]
                best_break = end

                for marker in sentence_markers:
                    idx = text.find(marker, end, search_end)
                    if idx != -1:
                        best_break = idx + len(marker)
                        break

                end = best_break

            chunk = text[start:end]
            chunks.append(chunk)
            start = end

        return chunks

    def _get_overlap_text(self, paragraphs: list[str], model: str) -> str:
        """
        Get last N paragraphs that fit within overlap budget.

        Args:
            paragraphs: List of paragraphs.
            model: Model for token estimation.

        Returns:
            Overlap text (last paragraphs up to overlap_tokens limit).
        """
        overlap_text = ""
        overlap_tokens = 0

        for para in reversed(paragraphs):
            para_tokens = self.token_manager.estimate_tokens(para, model)
            if overlap_tokens + para_tokens > self.overlap_tokens:
                break
            overlap_text = para + "\n\n" + overlap_text
            overlap_tokens += para_tokens

        return overlap_text.strip()

    def chunk_by_sections(self, text: str, model: str = "gpt-4o") -> dict[str, str]:
        """
        Divide text by legal document sections (EMENTA, RELATÓRIO, VOTO, DISPOSITIVO).

        Args:
            text: Legal document text.
            model: Model for token estimation.

        Returns:
            Dict mapping section names to section text.
        """
        # Common legal document sections
        section_patterns = [
            r"EMENTA",
            r"RELATÓRIO",
            r"VOTO",
            r"DISPOSITIVO",
            r"DECISÃO",
            r"ACÓRDÃO",
        ]

        sections: dict[str, str] = {}
        current_section = "PREÂMBULO"
        current_text: list[str] = []

        for line in text.split("\n"):
            # Check if line is a section header
            is_header = False
            for pattern in section_patterns:
                if re.match(rf"^\s*{pattern}\s*$", line, re.IGNORECASE):
                    # Save previous section
                    if current_text:
                        sections[current_section] = "\n".join(current_text).strip()

                    # Start new section
                    current_section = line.strip().upper()
                    current_text = []
                    is_header = True
                    break

            if not is_header:
                current_text.append(line)

        # Save final section
        if current_text:
            sections[current_section] = "\n".join(current_text).strip()

        logger.info("📑 Documento dividido em %d seções: %s", len(sections), ", ".join(sections.keys()))
        return sections


class RateLimiter:
    """Track tokens per minute (TPM) and apply proactive throttling."""

    def __init__(self):
        # Track usage with timestamps: model -> [(timestamp, tokens), ...]
        self.usage_window: dict[str, list[tuple[datetime, int]]] = defaultdict(list)
        # Rate limits (TPM) per model
        self.limits: dict[str, int] = {
            "gpt-4o": 30_000,
            "gpt-4o-mini": 200_000,
        }

    def add_usage(self, model: str, tokens: int) -> None:
        """
        Register token usage with timestamp.

        Args:
            model: Model name.
            tokens: Tokens consumed.
        """
        self.usage_window[model].append((datetime.now(), tokens))
        self._cleanup_old_entries(model)

    def _cleanup_old_entries(self, model: str) -> None:
        """Remove usage entries older than 60 seconds."""
        cutoff = datetime.now() - timedelta(minutes=1)
        self.usage_window[model] = [
            (ts, tok) for ts, tok in self.usage_window[model] if ts > cutoff
        ]

    def get_current_usage(self, model: str) -> int:
        """
        Get tokens used in the last 60 seconds.

        Args:
            model: Model name.

        Returns:
            Token count in current window.
        """
        self._cleanup_old_entries(model)
        return sum(tok for _, tok in self.usage_window[model])

    def can_proceed(self, model: str, tokens: int) -> bool:
        """
        Check if request can proceed without exceeding rate limit.

        Uses 90% threshold for safety margin.

        Args:
            model: Model name.
            tokens: Tokens to be consumed.

        Returns:
            True if request can proceed safely.
        """
        current = self.get_current_usage(model)
        limit = self.limits.get(model, 30_000)
        threshold = limit * 0.9  # 90% threshold

        return current + tokens <= threshold

    def wait_time_until_available(self, model: str, tokens: int) -> float:
        """
        Calculate seconds to wait until request can proceed.

        Args:
            model: Model name.
            tokens: Tokens to be consumed.

        Returns:
            Seconds to wait (0.0 if can proceed immediately).
        """
        if self.can_proceed(model, tokens):
            return 0.0

        if not self.usage_window[model]:
            return 0.0

        # Time until oldest entry expires (60s window)
        oldest_ts = min(ts for ts, _ in self.usage_window[model])
        wait_until = oldest_ts + timedelta(minutes=1)
        wait_seconds = max(0.0, (wait_until - datetime.now()).total_seconds())

        return wait_seconds

    def get_rate_limit_status(self, model: str) -> dict[str, Any]:
        """
        Get current rate limit status.

        Args:
            model: Model name.

        Returns:
            Dict with usage, limit, and available capacity.
        """
        current = self.get_current_usage(model)
        limit = self.limits.get(model, 30_000)

        return {
            "model": model,
            "current_tpm": current,
            "limit_tpm": limit,
            "available_tpm": limit - current,
            "utilization_pct": round(current / limit * 100, 1) if limit > 0 else 0,
        }


# Global instances
token_manager = TokenManager()
text_chunker = TextChunker()
rate_limiter = RateLimiter()
