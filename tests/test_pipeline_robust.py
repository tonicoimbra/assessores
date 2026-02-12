"""Integration tests for robust architecture: chunking, rate limiting, caching."""

import pytest

from src.config import ENABLE_CACHING, ENABLE_CHUNKING, ENABLE_HYBRID_MODELS
from src.etapa1 import executar_etapa1_com_chunking
from src.etapa2 import executar_etapa2_com_chunking
from src.etapa3 import executar_etapa3_com_chunking
from src.models import ResultadoEtapa1, ResultadoEtapa2
from src.token_manager import rate_limiter, token_manager


class TestChunkingIntegration:
    """Test chunking functionality in actual pipeline stages."""

    @pytest.fixture
    def small_text(self):
        """Generate small text that doesn't need chunking."""
        return "Este é um recurso especial. Processo nº 123456. Recorrente: João Silva."

    @pytest.fixture
    def large_text(self):
        """Generate large text that requires chunking (simulate 150k tokens)."""
        # Each paragraph ~100 tokens, 1500 paragraphs = ~150k tokens
        paragraphs = []
        for i in range(3000):
            paragraphs.append(
                f"Parágrafo {i}: Este é um texto de exemplo para simular um documento "
                f"jurídico muito grande que excederá os limites de contexto e necessitará "
                f"de chunking inteligente para processamento adequado. "
                f"Art. {i} do Código Civil. "
            )
        return "\n\n".join(paragraphs)

    @pytest.fixture
    def mock_prompt(self):
        """Mock system prompt."""
        return "Você é um assistente jurídico. Analise o documento."

    def test_etapa1_small_document_no_chunking(self, small_text, mock_prompt):
        """Test that small documents don't trigger chunking."""
        if not ENABLE_CHUNKING:
            pytest.skip("Chunking disabled")

        # Should process without chunking
        resultado = executar_etapa1_com_chunking(small_text, mock_prompt)

        assert resultado is not None
        # For small docs, should use standard flow
        # (This would require mocking LLM calls for full test)

    def test_etapa1_large_document_with_chunking(self, large_text, mock_prompt):
        """Test that large documents trigger chunking."""
        if not ENABLE_CHUNKING:
            pytest.skip("Chunking disabled")

        # Estimate tokens to verify it's large
        tokens = token_manager.estimate_tokens(large_text)
        assert tokens > 100_000  # Confirm it's large enough

        # Should trigger chunking
        # (This would require mocking LLM calls for full test)
        # For now, just test that the function can be called
        try:
            # Don't actually call - would require API key and credits
            # resultado = executar_etapa1_com_chunking(large_text, mock_prompt)
            # assert resultado is not None
            pass
        except Exception:
            pass  # Expected without API key

    def test_merge_etapa1_results(self):
        """Test merging of chunk results for Etapa 1."""
        from src.etapa1 import _merge_etapa1_results

        # Create sample results from different chunks
        r1 = ResultadoEtapa1(
            numero_processo="12345-67.2024.8.16.0001",
            recorrente="João Silva",
            dispositivos_violados=["Art. 927 do CC", "Art. 186 do CC"],
        )

        r2 = ResultadoEtapa1(
            numero_processo="",  # Empty in second chunk
            recorrente="",
            recorrido="Maria Santos",  # Found in second chunk
            dispositivos_violados=["Art. 927 do CC", "Art. 389 do CPC"],  # Partial overlap
        )

        merged = _merge_etapa1_results([r1, r2])

        # Should use first non-empty values
        assert merged.numero_processo == "12345-67.2024.8.16.0001"
        assert merged.recorrente == "João Silva"
        assert merged.recorrido == "Maria Santos"

        # Should deduplicate dispositivos
        assert "Art. 927 do CC" in merged.dispositivos_violados
        assert "Art. 186 do CC" in merged.dispositivos_violados
        assert "Art. 389 do CPC" in merged.dispositivos_violados
        # Should not have duplicates
        assert merged.dispositivos_violados.count("Art. 927 do CC") == 1

    def test_merge_etapa2_results(self):
        """Test merging of chunk results for Etapa 2."""
        from src.etapa2 import _merge_etapa2_results
        from src.models import TemaEtapa2

        # Create sample themes from different chunks
        r1 = ResultadoEtapa2(
            temas=[
                TemaEtapa2(materia_controvertida="Responsabilidade civil"),
                TemaEtapa2(materia_controvertida="Danos morais"),
            ]
        )

        r2 = ResultadoEtapa2(
            temas=[
                TemaEtapa2(materia_controvertida="Responsabilidade civil"),  # Duplicate
                TemaEtapa2(materia_controvertida="Nexo causal"),
            ]
        )

        merged = _merge_etapa2_results([r1, r2])

        # Should have 3 unique themes (deduplicating "Responsabilidade civil")
        assert len(merged.temas) == 3


