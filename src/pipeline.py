"""Pipeline orchestrator: coordinates all 3 stages of admissibility analysis."""

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from src.classifier import classificar_documentos
from src.config import (
    ENABLE_CHUNKING,
    ENABLE_PARALLEL_ETAPA2,
    OPENAI_MODEL,
    PROMPTS_DIR,
    MODEL_LEGAL_ANALYSIS,
    MODEL_DRAFT_GENERATION,
)


from src.etapa1 import executar_etapa1, executar_etapa1_com_chunking
from src.etapa2 import (
    executar_etapa2,
    executar_etapa2_com_chunking,
    executar_etapa2_paralelo,
)
from src.etapa3 import executar_etapa3, executar_etapa3_com_chunking
from src.llm_client import token_tracker
from src.models import (
    DocumentoEntrada,
    EstadoPipeline,
    MetadadosPipeline,
    ResultadoEtapa3,
    TipoDocumento,
)
from src.output_formatter import (
    formatar_minuta,
    gerar_relatorio_auditoria,
    salvar_minuta,
    salvar_minuta_docx,
)
from src.pdf_processor import extrair_texto
from src.state_manager import limpar_checkpoints, restaurar_estado, salvar_estado

logger = logging.getLogger("assessor_ai")


# --- 6.3 Global error handling ---

FRIENDLY_ERRORS: dict[str, str] = {
    "AuthenticationError": "❌ API key inválida ou expirada. Verifique OPENAI_API_KEY no .env",
    "RateLimitError": "⏳ Quota da API excedida. Aguarde alguns minutos e tente novamente.",
    "APITimeoutError": "⏰ Timeout na API. Verifique conexão ou aumente LLM_TIMEOUT no .env",
    "APIConnectionError": "🔌 Erro de conexão com a API. Verifique sua internet.",
    "PDFExtractionError": "📄 Erro ao processar PDF. Verifique se o arquivo é um PDF válido.",
    "FileNotFoundError": "📁 Arquivo não encontrado. Verifique o caminho informado.",
}


def _setup_file_logging() -> Path:
    """6.3.3 — Configure error logging to file."""
    log_dir = Path("outputs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "errors.log"

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.ERROR)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))

    root_logger = logging.getLogger("assessor_ai")
    if not any(isinstance(h, logging.FileHandler) for h in root_logger.handlers):
        root_logger.addHandler(file_handler)

    return log_path


def get_friendly_error(exc: Exception) -> str:
    """6.3.2 — Return a user-friendly error message."""
    exc_name = type(exc).__name__
    return FRIENDLY_ERRORS.get(exc_name, f"❌ Erro inesperado: {exc}")


def handle_pipeline_error(
    exc: Exception,
    estado: "EstadoPipeline | None" = None,
    processo_id: str = "default",
) -> None:
    """6.3.1 — Global error handler: save state and log."""
    logger.error("Pipeline error: %s", exc, exc_info=True)

    if estado:
        try:
            salvar_estado(estado, processo_id)
            logger.info("💾 Estado salvo antes do erro — use --continuar para retomar")
        except Exception:
            logger.error("Falha ao salvar estado de emergência")


# GPT-4o pricing (USD per 1M tokens, as of 2024)
PRICING = {
    # OpenAI models
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    # OpenRouter models
    "deepseek/deepseek-r1": {"input": 0.55, "output": 2.19},
    "deepseek/deepseek-chat-v3-0324:free": {"input": 0.00, "output": 0.00},
    "google/gemini-2.0-flash-001": {"input": 0.10, "output": 0.40},
    "google/gemini-2.5-flash-preview": {"input": 0.15, "output": 0.60},
    "qwen/qwen-2.5-72b-instruct": {"input": 0.12, "output": 0.39},
    "anthropic/claude-3.5-sonnet": {"input": 3.00, "output": 15.00},
}


def _carregar_prompt() -> str:
    """Load system prompt from file."""
    prompt_path = PROMPTS_DIR / "SYSTEM_PROMPT.md"
    if not prompt_path.exists():
        logger.warning("System prompt não encontrado em %s, usando default", prompt_path)
        return "Você é um assessor jurídico especializado em admissibilidade recursal."
    return prompt_path.read_text(encoding="utf-8")


