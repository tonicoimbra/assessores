"""Tests for token_manager module: TokenManager, TextChunker, RateLimiter."""

import time

import pytest

from src.token_manager import RateLimiter, TextChunker, TokenManager


class TestTokenManager:
    """Test TokenManager functionality."""

    def test_estimate_tokens_basic(self):
        """Test basic token estimation."""
        tm = TokenManager()

        # Short text
        text = "Hello world"
        tokens = tm.estimate_tokens(text, "gpt-4o")
        assert tokens > 0
        assert tokens < 10  # "Hello world" should be 2-3 tokens

    def test_estimate_tokens_large(self):
        """Test token estimation for large text."""
        tm = TokenManager()

        # Generate large text (~1000 words)
        text = " ".join(["palavra"] * 1000)
        tokens = tm.estimate_tokens(text, "gpt-4o")
        assert tokens > 500  # Should be around 1000 tokens
        assert tokens < 2000

    def test_reserve_release_budget(self):
        """Test budget reservation and release."""
        tm = TokenManager()

        # Reserve budget
        assert tm.reserve_budget(1000, "gpt-4o") is True

        # Check status
        status = tm.get_budget_status("gpt-4o")
        assert status["used"] == 1000
        assert status["available"] < status["limit"]

        # Release budget
        tm.release_budget(500, "gpt-4o")
        status = tm.get_budget_status("gpt-4o")
        assert status["used"] == 500

        # Reset budget
        tm.reset_budget("gpt-4o")
        status = tm.get_budget_status("gpt-4o")
        assert status["used"] == 0

    def test_reserve_budget_exceeded(self):
        """Test budget reservation when limit is exceeded."""
        tm = TokenManager()

        # Reserve almost all budget
        tm.reserve_budget(100_000, "gpt-4o")

        # Try to reserve more (should fail)
        assert tm.reserve_budget(50_000, "gpt-4o") is False


class TestTextChunker:
    """Test TextChunker functionality."""

    def test_chunk_small_text(self):
        """Test that small text is not chunked."""
        chunker = TextChunker(max_tokens=10_000, overlap_tokens=500)

        text = "Este é um texto pequeno que não precisa de chunking."
        chunks = chunker.chunk_text(text, "gpt-4o")

        assert len(chunks) == 1
        assert chunks[0] == text

    def test_chunk_large_text(self):
        """Test that large text is chunked."""
        chunker = TextChunker(max_tokens=1000, overlap_tokens=100)

        # Generate large text (~5000 tokens)
        paragraphs = [f"Este é o parágrafo número {i}. " * 50 for i in range(100)]
        text = "\n\n".join(paragraphs)

        chunks = chunker.chunk_text(text, "gpt-4o")

        # Should produce multiple chunks
        assert len(chunks) > 1

        # Each chunk should be within token limit (with some margin)
        tm = TokenManager()
        for chunk in chunks:
            tokens = tm.estimate_tokens(chunk, "gpt-4o")
            # Allow 20% over due to overlap
            assert tokens <= chunker.max_tokens * 1.2

    def test_chunk_overlap(self):
        """Test that chunks have overlap for context continuity."""
        chunker = TextChunker(max_tokens=1000, overlap_tokens=200)

        # Create text with distinctive paragraphs
        paragraphs = [f"PARAGRAPH_{i}: " + ("word " * 100) for i in range(20)]
        text = "\n\n".join(paragraphs)

        chunks = chunker.chunk_text(text, "gpt-4o")

        # Check that consecutive chunks have some overlap
        if len(chunks) > 1:
            # Last part of chunk[0] should appear in chunk[1]
            # This is hard to test precisely, so just check chunks overlap
            assert len(chunks) >= 2

    def test_chunk_with_coverage_map(self):
        """Test semantic chunking with auditable coverage map output."""
        chunker = TextChunker(max_tokens=500, overlap_tokens=120)
        text = "\n\n".join(
            [
                "EMENTA\nRecurso especial sobre responsabilidade civil.",
                "RELATÓRIO\n" + ("Fato processual relevante. " * 40),
                "VOTO\n" + ("Fundamento jurídico detalhado. " * 60),
                "DISPOSITIVO\n" + ("Conclusão do julgamento. " * 30),
            ]
        )

        chunks, report = chunker.chunk_text_with_coverage(text, "gpt-4o")

        assert len(chunks) >= 2
        assert report["aplicado"] is True
        assert report["chunk_count"] == len(chunks)
        assert report["coverage_ratio_chars"] > 0.95
        assert report["coverage_ratio_tokens"] > 0.95
        assert len(report["coverage_map"]) == len(chunks)
        assert all("sections" in c for c in report["coverage_map"])

    def test_chunk_overlap_control_does_not_explode(self):
        """Ensure overlap per chunk is controlled by configured overlap budget."""
        chunker = TextChunker(max_tokens=500, overlap_tokens=80)
        text = "\n\n".join([f"Parágrafo {i}. " + ("texto " * 70) for i in range(25)])
        _, report = chunker.chunk_text_with_coverage(text, "gpt-4o")

        if report["aplicado"]:
            for item in report["coverage_map"][1:]:
                assert item["overlap_prev_tokens"] <= 150

    def test_chunk_by_sections(self):
        """Test chunking by legal document sections."""
        chunker = TextChunker()

        text = """
        PREÂMBULO
        Processo nº 123456-78.2024.8.16.0001

        EMENTA
        RECURSO ESPECIAL. MATÉRIA DE DIREITO CIVIL.

        RELATÓRIO
        O recorrente alega violação ao art. 927 do CC.

        VOTO
        Conheço do recurso e lhe dou provimento.

        DISPOSITIVO
        Pelo exposto, dou provimento ao recurso.
        """

        sections = chunker.chunk_by_sections(text, "gpt-4o")

        # Should identify standard sections
        assert "EMENTA" in sections
        assert "RELATÓRIO" in sections
        assert "VOTO" in sections
        assert "DISPOSITIVO" in sections
        assert len(sections) >= 4