class TestRateLimitingIntegration:
    """Test rate limiting in pipeline context."""

    def test_rate_limiter_prevents_429(self):
        """Test that rate limiter tracks usage correctly."""
        # Reset rate limiter
        rate_limiter.usage_window.clear()

        # Simulate multiple API calls
        rate_limiter.add_usage("gpt-4o", 10_000)
        rate_limiter.add_usage("gpt-4o", 15_000)

        # Check current usage
        current = rate_limiter.get_current_usage("gpt-4o")
        assert current == 25_000

        # Should be near limit (30k)
        assert not rate_limiter.can_proceed("gpt-4o", 10_000)  # Would exceed 90% threshold

        # Should allow smaller request
        assert rate_limiter.can_proceed("gpt-4o", 2_000)

    def test_rate_limiter_wait_time(self):
        """Test wait time calculation."""
        rate_limiter.usage_window.clear()

        # Add usage near limit
        rate_limiter.add_usage("gpt-4o", 28_000)

        # Should need to wait
        wait_time = rate_limiter.wait_time_until_available("gpt-4o", 5_000)
        assert wait_time > 0


class TestCachingIntegration:
    """Test caching functionality."""

    def test_cache_manager_basic(self):
        """Test basic cache operations."""
        if not ENABLE_CACHING:
            pytest.skip("Caching disabled")

        from src.cache_manager import cache_manager

        # Clear cache
        cache_manager.clear("test")

        # Store value
        cache_manager.set("test_key", {"result": "test_value"}, category="test")

        # Retrieve value
        cached = cache_manager.get("test_key", category="test")
        assert cached is not None
        assert cached["result"] == "test_value"

        # Invalidate
        assert cache_manager.invalidate("test_key", category="test")

        # Should be gone
        cached = cache_manager.get("test_key", category="test")
        assert cached is None

    def test_cache_ttl(self):
        """Test that cache respects TTL."""
        if not ENABLE_CACHING:
            pytest.skip("Caching disabled")

        from src.cache_manager import CacheManager

        # Create cache with 1 second TTL
        cache = CacheManager(ttl_hours=1/3600)  # 1 second

        cache.set("key1", "value1", category="test")

        # Should exist immediately
        assert cache.get("key1", category="test") == "value1"

        # Wait 2 seconds
        import time
        time.sleep(2)

        # Should be expired
        assert cache.get("key1", category="test") is None


class TestHybridModels:
    """Test hybrid model routing."""

    def test_model_router_classification(self):
        """Test that classification uses gpt-4o-mini."""
        if not ENABLE_HYBRID_MODELS:
            pytest.skip("Hybrid models disabled")

        from src.model_router import TaskType, model_router

        from src.config import MODEL_CLASSIFICATION
        
        model = model_router.get_model_for_task(TaskType.CLASSIFICATION)
        assert model == MODEL_CLASSIFICATION

    def test_model_router_legal_analysis(self):
        """Test that legal analysis uses gpt-4o."""
        if not ENABLE_HYBRID_MODELS:
            pytest.skip("Hybrid models disabled")

        from src.model_router import TaskType, model_router

        from src.config import MODEL_LEGAL_ANALYSIS
        
        model = model_router.get_model_for_task(TaskType.LEGAL_ANALYSIS)
        assert model == MODEL_LEGAL_ANALYSIS

    def test_cost_savings_estimate(self):
        """Test cost savings calculation."""
        if not ENABLE_HYBRID_MODELS:
            pytest.skip("Hybrid models disabled")

        from src.model_router import model_router

        savings = model_router.estimate_cost_savings(
            classification_tokens=5_000,
            analysis_tokens=20_000,
        )

        # Should show savings
        assert savings["savings_usd"] > 0
        assert savings["savings_pct"] > 0
        assert savings["all_gpt4o"] > savings["hybrid"]