def _estimar_custo(prompt_tokens: int, completion_tokens: int, modelo: str) -> float:
    """Estimate cost in USD based on token usage."""
    pricing = PRICING.get(modelo, PRICING["gpt-4o"])
    return (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000


ProgressCallback = Callable[[str, int, int], None]


def _default_progress(msg: str, step: int, total: int) -> None:
    """Default progress callback — logs to logger."""
    logger.info("[%d/%d] %s", step, total, msg)


class PipelineAdmissibilidade:
    """Orchestrates the full admissibility analysis pipeline."""

    def __init__(
        self,
        modelo: str | None = None,
        temperatura: float | None = None,
        saida_dir: str | None = None,
        formato_saida: str = "md",
        progress: ProgressCallback | None = None,
    ) -> None:
        self.modelo = modelo or OPENAI_MODEL
        self.temperatura = temperatura
        self.saida_dir = saida_dir
        if formato_saida not in {"md", "docx"}:
            raise ValueError("formato_saida deve ser 'md' ou 'docx'")
        self.formato_saida = formato_saida
        self.progress = progress or _default_progress
        self.prompt_sistema = _carregar_prompt()
        self.metricas: dict = {}

    def _notify(self, msg: str, step: int, total: int = 6) -> None:
        self.progress(msg, step, total)

    def executar(
        self,
        pdfs: list[str],
        processo_id: str = "default",
        continuar: bool = False,
    ) -> ResultadoEtapa3:
        """
        Execute the full pipeline: PDF→Classify→Etapa1→Etapa2→Etapa3→Output.

        Args:
            pdfs: List of PDF file paths.
            processo_id: Process identifier for checkpointing.
            continuar: If True, resume from saved checkpoint.

        Returns:
            ResultadoEtapa3 with complete draft and decision.
        """
        inicio = time.time()
        token_tracker.calls.clear()

        # 6.1.3 — Check for saved state
        estado: EstadoPipeline | None = None
        if continuar:
            estado = restaurar_estado(processo_id=processo_id)
            if estado:
                logger.info("📂 Retomando processamento do checkpoint")

        if estado is None:
            estado = EstadoPipeline(metadata=MetadadosPipeline(inicio=datetime.now()))

        total_steps = 6

        # Step 1: Extract text from PDFs
        if not estado.documentos_entrada:
            self._notify("Extraindo texto dos PDFs...", 1, total_steps)
            t0 = time.time()
            documentos = []
            for pdf_path in pdfs:
                resultado = extrair_texto(pdf_path)
                doc = DocumentoEntrada(
                    filepath=pdf_path,
                    texto_extraido=resultado.texto,
                    num_paginas=resultado.num_paginas,
                    num_caracteres=resultado.num_caracteres,
                )
                documentos.append(doc)
            estado.documentos_entrada = documentos
            self.metricas["tempo_extracao"] = time.time() - t0
            salvar_estado(estado, processo_id)

        # Step 2: Classify documents
        if all(d.tipo == TipoDocumento.DESCONHECIDO for d in estado.documentos_entrada):
            self._notify("Classificando documentos...", 2, total_steps)
            t0 = time.time()
            estado.documentos_entrada = classificar_documentos(estado.documentos_entrada)
            self.metricas["tempo_classificacao"] = time.time() - t0
            salvar_estado(estado, processo_id)

        # Identify recurso and acórdão texts
        texto_recurso = ""
        texto_acordao = ""
        for doc in estado.documentos_entrada:
            if doc.tipo == TipoDocumento.RECURSO:
                texto_recurso += doc.texto_extraido + "\n"
            elif doc.tipo == TipoDocumento.ACORDAO:
                texto_acordao += doc.texto_extraido + "\n"

        # Step 3: Etapa 1 — Appeal analysis
        if estado.resultado_etapa1 is None:
            self._notify("Etapa 1 — Analisando recurso...", 3, total_steps)
            t0 = time.time()
            # Record model used
            estado.metadata.modelos_utilizados["Etapa 1"] = MODEL_LEGAL_ANALYSIS

            # Import TokenBudgetExceededError for retry handling
            try:
                from src.token_manager import TokenBudgetExceededError
            except ImportError:
                TokenBudgetExceededError = Exception  # Fallback if not available

            # Use chunking-enabled version if feature is enabled
            executar_fn = executar_etapa1_com_chunking if ENABLE_CHUNKING else executar_etapa1

            try:
                # Pass user selected model as override
                estado.resultado_etapa1 = executar_fn(
                    texto_recurso, self.prompt_sistema, modelo_override=self.modelo
                )
            except TokenBudgetExceededError:
                logger.warning("⏳ Orçamento de tokens excedido na Etapa 1. Aguardando 60s para reset...")
                time.sleep(60)
                # Retry after wait
                estado.resultado_etapa1 = executar_fn(
                    texto_recurso, self.prompt_sistema, modelo_override=self.modelo
                )

            self.metricas["tempo_etapa1"] = time.time() - t0
            salvar_estado(estado, processo_id)

        # Step 4: Etapa 2 — Ruling analysis
        if estado.resultado_etapa2 is None:
            self._notify("Etapa 2 — Analisando acórdão...", 4, total_steps)
            t0 = time.time()
            # Record model used
            estado.metadata.modelos_utilizados["Etapa 2"] = MODEL_LEGAL_ANALYSIS

            # Import TokenBudgetExceededError for retry handling
            try:
                from src.token_manager import TokenBudgetExceededError
            except ImportError:
                TokenBudgetExceededError = Exception  # Fallback

            # Select execution mode based on feature flags
            # Priority: Parallel > Chunking > Standard
            if ENABLE_PARALLEL_ETAPA2 and not ENABLE_CHUNKING:
                executar_fn = executar_etapa2_paralelo
            elif ENABLE_CHUNKING:
                executar_fn = executar_etapa2_com_chunking
            else:
                executar_fn = executar_etapa2

            try:
                estado.resultado_etapa2 = executar_fn(
                    texto_acordao, estado.resultado_etapa1, self.prompt_sistema, modelo_override=self.modelo
                )
            except TokenBudgetExceededError:
                logger.warning("⏳ Orçamento de tokens excedido na Etapa 2. Aguardando 60s para reset...")
                time.sleep(60)
                # Retry after wait
                estado.resultado_etapa2 = executar_fn(
                    texto_acordao, estado.resultado_etapa1, self.prompt_sistema, modelo_override=self.modelo
                )

            self.metricas["tempo_etapa2"] = time.time() - t0
            salvar_estado(estado, processo_id)

        # Step 5: Etapa 3 — Draft generation
        if estado.resultado_etapa3 is None:
            self._notify("Etapa 3 — Gerando minuta...", 5, total_steps)
            t0 = time.time()
            # Record model used
            estado.metadata.modelos_utilizados["Etapa 3"] = MODEL_DRAFT_GENERATION

            # Import TokenBudgetExceededError for retry handling
            try:
                from src.token_manager import TokenBudgetExceededError
            except ImportError:
                TokenBudgetExceededError = Exception  # Fallback

            # Use chunking-enabled version if feature is enabled
            executar_fn = executar_etapa3_com_chunking if ENABLE_CHUNKING else executar_etapa3

            try:
                estado.resultado_etapa3 = executar_fn(
                    estado.resultado_etapa1,
                    estado.resultado_etapa2,
                    texto_acordao,
                    self.prompt_sistema,
                    modelo_override=self.modelo,
                )
            except TokenBudgetExceededError:
                logger.warning("⏳ Orçamento de tokens excedido na Etapa 3. Aguardando 60s para reset...")
                time.sleep(60)
                # Retry after wait
                estado.resultado_etapa3 = executar_fn(
                    estado.resultado_etapa1,
                    estado.resultado_etapa2,
                    texto_acordao,
                    self.prompt_sistema,
                    modelo_override=self.modelo,
                )

            self.metricas["tempo_etapa3"] = time.time() - t0
            salvar_estado(estado, processo_id)

        # Step 6: Format and save output
        self._notify("Formatando e salvando resultados...", 6, total_steps)

        # Collect metrics
        estado.metadata.fim = datetime.now()
        estado.metadata.modelo_usado = self.modelo
        estado.metadata.prompt_tokens = token_tracker.total_prompt_tokens
        estado.metadata.completion_tokens = token_tracker.total_completion_tokens
        estado.metadata.total_tokens = token_tracker.total_tokens

        self.metricas["tempo_total"] = time.time() - inicio
        self.metricas["tokens_totais"] = token_tracker.total_tokens
        self.metricas["custo_estimado_usd"] = _estimar_custo(
            token_tracker.total_prompt_tokens,
            token_tracker.total_completion_tokens,
            self.modelo,
        )

        # Format and save
        numero_proc = estado.resultado_etapa1.numero_processo or "sem_numero"
        minuta_fmt = formatar_minuta(estado.resultado_etapa3, estado)
        output_dir = Path(self.saida_dir) if self.saida_dir else None
        if self.formato_saida == "docx":
            minuta_path = salvar_minuta_docx(minuta_fmt, numero_proc, output_dir=output_dir)
        else:
            minuta_path = salvar_minuta(minuta_fmt, numero_proc, output_dir=output_dir)
        auditoria_path = gerar_relatorio_auditoria(
            estado,
            numero_processo=numero_proc,
            output_dir=output_dir,
        )
        self.metricas["arquivo_minuta"] = str(minuta_path)
        self.metricas["arquivo_auditoria"] = str(auditoria_path)

        # Save final state and cleanup
        salvar_estado(estado, processo_id)
        limpar_checkpoints(processo_id)

        logger.info(
            "✅ Pipeline concluído em %.1fs — %d tokens (~$%.4f)",
            self.metricas["tempo_total"],
            self.metricas["tokens_totais"],
            self.metricas["custo_estimado_usd"],
        )

        return estado.resultado_etapa3
