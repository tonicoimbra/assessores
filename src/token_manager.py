"""Token management: budget tracking, chunking, and rate limiting."""

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

import tiktoken

from src.config import (
    CHUNK_OVERLAP_TOKENS,
    CONTEXT_LIMIT_TOKENS,
    CONTEXT_WARNING_RATIO,
    MAX_CONTEXT_TOKENS,
    RATE_LIMIT_TPM,
)

logger = logging.getLogger("assessor_ai")


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

    def __init__(
        self,
        max_tokens: int = MAX_CONTEXT_TOKENS,
        overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
    ):
        """
        Initialize chunker.

        Args:
            max_tokens: Maximum tokens per chunk.
            overlap_tokens: Token overlap between chunks for context continuity.
        """
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.token_manager = TokenManager()
        self._section_header_re = re.compile(
            r"^\s*(EMENTA|RELAT[ÓO]RIO|VOTO|DISPOSITIVO|DECIS[ÃA]O|AC[ÓO]RD[ÃA]O|FUNDAMENTA[ÇC][ÃA]O)\s*$",
            re.IGNORECASE,
        )

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
        chunks, _ = self.chunk_text_with_coverage(text, model=model)
        return chunks

    def chunk_text_with_coverage(self, text: str, model: str = "gpt-4o") -> tuple[list[str], dict[str, Any]]:
        """Divide text into semantic chunks and return an auditable coverage map."""
        total_tokens = self.token_manager.estimate_tokens(text, model)
        total_chars = len(text)

        if total_tokens <= self.max_tokens:
            coverage = {
                "strategy": "semantic_sections_paragraphs_v1",
                "aplicado": False,
                "motivo": "fits_single_context",
                "max_tokens": self.max_tokens,
                "overlap_tokens_config": self.overlap_tokens,
                "total_tokens_estimados": total_tokens,
                "total_chars": total_chars,
                "chunk_count": 1,
                "coverage_ratio_chars": 1.0,
                "coverage_ratio_tokens": 1.0,
                "coverage_map": [
                    {
                        "chunk_index": 1,
                        "start_char": 0,
                        "end_char": total_chars,
                        "tokens_estimados": total_tokens,
                        "overlap_prev_tokens": 0,
                        "sections": ["DOCUMENTO_COMPLETO"],
                    }
                ],
            }
            logger.debug("Texto cabe em um chunk (%d tokens)", total_tokens)
            return [text], coverage

        logger.info(
            "📦 Chunking semântico necessário: %d tokens → chunks de %d tokens com overlap de %d",
            total_tokens, self.max_tokens, self.overlap_tokens,
        )
        units = self._build_semantic_units(text, model)
        if not units:
            # Fail-safe: preserve behavior for empty/invalid segmentation.
            return [text], {
                "strategy": "semantic_sections_paragraphs_v1",
                "aplicado": False,
                "motivo": "fallback_no_units",
                "max_tokens": self.max_tokens,
                "overlap_tokens_config": self.overlap_tokens,
                "total_tokens_estimados": total_tokens,
                "total_chars": total_chars,
                "chunk_count": 1,
                "coverage_ratio_chars": 1.0,
                "coverage_ratio_tokens": 1.0,
                "coverage_map": [],
            }

        chunks_unit_indices: list[list[int]] = []
        current_chunk: list[int] = []
        current_tokens = 0

        for idx, unit in enumerate(units):
            unit_tokens = int(unit["tokens"])
            if current_chunk and current_tokens + unit_tokens > self.max_tokens:
                chunks_unit_indices.append(current_chunk)
                overlap_indices = self._get_overlap_unit_indices(current_chunk, units)
                current_chunk = overlap_indices[:]
                current_tokens = sum(int(units[i]["tokens"]) for i in current_chunk)

                while current_chunk and current_tokens + unit_tokens > self.max_tokens:
                    dropped = current_chunk.pop(0)
                    current_tokens -= int(units[dropped]["tokens"])

            current_chunk.append(idx)
            current_tokens += unit_tokens

        if current_chunk:
            chunks_unit_indices.append(current_chunk)

        token_prefix = [0]
        for unit in units:
            token_prefix.append(token_prefix[-1] + int(unit["tokens"]))

        chunks: list[str] = []
        coverage_map: list[dict[str, Any]] = []
        covered_unit_indices: set[int] = set()
        previous_chunk_indices: set[int] = set()

        for chunk_idx, indices in enumerate(chunks_unit_indices, start=1):
            chunk_text = "\n\n".join(str(units[i]["text"]) for i in indices).strip()
            chunks.append(chunk_text)

            start_unit = min(indices)
            end_unit = max(indices)
            sections = sorted({str(units[i]["section"]) for i in indices if str(units[i]["section"]).strip()})
            overlap_units = [i for i in indices if i in previous_chunk_indices]
            overlap_prev_tokens = sum(int(units[i]["tokens"]) for i in overlap_units)
            tokens_estimados = sum(int(units[i]["tokens"]) for i in indices)

            coverage_map.append({
                "chunk_index": chunk_idx,
                "start_char": int(units[start_unit]["start_char"]),
                "end_char": int(units[end_unit]["end_char"]),
                "start_token": token_prefix[start_unit],
                "end_token": token_prefix[end_unit + 1],
                "tokens_estimados": tokens_estimados,
                "overlap_prev_tokens": overlap_prev_tokens,
                "overlap_prev_units": len(overlap_units),
                "sections": sections or ["SEM_SECAO_DETECTADA"],
            })

            covered_unit_indices.update(indices)
            previous_chunk_indices = set(indices)

        covered_chars = sum(
            max(0, int(units[i]["end_char"]) - int(units[i]["start_char"]))
            for i in covered_unit_indices
        )
        covered_tokens = sum(int(units[i]["tokens"]) for i in covered_unit_indices)
        coverage_ratio_chars = round(min(1.0, covered_chars / max(total_chars, 1)), 4)
        coverage_ratio_tokens = round(min(1.0, covered_tokens / max(total_tokens, 1)), 4)

        report = {
            "strategy": "semantic_sections_paragraphs_v1",
            "aplicado": True,
            "motivo": "context_exceeded",
            "max_tokens": self.max_tokens,
            "overlap_tokens_config": self.overlap_tokens,
            "total_tokens_estimados": total_tokens,
            "total_chars": total_chars,
            "chunk_count": len(chunks),
            "coverage_ratio_chars": coverage_ratio_chars,
            "coverage_ratio_tokens": coverage_ratio_tokens,
            "coverage_map": coverage_map,
        }

        logger.info(
            "✅ Texto dividido em %d chunks semânticos (cobertura chars=%.2f%% tokens=%.2f%%)",
            len(chunks),
            coverage_ratio_chars * 100,
            coverage_ratio_tokens * 100,
        )
        return chunks, report

    def _build_semantic_units(self, text: str, model: str) -> list[dict[str, Any]]:
        """Build paragraph units with offsets, section hints and token estimates."""
        units: list[dict[str, Any]] = []
        current_section = "PREAMBULO"
        pattern = re.compile(r"\S[\s\S]*?(?=(?:\n\s*\n)|\Z)")

        for match in pattern.finditer(text):
            raw = match.group(0)
            normalized = raw.strip()
            if not normalized:
                continue

            start_offset = match.start() + (len(raw) - len(raw.lstrip()))
            end_offset = match.end() - (len(raw) - len(raw.rstrip()))
            header_candidate = normalized.splitlines()[0].strip().upper()
            if self._section_header_re.match(header_candidate):
                current_section = header_candidate

            unit: dict[str, Any] = {
                "text": normalized,
                "start_char": start_offset,
                "end_char": end_offset,
                "tokens": self.token_manager.estimate_tokens(normalized, model),
                "section": current_section,
            }

            if int(unit["tokens"]) > self.max_tokens:
                units.extend(self._hard_split_unit(unit, model))
            else:
                units.append(unit)

        return units

    def _get_overlap_unit_indices(self, unit_indices: list[int], units: list[dict[str, Any]]) -> list[int]:
        """Return tail unit indices that fit the configured overlap token budget."""
        selected: list[int] = []
        used_tokens = 0
        for idx in reversed(unit_indices):
            tok = int(units[idx]["tokens"])
            if used_tokens + tok > self.overlap_tokens:
                break
            selected.insert(0, idx)
            used_tokens += tok
        return selected

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

    def _hard_split_unit(self, unit: dict[str, Any], model: str) -> list[dict[str, Any]]:
        """Split oversized semantic unit preserving offsets and section hint."""
        text = str(unit["text"])
        base_start = int(unit["start_char"])
        section = str(unit.get("section") or "SEM_SECAO_DETECTADA")

        total_tokens = max(1, self.token_manager.estimate_tokens(text, model))
        chars_per_token = len(text) / total_tokens
        target_chars = max(200, int(self.max_tokens * chars_per_token * 0.9))

        split_units: list[dict[str, Any]] = []
        rel_start = 0
        while rel_start < len(text):
            rel_end = min(len(text), rel_start + target_chars)
            if rel_end < len(text):
                search_end = min(len(text), rel_end + 200)
                best_break = rel_end
                for marker in (". ", ".\n", "! ", "?\n", "\n"):
                    marker_idx = text.find(marker, rel_end, search_end)
                    if marker_idx != -1:
                        best_break = marker_idx + len(marker)
                        break
                rel_end = best_break

            chunk_text = text[rel_start:rel_end].strip()
            if chunk_text:
                split_units.append({
                    "text": chunk_text,
                    "start_char": base_start + rel_start,
                    "end_char": base_start + rel_end,
                    "tokens": self.token_manager.estimate_tokens(chunk_text, model),
                    "section": section,
                })
            rel_start = rel_end

        return split_units

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
        self.limits: dict[str, int] = dict(RATE_LIMIT_TPM)

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