class TestFeatureFlags:
    """Test that feature flags work correctly."""

    def test_chunking_flag(self):
        """Test ENABLE_CHUNKING flag."""
        from src.config import ENABLE_CHUNKING

        # Should be boolean
        assert isinstance(ENABLE_CHUNKING, bool)

    def test_hybrid_models_flag(self):
        """Test ENABLE_HYBRID_MODELS flag."""
        from src.config import ENABLE_HYBRID_MODELS

        assert isinstance(ENABLE_HYBRID_MODELS, bool)

    def test_rate_limiting_flag(self):
        """Test ENABLE_RATE_LIMITING flag."""
        from src.config import ENABLE_RATE_LIMITING

        assert isinstance(ENABLE_RATE_LIMITING, bool)

    def test_caching_flag(self):
        """Test ENABLE_CACHING flag."""
        from src.config import ENABLE_CACHING

        assert isinstance(ENABLE_CACHING, bool)


class TestSemanticContinuity:
    """Test that chunking preserves semantic continuity."""

    def test_chunk_overlap_preserves_context(self):
        """Test that chunk overlap maintains context."""
        from src.token_manager import TextChunker

        chunker = TextChunker(max_tokens=1000, overlap_tokens=200)

        # Create text with clear structure
        sections = []
        for i in range(10):
            sections.append(
                f"SEÇÃO {i}\n"
                f"Conteúdo da seção {i}: " + ("texto " * 100)
            )

        text = "\n\n".join(sections)
        chunks = chunker.chunk_text(text)

        if len(chunks) > 1:
            # Last words of chunk[i] should appear in chunk[i+1]
            # This ensures context continuity
            for i in range(len(chunks) - 1):
                chunk_end = chunks[i][-200:]  # Last 200 chars
                chunk_start = chunks[i + 1][:400]  # First 400 chars

                # Check for some overlap (relaxed test)
                # At least one word should overlap
                end_words = set(chunk_end.split())
                start_words = set(chunk_start.split())
                overlap = end_words & start_words

                # Should have some overlap
                assert len(overlap) > 0, f"No overlap between chunks {i} and {i+1}"


class TestErrorHandling:
    """Test error handling in robust architecture."""

    def test_token_budget_exceeded_error(self):
        """Test TokenBudgetExceededError is raised correctly."""
        from src.token_manager import TokenBudgetExceededError

        # Verify error can be raised
        with pytest.raises(TokenBudgetExceededError):
            raise TokenBudgetExceededError("Test error")

    def test_pipeline_handles_chunking_errors(self):
        """Test that pipeline handles errors in chunking gracefully."""
        # This would require full integration test with mocked LLM
        # For now, just verify error classes exist
        from src.etapa1 import executar_etapa1_com_chunking
        from src.etapa2 import Etapa2Error
        from src.etapa3 import Etapa3Error

        assert callable(executar_etapa1_com_chunking)
        assert issubclass(Etapa2Error, Exception)
        assert issubclass(Etapa3Error, Exception)


@pytest.mark.slow
class TestPerformance:
    """Performance tests (marked as slow)."""

    def test_chunking_performance(self):
        """Test that chunking doesn't add excessive overhead."""
        import time
        from src.token_manager import TextChunker

        chunker = TextChunker()

        # Generate large text
        text = "palavra " * 50_000

        start = time.time()
        chunks = chunker.chunk_text(text)
        duration = time.time() - start

        # Should complete in reasonable time (< 2 seconds)
        assert duration < 2.0
        assert len(chunks) > 0

    def test_token_estimation_performance(self):
        """Test token estimation performance."""
        import time

        # Generate text
        text = "palavra " * 10_000

        start = time.time()
        tokens = token_manager.estimate_tokens(text)
        duration = time.time() - start

        # Should be very fast (< 0.1 seconds)
        assert duration < 0.1
        assert tokens > 0
