"""Model routing: intelligent task-to-model mapping for hybrid strategy."""

import logging
from enum import Enum

from src.config import (
    ENABLE_HYBRID_MODELS,
    MODEL_CLASSIFICATION,
    MODEL_DRAFT_GENERATION,
    MODEL_LEGAL_ANALYSIS,
    OPENAI_MODEL,
)

logger = logging.getLogger("assessor_ai")


class TaskType(str, Enum):
    """Types of tasks for model routing."""

    # Simple tasks - use GPT-4.1 mini for cost savings
    CLASSIFICATION = "classification"  # Document type classification
    PARSING = "parsing"  # Response parsing and extraction
    VALIDATION = "validation"  # Data validation checks

    # Critical tasks - use OPENAI_MODEL or O1_MODEL for accuracy
    LEGAL_ANALYSIS = "legal_analysis"  # Stages 1 & 2 analysis
    DRAFT_GENERATION = "draft_generation"  # Stage 3 draft generation


class ModelRouter:
    """
    Route tasks to appropriate models based on complexity and criticality.

    Hybrid Strategy:
    - Simple/auxiliary tasks → Mini / Fast model
    - Critical legal analysis → Advanced Model (e.g. GPT-4o, O1-mini)
    - Overall savings: 60-80% on total costs
    """

    def __init__(self):
        """Initialize router with model mapping."""
        self.model_mapping: dict[TaskType, str] = {
            # Simple tasks → mini
            TaskType.CLASSIFICATION: MODEL_CLASSIFICATION,
            TaskType.PARSING: MODEL_CLASSIFICATION,  # Same as classification
            TaskType.VALIDATION: MODEL_CLASSIFICATION,  # Same as classification

            # Critical tasks → Advanced Model
            TaskType.LEGAL_ANALYSIS: MODEL_LEGAL_ANALYSIS,
            TaskType.DRAFT_GENERATION: MODEL_DRAFT_GENERATION,
        }

        # Cost per 1M tokens (as of 2026)
        self.cost_per_1m = {
            # OpenAI models
            "gpt-4.1": {"input": 2.00, "output": 8.00},
            "gpt-4.1-mini": {"input": 0.15, "output": 0.60},
            "gpt-4o": {"input": 2.50, "output": 10.00},
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},
            "o1-preview": {"input": 15.00, "output": 60.00},
            "o1-mini": {"input": 3.00, "output": 12.00},
            # OpenRouter models
            "deepseek/deepseek-r1": {"input": 0.55, "output": 2.19},
            "deepseek/deepseek-chat-v3-0324:free": {"input": 0.00, "output": 0.00},
            "google/gemini-2.0-flash-001": {"input": 0.10, "output": 0.40},
            "google/gemini-2.5-flash-preview": {"input": 0.15, "output": 0.60},
            "qwen/qwen-2.5-72b-instruct": {"input": 0.12, "output": 0.39},
            "anthropic/claude-3.5-sonnet": {"input": 3.00, "output": 15.00},
        }

        self._log_cost_comparison()

    def get_model_for_task(self, task: TaskType) -> str:
        """
        Get appropriate model for a task type.

        Args:
            task: Type of task to be performed.

        Returns:
            Model name (e.g., "gpt-4.1" or "gpt-4.1-mini").
        """
        if not ENABLE_HYBRID_MODELS:
            # Hybrid strategy disabled - use default model
            logger.debug("Hybrid models disabled, using default: %s", OPENAI_MODEL)
            return OPENAI_MODEL

        model = self.model_mapping.get(task, OPENAI_MODEL)

        logger.debug(
            "Task routing: %s → %s (hybrid=%s)",
            task.value, model, ENABLE_HYBRID_MODELS,
        )

        return model

    def estimate_cost_savings(
        self,
        classification_tokens: int,
        analysis_tokens: int,
    ) -> dict[str, float]:
        """
        Estimate cost savings from hybrid strategy.

        Args:
            classification_tokens: Tokens used in classification/parsing tasks.
            analysis_tokens: Tokens used in legal analysis tasks.

        Returns:
            Dict with cost comparison: all_gpt41, hybrid, savings_usd, savings_pct.
        """
        # Assume 20% input, 80% output ratio
        input_ratio = 0.2
        output_ratio = 0.8

        # Custo do modelo default vs modelo fallback (se híbrido)
        cost_all_default = (
            (classification_tokens * input_ratio * self.cost_per_1m.get(OPENAI_MODEL, self.cost_per_1m["gpt-4.1"])["input"] / 1_000_000)
            + (classification_tokens * output_ratio * self.cost_per_1m.get(OPENAI_MODEL, self.cost_per_1m["gpt-4.1"])["output"] / 1_000_000)
            + (analysis_tokens * input_ratio * self.cost_per_1m.get(OPENAI_MODEL, self.cost_per_1m["gpt-4.1"])["input"] / 1_000_000)
            + (analysis_tokens * output_ratio * self.cost_per_1m.get(OPENAI_MODEL, self.cost_per_1m["gpt-4.1"])["output"] / 1_000_000)
        )

        cost_hybrid = (
            (classification_tokens * input_ratio * self.cost_per_1m.get(MODEL_CLASSIFICATION, self.cost_per_1m["gpt-4.1-mini"])["input"] / 1_000_000)
            + (classification_tokens * output_ratio * self.cost_per_1m.get(MODEL_CLASSIFICATION, self.cost_per_1m["gpt-4.1-mini"])["output"] / 1_000_000)
            + (analysis_tokens * input_ratio * self.cost_per_1m.get(MODEL_LEGAL_ANALYSIS, self.cost_per_1m["gpt-4.1"])["input"] / 1_000_000)
            + (analysis_tokens * output_ratio * self.cost_per_1m.get(MODEL_LEGAL_ANALYSIS, self.cost_per_1m["gpt-4.1"])["output"] / 1_000_000)
        )

        savings_usd = cost_all_default - cost_hybrid
        savings_pct = (savings_usd / cost_all_default * 100) if cost_all_default > 0 else 0

        return {
            "all_default": round(cost_all_default, 4),
            "hybrid": round(cost_hybrid, 4),
            "savings_usd": round(savings_usd, 4),
            "savings_pct": round(savings_pct, 1),
        }

    def _log_cost_comparison(self) -> None:
        """Log cost comparison between models."""
        if not ENABLE_HYBRID_MODELS:
            logger.debug("Hybrid model strategy disabled")
            return

        logger.info("💰 Hybrid model strategy enabled:")
        logger.info("  • Classification/Parsing: %s (menor custo)", MODEL_CLASSIFICATION)
        logger.info("  • Legal Analysis: %s (maior rigor)", MODEL_LEGAL_ANALYSIS)
        logger.info("  • Draft Generation: %s (alta qualidade)", MODEL_DRAFT_GENERATION)
        logger.info("  • Expected savings: 60-80%% on auxiliary tasks")


# Global router instance
model_router = ModelRouter()


def get_model_for_task(task: TaskType) -> str:
    """
    Convenience function to get model for a task.

    Args:
        task: Task type.

    Returns:
        Model name.
    """
    return model_router.get_model_for_task(task)