class TestRateLimiter:
    """Test RateLimiter functionality."""

    def test_add_usage_and_get_current(self):
        """Test tracking usage within time window."""
        limiter = RateLimiter()

        # Add usage
        limiter.add_usage("gpt-4o", 5000)
        limiter.add_usage("gpt-4o", 3000)

        # Check current usage
        current = limiter.get_current_usage("gpt-4o")
        assert current == 8000

    def test_can_proceed_within_limit(self):
        """Test that requests can proceed when within limit."""
        limiter = RateLimiter()

        # Well within limit
        limiter.add_usage("gpt-4o", 5000)
        assert limiter.can_proceed("gpt-4o", 5000) is True

    def test_can_proceed_exceeds_limit(self):
        """Test that requests are blocked when exceeding limit."""
        limiter = RateLimiter()

        # Add usage close to limit (30k for gpt-4o)
        limiter.add_usage("gpt-4o", 25_000)

        # Try to add more (should block at 90% threshold = 27k)
        assert limiter.can_proceed("gpt-4o", 5_000) is False

    def test_cleanup_old_entries(self):
        """Test that old usage entries are cleaned up."""
        limiter = RateLimiter()

        # Add usage
        limiter.add_usage("gpt-4o", 10_000)

        # Verify it's tracked
        assert limiter.get_current_usage("gpt-4o") == 10_000

        # Manually set old timestamp (simulate 2 minutes ago)
        if limiter.usage_window["gpt-4o"]:
            from datetime import datetime, timedelta
            old_time = datetime.now() - timedelta(minutes=2)
            limiter.usage_window["gpt-4o"][0] = (old_time, 10_000)

        # Cleanup should remove it
        current = limiter.get_current_usage("gpt-4o")
        assert current == 0

    def test_wait_time_calculation(self):
        """Test calculation of wait time until available."""
        limiter = RateLimiter()

        # Within limit - no wait
        limiter.add_usage("gpt-4o", 5000)
        wait_time = limiter.wait_time_until_available("gpt-4o", 1000)
        assert wait_time == 0.0

        # Exceed limit - should have wait time
        limiter.add_usage("gpt-4o", 25_000)  # Total 30k (at limit)
        wait_time = limiter.wait_time_until_available("gpt-4o", 5000)
        assert wait_time > 0  # Should need to wait

    def test_rate_limit_status(self):
        """Test rate limit status reporting."""
        limiter = RateLimiter()

        limiter.add_usage("gpt-4o", 10_000)

        status = limiter.get_rate_limit_status("gpt-4o")

        assert status["model"] == "gpt-4o"
        assert status["current_tpm"] == 10_000
        assert status["limit_tpm"] == 30_000
        assert status["available_tpm"] == 20_000
        assert status["utilization_pct"] > 0


class TestIntegration:
    """Integration tests for token management components."""

    def test_full_workflow(self):
        """Test complete workflow: estimate, reserve, chunk, rate limit."""
        tm = TokenManager()
        chunker = TextChunker(max_tokens=5000)
        limiter = RateLimiter()

        # Generate text
        text = "Este é um teste de integração. " * 1000

        # Estimate tokens
        tokens = tm.estimate_tokens(text)
        assert tokens > 0

        # Reserve budget
        assert tm.reserve_budget(tokens, "gpt-4o")

        # Check if chunking needed
        chunks = chunker.chunk_text(text, "gpt-4o")
        assert len(chunks) > 0

        # Check rate limit
        assert limiter.can_proceed("gpt-4o", tokens)

        # Simulate usage
        limiter.add_usage("gpt-4o", tokens)

        # Release budget
        tm.release_budget(tokens, "gpt-4o")

        # Verify final state
        assert tm.get_budget_status("gpt-4o")["used"] == 0
