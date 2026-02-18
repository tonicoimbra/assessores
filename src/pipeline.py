"""Pipeline orchestrator: coordinates all 3 stages of admissibility analysis."""

import json
import logging
import inspect
import time
from datetime import datetime
from pathlib import Path
from typing import Callable
from typing import Any

from src.classifier import classificar_documentos, validar_classificacao_documentos
from src.config import (
    CONFIDENCE_THRESHOLD_FIELD,
    CONFIDENCE_THRESHOLD_GLOBAL,
    CONFIDENCE_THRESHOLD_THEME,
    ENABLE_CHUNKING,
    ENABLE_CONFIDENCE_ESCALATION,
    ENABLE_FAIL_CLOSED,
    ENABLE_PARALLEL_ETAPA2,
    MIN_ACORDAO_COUNT,
    OPENAI_MODEL,
    PROMPT_PROFILE,
    REQUIRE_EXACTLY_ONE_RECURSO,
    MODEL_LEGAL_ANALYSIS,
    MODEL_DRAFT_GENERATION,
)


from src.dead_letter_queue import salvar_dead_letter
from src.etapa1 import executar_etapa1, executar_etapa1_com_chunking
from src.etapa2 import (
    executar_etapa2,
    executar_etapa2_com_chunking,
    executar_etapa2_paralelo,
)
from src.etapa3 import executar_etapa3, executar_etapa3_com_chunking
from src.llm_client import token_tracker
from src.models import (
    Decisao,
    DocumentoEntrada,
    EstadoPipeline,
    MetadadosPipeline,
    ResultadoEtapa1,
    ResultadoEtapa2,
    ResultadoEtapa3,
    TipoDocumento,
)
from src.output_formatter import (
    formatar_minuta,
    gerar_relatorio_auditoria,
    salvar_snapshot_execucao_json,
    salvar_trilha_auditoria_json,
    salvar_minuta,
    salvar_minuta_docx,
)
from src.pdf_processor import extrair_texto
from src.prompt_loader import ensure_prompt_contract, get_pipeline_prompt_signature
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
    "DocumentClassificationError": (
        "📚 Não foi possível validar os tipos de documento de entrada. "
        "Envie exatamente 1 recurso e ao menos 1 acórdão."
    ),
    "PromptConfigurationError": (
        "🧩 Configuração de prompt inválida. "
        "Verifique os arquivos em prompts/ e a flag ALLOW_MINIMAL_PROMPT_FALLBACK."
    ),
    "PipelineValidationError": (
        "🧪 O pipeline interrompeu por inconsistência de qualidade dos dados. "
        "Revise os documentos e tente novamente."
    ),
}


class PipelineValidationError(Exception):
    """Raised when fail-closed validations detect inconsistent stage outputs."""


BLOQUEIO_CODIGOS: dict[str, str] = {
    "E1_INCONCLUSIVA": "Etapa 1 inconclusiva, execução bloqueada antes da Etapa 2.",
    "E2_VALIDACAO_FAIL": "Etapa 2 inválida em política fail-closed.",
    "E3_VALIDACAO_FAIL": "Etapa 3 inválida em política fail-closed.",
    "E3_INCONCLUSIVO": "Decisão final inconclusiva com aviso explícito.",
}

CRITICAL_FIELDS_ETAPA1: tuple[str, ...] = ("numero_processo", "recorrente", "especie_recurso")
ESSENTIAL_FIELDS_ETAPA2: tuple[str, ...] = (
    "materia_controvertida",
    "conclusao_fundamentos",
    "obices_sumulas",
    "trecho_transcricao",
)


def _definir_motivo_bloqueio(
    estado: EstadoPipeline,
    codigo: str,
    descricao: str | None = None,
) -> None:
    """Persist standardized block reason in pipeline metadata."""
    estado.metadata.motivo_bloqueio_codigo = codigo.strip()
    estado.metadata.motivo_bloqueio_descricao = (
        (descricao or "").strip()
        or BLOQUEIO_CODIGOS.get(codigo.strip(), "")
    )


def _validar_etapa1(resultado: ResultadoEtapa1) -> list[str]:
    """Return mandatory Stage 1 validation errors."""
    erros: list[str] = []
    if resultado.inconclusivo:
        motivo = resultado.motivo_inconclusivo or "sem motivo informado"
        erros.append(f"Etapa 1 marcada como inconclusiva: {motivo}")
    if not resultado.numero_processo:
        erros.append("Etapa 1 sem numero_processo.")
    if not resultado.recorrente:
        erros.append("Etapa 1 sem recorrente.")
    if not resultado.especie_recurso:
        erros.append("Etapa 1 sem especie_recurso.")

    for campo in ("numero_processo", "recorrente", "especie_recurso"):
        valor = str(getattr(resultado, campo, "") or "").strip()
        if not valor:
            continue
        evidencia = resultado.evidencias_campos.get(campo)
        if evidencia is None:
            erros.append(f"Etapa 1 sem evidência para {campo}.")
            continue
        if not evidencia.citacao_literal.strip():
            erros.append(f"Etapa 1 sem citação literal da evidência para {campo}.")
        if evidencia.pagina is None or evidencia.pagina < 1:
            erros.append(f"Etapa 1 sem página válida da evidência para {campo}.")
        if not evidencia.ancora.strip():
            erros.append(f"Etapa 1 sem âncora da evidência para {campo}.")
        if resultado.verificacao_campos.get(campo) is not True:
            erros.append(f"Etapa 1 sem verificação independente positiva para {campo}.")
    return erros


def _validar_etapa2(resultado: ResultadoEtapa2) -> list[str]:
    """Return mandatory Stage 2 validation errors."""
    erros: list[str] = []
    if not resultado.temas:
        erros.append("Etapa 2 sem temas identificados.")
        return erros

    campos_essenciais = (
        "materia_controvertida",
        "conclusao_fundamentos",
        "obices_sumulas",
        "trecho_transcricao",
    )

    for idx, tema in enumerate(resultado.temas, 1):
        if not tema.materia_controvertida:
            erros.append(f"Etapa 2 tema {idx} sem materia_controvertida.")
        if not tema.conclusao_fundamentos:
            erros.append(f"Etapa 2 tema {idx} sem conclusao_fundamentos.")
        if not tema.obices_sumulas:
            erros.append(f"Etapa 2 tema {idx} sem obices_sumulas.")
        if not tema.trecho_transcricao:
            erros.append(f"Etapa 2 tema {idx} sem trecho_transcricao.")

        for campo in campos_essenciais:
            valor_presente = False
            if campo == "obices_sumulas":
                valor_presente = bool(tema.obices_sumulas)
            else:
                valor_presente = bool(str(getattr(tema, campo, "") or "").strip())

            if not valor_presente:
                continue

            evidencia = tema.evidencias_campos.get(campo)
            if evidencia is None:
                erros.append(f"Etapa 2 tema {idx} sem evidência para {campo}.")
                continue
            if not evidencia.citacao_literal.strip():
                erros.append(f"Etapa 2 tema {idx} sem citação literal da evidência para {campo}.")
            if evidencia.pagina is None or evidencia.pagina < 1:
                erros.append(f"Etapa 2 tema {idx} sem página válida da evidência para {campo}.")
            if not evidencia.ancora.strip():
                erros.append(f"Etapa 2 tema {idx} sem âncora da evidência para {campo}.")
    return erros


def _validar_etapa3(resultado: ResultadoEtapa3) -> list[str]:
    """Return mandatory Stage 3 validation errors."""
    erros: list[str] = []
    if not resultado.minuta_completa.strip():
        erros.append("Etapa 3 sem minuta_completa.")
    if resultado.decisao in {Decisao.ADMITIDO, Decisao.INADMITIDO}:
        pass
    elif resultado.decisao == Decisao.INCONCLUSIVO:
        minuta_upper = resultado.minuta_completa.upper()
        aviso_ok = resultado.aviso_inconclusivo or ("AVISO" in minuta_upper and "INCONCLUS" in minuta_upper)
        if not aviso_ok:
            erros.append("Etapa 3 inconclusiva sem aviso explícito na minuta.")
        if not resultado.motivo_bloqueio_codigo.strip():
            erros.append("Etapa 3 inconclusiva sem motivo_bloqueio_codigo padronizado.")
        if not resultado.motivo_bloqueio_descricao.strip():
            erros.append("Etapa 3 inconclusiva sem motivo_bloqueio_descricao padronizado.")
    else:
        erros.append("Etapa 3 sem decisão estruturada (ADMITIDO/INADMITIDO/INCONCLUSIVO).")

    if not resultado.fundamentos_decisao:
        erros.append("Etapa 3 sem fundamentos_decisao estruturados.")
    if not resultado.itens_evidencia_usados:
        erros.append("Etapa 3 sem itens_evidencia_usados estruturados.")
    return erros


def _score_confianca_etapa(
    *,
    total_checks: int,
    total_erros: int,
    inconclusivo: bool = False,
) -> float:
    """Compute stage confidence score (0..1) with progressive penalties."""
    checks = max(total_checks, 1)
    ratio_erros = min(1.0, total_erros / checks)
    penalidade_erros = min(1.0, (ratio_erros ** 1.35) * 1.15)
    score = 1.0 - penalidade_erros
    if inconclusivo:
        score -= 0.35
    return round(max(0.0, min(1.0, score)), 3)


def _score_boolean_checks(checks: list[bool], inconclusivo: bool = False) -> float:
    """Compute confidence score from boolean checks (True=pass, False=error)."""
    total = max(len(checks), 1)
    erros = sum(1 for ok in checks if not ok)
    return _score_confianca_etapa(
        total_checks=total,
        total_erros=erros,
        inconclusivo=inconclusivo,
    )


def _calcular_confianca_campos_etapa1(resultado: ResultadoEtapa1 | None) -> dict[str, float]:
    """Compute confidence per critical Stage 1 field."""
    if resultado is None:
        return {}

    confiancas: dict[str, float] = {}
    for campo in CRITICAL_FIELDS_ETAPA1:
        valor = str(getattr(resultado, campo, "") or "").strip()
        if not valor:
            confiancas[campo] = 0.0
            continue

        evidencia = resultado.evidencias_campos.get(campo)
        checks: list[bool] = [
            True,  # valor presente
            evidencia is not None,
            bool(evidencia and evidencia.citacao_literal.strip()),
            bool(evidencia and evidencia.pagina is not None and evidencia.pagina >= 1),
            bool(evidencia and evidencia.ancora.strip()),
            resultado.verificacao_campos.get(campo) is True,
        ]
        confiancas[campo] = _score_boolean_checks(checks, inconclusivo=resultado.inconclusivo)

    return confiancas


def _calcular_confianca_temas_etapa2(resultado: ResultadoEtapa2 | None) -> dict[str, float]:
    """Compute confidence per Stage 2 theme."""
    if resultado is None:
        return {}

    confiancas: dict[str, float] = {}
    for idx, tema in enumerate(resultado.temas, 1):
        checks: list[bool] = []
        for campo in ESSENTIAL_FIELDS_ETAPA2:
            if campo == "obices_sumulas":
                valor_presente = bool(tema.obices_sumulas)
            else:
                valor_presente = bool(str(getattr(tema, campo, "") or "").strip())
            checks.append(valor_presente)

            if not valor_presente:
                checks.extend([False, False, False, False])
                continue

            evidencia = tema.evidencias_campos.get(campo)
            checks.append(evidencia is not None)
            checks.append(bool(evidencia and evidencia.citacao_literal.strip()))
            checks.append(bool(evidencia and evidencia.pagina is not None and evidencia.pagina >= 1))
            checks.append(bool(evidencia and evidencia.ancora.strip()))

        confiancas[f"tema_{idx}"] = _score_boolean_checks(checks)

    return confiancas


def _avaliar_politica_escalonamento(
    *,
    confianca_global: float,
    confianca_campos_etapa1: dict[str, float],
    confianca_temas_etapa2: dict[str, float],
) -> dict[str, Any]:
    """Evaluate confidence escalation policy for human review recommendation."""
    thresholds = {
        "global": round(CONFIDENCE_THRESHOLD_GLOBAL, 3),
        "campo": round(CONFIDENCE_THRESHOLD_FIELD, 3),
        "tema": round(CONFIDENCE_THRESHOLD_THEME, 3),
    }

    if not ENABLE_CONFIDENCE_ESCALATION:
        return {
            "ativo": False,
            "escalonar": False,
            "thresholds": thresholds,
            "motivos": [],
        }

    motivos: list[str] = []
    if confianca_global < CONFIDENCE_THRESHOLD_GLOBAL:
        motivos.append(
            f"Confianca global {confianca_global:.3f} abaixo do threshold {CONFIDENCE_THRESHOLD_GLOBAL:.3f}."
        )

    for campo, score in sorted(confianca_campos_etapa1.items()):
        if score < CONFIDENCE_THRESHOLD_FIELD:
            motivos.append(
                f"Etapa 1 campo '{campo}' com confianca {score:.3f} abaixo do threshold "
                f"{CONFIDENCE_THRESHOLD_FIELD:.3f}."
            )

    for tema, score in sorted(confianca_temas_etapa2.items()):
        if score < CONFIDENCE_THRESHOLD_THEME:
            motivos.append(
                f"Etapa 2 {tema} com confianca {score:.3f} abaixo do threshold "
                f"{CONFIDENCE_THRESHOLD_THEME:.3f}."
            )

    return {
        "ativo": True,
        "escalonar": bool(motivos),
        "thresholds": thresholds,
        "motivos": motivos,
    }


def _calcular_confiancas_pipeline(
    estado: EstadoPipeline,
) -> tuple[dict[str, float], float, dict[str, list[str]]]:
    """Compute confidence per stage and global confidence for auditability."""
    confiancas: dict[str, float] = {"etapa1": 0.0, "etapa2": 0.0, "etapa3": 0.0}
    validacoes: dict[str, list[str]] = {"etapa1": [], "etapa2": [], "etapa3": []}

    r1 = estado.resultado_etapa1
    if r1 is None:
        validacoes["etapa1"] = ["Etapa 1 não executada."]
        confiancas["etapa1"] = 0.0
    else:
        erros_e1 = _validar_etapa1(r1)
        validacoes["etapa1"] = erros_e1
        checks_e1 = 3 + sum(
            4 for campo in ("numero_processo", "recorrente", "especie_recurso")
            if str(getattr(r1, campo, "") or "").strip()
        )
        if r1.inconclusivo:
            checks_e1 += 1
        confiancas["etapa1"] = _score_confianca_etapa(
            total_checks=checks_e1,
            total_erros=len(erros_e1),
            inconclusivo=r1.inconclusivo,
        )

    r2 = estado.resultado_etapa2
    if r2 is None:
        validacoes["etapa2"] = ["Etapa 2 não executada."]
        confiancas["etapa2"] = 0.0
    else:
        erros_e2 = _validar_etapa2(r2)
        validacoes["etapa2"] = erros_e2
        checks_e2 = max(1, len(r2.temas)) * 8  # 4 campos essenciais + 4 evidências por tema.
        confiancas["etapa2"] = _score_confianca_etapa(
            total_checks=checks_e2,
            total_erros=len(erros_e2),
        )

    r3 = estado.resultado_etapa3
    if r3 is None:
        validacoes["etapa3"] = ["Etapa 3 não executada."]
        confiancas["etapa3"] = 0.0
    else:
        erros_e3 = _validar_etapa3(r3)
        validacoes["etapa3"] = erros_e3
        checks_e3 = 4 + (1 if r3.decisao == Decisao.INCONCLUSIVO else 0)
        confiancas["etapa3"] = _score_confianca_etapa(
            total_checks=checks_e3,
            total_erros=len(erros_e3),
            inconclusivo=(r3.decisao == Decisao.INCONCLUSIVO),
        )

    pesos = {"etapa1": 0.35, "etapa2": 0.35, "etapa3": 0.30}
    etapas_executadas = [
        etapa for etapa, resultado in (
            ("etapa1", r1),
            ("etapa2", r2),
            ("etapa3", r3),
        ) if resultado is not None
    ]
    if not etapas_executadas:
        return confiancas, 0.0, validacoes

    peso_total = sum(pesos[e] for e in etapas_executadas)
    score_global = sum(confiancas[e] * pesos[e] for e in etapas_executadas) / peso_total
    if r3 is not None and r3.decisao == Decisao.INCONCLUSIVO:
        score_global = min(score_global, 0.49)
    return confiancas, round(max(0.0, min(1.0, score_global)), 3), validacoes


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


def _build_structured_log_event(
    *,
    evento: str,
    processo_id: str,
    execucao_id: str,
    etapa: str,
    extra: dict | None = None,
) -> dict:
    """Build structured JSON log payload with correlation fields."""
    payload = {
        "evento": evento,
        "processo_id": processo_id,
        "execucao_id": execucao_id,
        "etapa": etapa,
        "timestamp": datetime.now().isoformat(),
    }
    if extra:
        payload.update(extra)
    return payload


def _log_structured_event(
    *,
    evento: str,
    processo_id: str,
    execucao_id: str,
    etapa: str,
    extra: dict | None = None,
) -> None:
    """Emit structured JSON event for observability/correlation."""
    payload = _build_structured_log_event(
        evento=evento,
        processo_id=processo_id,
        execucao_id=execucao_id,
        etapa=etapa,
        extra=extra,
    )
    logger.info("EVENTO_JSON %s", json.dumps(payload, ensure_ascii=False, sort_keys=True))


def get_friendly_error(exc: Exception) -> str:
    """6.3.2 — Return a user-friendly error message."""
    exc_name = type(exc).__name__
    return FRIENDLY_ERRORS.get(exc_name, f"❌ Erro inesperado: {exc}")


def handle_pipeline_error(
    exc: Exception,
    estado: "EstadoPipeline | None" = None,
    processo_id: str = "default",
    metricas: dict[str, Any] | None = None,
    contexto: dict[str, Any] | None = None,
) -> Path | None:
    """6.3.1 — Global error handler: save state and log."""
    logger.error("Pipeline error: %s", exc, exc_info=True)
    dlq_path: Path | None = None

    if estado:
        try:
            salvar_estado(estado, processo_id)
            logger.info("💾 Estado salvo antes do erro — use --continuar para retomar")
        except Exception:
            logger.error("Falha ao salvar estado de emergência")

    try:
        dlq_path = salvar_dead_letter(
            exc,
            processo_id=processo_id,
            estado=estado,
            metricas=metricas,
            contexto=contexto,
        )
    except Exception:
        logger.error("Falha ao persistir snapshot na dead-letter queue", exc_info=True)

    if dlq_path:
        logger.info("📮 Snapshot de falha salvo na DLQ: %s", dlq_path)
    return dlq_path


# GPT-4o pricing (USD per 1M tokens, as of 2024)
PRICING = {
    # OpenAI models
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1": {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini": {"input": 0.15, "output": 0.60},
    # OpenRouter models
    "deepseek/deepseek-r1": {"input": 0.55, "output": 2.19},
    "deepseek/deepseek-chat-v3-0324:free": {"input": 0.00, "output": 0.00},
    "google/gemini-2.0-flash-001": {"input": 0.10, "output": 0.40},
    "google/gemini-2.5-flash-preview": {"input": 0.15, "output": 0.60},
    "qwen/qwen-2.5-72b-instruct": {"input": 0.12, "output": 0.39},
    "anthropic/claude-3.5-sonnet": {"input": 3.00, "output": 15.00},
}


def _estimar_custo(prompt_tokens: int, completion_tokens: int, modelo: str) -> float:
    """Estimate cost in USD based on token usage."""
    pricing = PRICING.get(modelo, PRICING["gpt-4o"])
    return (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000


ProgressCallback = Callable[[str, int, int], None]


def _default_progress(msg: str, step: int, total: int) -> None:
    """Default progress callback — logs to logger."""
    logger.info("[%d/%d] %s", step, total, msg)


def _executar_com_kwargs_suportados(func: Callable, *args: Any, **kwargs: Any) -> Any:
    """Call function filtering kwargs not present in its signature."""
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        params = {}
    accepted_kwargs = {k: v for k, v in kwargs.items() if k in params}
    return func(*args, **accepted_kwargs)


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
        # Prompt modular dinâmico por etapa (fallback legado só quando necessário).
        self.prompt_sistema = ""
        self.metricas: dict = {}
        self.fail_closed = ENABLE_FAIL_CLOSED
        self._estado_atual: EstadoPipeline | None = None
        self._ultimo_processo_id: str = "default"
        logger.info("Prompt profile ativo: %s", PROMPT_PROFILE)

    def _notify(self, msg: str, step: int, total: int = 6) -> None:
        self.progress(msg, step, total)

    @property
    def estado_atual(self) -> EstadoPipeline | None:
        """Expose the latest in-memory state for error handling/recovery."""
        return self._estado_atual

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
        self._ultimo_processo_id = processo_id

        # 6.1.3 — Check for saved state
        estado: EstadoPipeline | None = None
        if continuar:
            estado = restaurar_estado(processo_id=processo_id)
            if estado:
                logger.info("📂 Retomando processamento do checkpoint")

        if estado is None:
            estado = EstadoPipeline(metadata=MetadadosPipeline(inicio=datetime.now()))
        self._estado_atual = estado
        if not estado.metadata.execucao_id:
            estado.metadata.execucao_id = f"{processo_id}-{int(time.time() * 1000)}"
        execucao_id = estado.metadata.execucao_id
        _log_structured_event(
            evento="pipeline_started",
            processo_id=processo_id,
            execucao_id=execucao_id,
            etapa="pipeline",
            extra={"continuar": continuar, "pdfs_recebidos": len(pdfs)},
        )
        ensure_prompt_contract(
            legacy_system_prompt=self.prompt_sistema.strip() if self.prompt_sistema else None,
            strict=self.fail_closed,
        )
        if not estado.metadata.prompt_hash_sha256:
            assinatura_prompt = get_pipeline_prompt_signature(
                legacy_system_prompt=self.prompt_sistema.strip() if self.prompt_sistema else None
            )
            estado.metadata.prompt_profile = assinatura_prompt["prompt_profile"]
            estado.metadata.prompt_version = assinatura_prompt["prompt_version"]
            estado.metadata.prompt_hash_sha256 = assinatura_prompt["prompt_hash_sha256"]

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
            _log_structured_event(
                evento="extracao_concluida",
                processo_id=processo_id,
                execucao_id=execucao_id,
                etapa="extracao_pdf",
                extra={
                    "duracao_s": round(self.metricas["tempo_extracao"], 3),
                    "documentos": len(documentos),
                },
            )
            salvar_estado(estado, processo_id)

        # Step 2: Classify documents
        if any(d.tipo == TipoDocumento.DESCONHECIDO for d in estado.documentos_entrada):
            self._notify("Classificando documentos...", 2, total_steps)
            t0 = time.time()
            estado.documentos_entrada = classificar_documentos(
                estado.documentos_entrada,
                strict=self.fail_closed,
                require_exactly_one_recurso=REQUIRE_EXACTLY_ONE_RECURSO,
                min_acordaos=MIN_ACORDAO_COUNT,
            )
            self.metricas["tempo_classificacao"] = time.time() - t0
            _log_structured_event(
                evento="classificacao_concluida",
                processo_id=processo_id,
                execucao_id=execucao_id,
                etapa="classificacao",
                extra={
                    "duracao_s": round(self.metricas["tempo_classificacao"], 3),
                    "documentos": len(estado.documentos_entrada),
                },
            )
            salvar_estado(estado, processo_id)
        elif self.fail_closed:
            validar_classificacao_documentos(
                estado.documentos_entrada,
                strict=True,
                require_exactly_one_recurso=REQUIRE_EXACTLY_ONE_RECURSO,
                min_acordaos=MIN_ACORDAO_COUNT,
            )

        # Identify recurso and acórdão texts
        texto_recurso = ""
        texto_acordao = ""
        for doc in estado.documentos_entrada:
            if doc.tipo == TipoDocumento.RECURSO:
                texto_recurso += doc.texto_extraido + "\n"
            elif doc.tipo == TipoDocumento.ACORDAO:
                texto_acordao += doc.texto_extraido + "\n"

        if self.fail_closed:
            if not texto_recurso.strip():
                raise PipelineValidationError("Não há texto de RECURSO para processar.")
            if not texto_acordao.strip():
                raise PipelineValidationError("Não há texto de ACÓRDÃO para processar.")

        # Step 3: Etapa 1 — Appeal analysis
        if estado.resultado_etapa1 is None:
            self._notify("Etapa 1 — Analisando recurso...", 3, total_steps)
            t0 = time.time()
            # Record model used
            estado.metadata.modelos_utilizados["Etapa 1"] = MODEL_LEGAL_ANALYSIS
            etapa1_chunking_audit: dict[str, Any] = {}

            # Import TokenBudgetExceededError for retry handling
            try:
                from src.token_manager import TokenBudgetExceededError
            except ImportError:
                TokenBudgetExceededError = Exception  # Fallback if not available

            # Use chunking-enabled version if feature is enabled
            executar_fn = executar_etapa1_com_chunking if ENABLE_CHUNKING else executar_etapa1

            try:
                # Pass user selected model as override
                estado.resultado_etapa1 = _executar_com_kwargs_suportados(
                    executar_fn,
                    texto_recurso,
                    self.prompt_sistema,
                    modelo_override=self.modelo,
                    chunking_audit=etapa1_chunking_audit,
                )
            except TokenBudgetExceededError:
                logger.warning(
                    "⏳ Orçamento de tokens excedido na Etapa 1. "
                    "Retentando imediatamente após ajuste de payload."
                )
                estado.resultado_etapa1 = _executar_com_kwargs_suportados(
                    executar_fn,
                    texto_recurso,
                    self.prompt_sistema,
                    modelo_override=self.modelo,
                    chunking_audit=etapa1_chunking_audit,
                )
            if etapa1_chunking_audit:
                estado.metadata.chunking_auditoria["etapa1"] = etapa1_chunking_audit
                if etapa1_chunking_audit.get("aplicado"):
                    _log_structured_event(
                        evento="chunking_etapa1",
                        processo_id=processo_id,
                        execucao_id=execucao_id,
                        etapa="etapa1",
                        extra={
                            "chunk_count": etapa1_chunking_audit.get("chunk_count", 0),
                            "coverage_ratio_chars": etapa1_chunking_audit.get("coverage_ratio_chars", 0.0),
                            "coverage_ratio_tokens": etapa1_chunking_audit.get("coverage_ratio_tokens", 0.0),
                        },
                    )

            if self.fail_closed:
                erros_e1 = _validar_etapa1(estado.resultado_etapa1)
                if erros_e1:
                    raise PipelineValidationError(" ".join(erros_e1))

            self.metricas["tempo_etapa1"] = time.time() - t0
            _log_structured_event(
                evento="etapa1_concluida",
                processo_id=processo_id,
                execucao_id=execucao_id,
                etapa="etapa1",
                extra={"duracao_s": round(self.metricas["tempo_etapa1"], 3)},
            )
            salvar_estado(estado, processo_id)

        # E1-005: always block Etapa 2 when Etapa 1 is marked inconclusive.
        if estado.resultado_etapa1 and estado.resultado_etapa1.inconclusivo:
            _definir_motivo_bloqueio(
                estado,
                "E1_INCONCLUSIVA",
                estado.resultado_etapa1.motivo_inconclusivo
                or BLOQUEIO_CODIGOS["E1_INCONCLUSIVA"],
            )
            _log_structured_event(
                evento="pipeline_bloqueado",
                processo_id=processo_id,
                execucao_id=execucao_id,
                etapa="etapa1",
                extra={
                    "motivo_bloqueio_codigo": estado.metadata.motivo_bloqueio_codigo,
                    "motivo_bloqueio_descricao": estado.metadata.motivo_bloqueio_descricao,
                },
            )
            raise PipelineValidationError(
                f"MOTIVO_BLOQUEIO[{estado.metadata.motivo_bloqueio_codigo}] "
                + estado.metadata.motivo_bloqueio_descricao
            )

        # Step 4: Etapa 2 — Ruling analysis
        if estado.resultado_etapa2 is None:
            self._notify("Etapa 2 — Analisando acórdão...", 4, total_steps)
            t0 = time.time()
            # Record model used
            estado.metadata.modelos_utilizados["Etapa 2"] = MODEL_LEGAL_ANALYSIS
            etapa2_chunking_audit: dict[str, Any] = {}

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
                estado.resultado_etapa2 = _executar_com_kwargs_suportados(
                    executar_fn,
                    texto_acordao,
                    estado.resultado_etapa1,
                    self.prompt_sistema,
                    modelo_override=self.modelo,
                    chunking_audit=etapa2_chunking_audit,
                )
            except TokenBudgetExceededError:
                logger.warning(
                    "⏳ Orçamento de tokens excedido na Etapa 2. "
                    "Retentando imediatamente após ajuste de payload."
                )
                estado.resultado_etapa2 = _executar_com_kwargs_suportados(
                    executar_fn,
                    texto_acordao,
                    estado.resultado_etapa1,
                    self.prompt_sistema,
                    modelo_override=self.modelo,
                    chunking_audit=etapa2_chunking_audit,
                )
            if etapa2_chunking_audit:
                estado.metadata.chunking_auditoria["etapa2"] = etapa2_chunking_audit
                if etapa2_chunking_audit.get("aplicado"):
                    _log_structured_event(
                        evento="chunking_etapa2",
                        processo_id=processo_id,
                        execucao_id=execucao_id,
                        etapa="etapa2",
                        extra={
                            "chunk_count": etapa2_chunking_audit.get("chunk_count", 0),
                            "coverage_ratio_chars": etapa2_chunking_audit.get("coverage_ratio_chars", 0.0),
                            "coverage_ratio_tokens": etapa2_chunking_audit.get("coverage_ratio_tokens", 0.0),
                        },
                    )

            self.metricas["tempo_etapa2"] = time.time() - t0
            _log_structured_event(
                evento="etapa2_concluida",
                processo_id=processo_id,
                execucao_id=execucao_id,
                etapa="etapa2",
                extra={"duracao_s": round(self.metricas["tempo_etapa2"], 3)},
            )
            salvar_estado(estado, processo_id)

        if self.fail_closed and estado.resultado_etapa2 is not None:
            erros_e2 = _validar_etapa2(estado.resultado_etapa2)
            if erros_e2:
                _definir_motivo_bloqueio(
                    estado,
                    "E2_VALIDACAO_FAIL",
                    "; ".join(erros_e2),
                )
                _log_structured_event(
                    evento="pipeline_bloqueado",
                    processo_id=processo_id,
                    execucao_id=execucao_id,
                    etapa="etapa2",
                    extra={
                        "motivo_bloqueio_codigo": estado.metadata.motivo_bloqueio_codigo,
                        "motivo_bloqueio_descricao": estado.metadata.motivo_bloqueio_descricao,
                    },
                )
                raise PipelineValidationError(" ".join(erros_e2))

        # Step 5: Etapa 3 — Draft generation
        if estado.resultado_etapa3 is None:
            self._notify("Etapa 3 — Gerando minuta...", 5, total_steps)
            t0 = time.time()
            # Record model used
            estado.metadata.modelos_utilizados["Etapa 3"] = MODEL_DRAFT_GENERATION
            etapa3_chunking_audit: dict[str, Any] = {}

            # Import TokenBudgetExceededError for retry handling
            try:
                from src.token_manager import TokenBudgetExceededError
            except ImportError:
                TokenBudgetExceededError = Exception  # Fallback

            # Use chunking-enabled version if feature is enabled
            executar_fn = executar_etapa3_com_chunking if ENABLE_CHUNKING else executar_etapa3

            try:
                estado.resultado_etapa3 = _executar_com_kwargs_suportados(
                    executar_fn,
                    estado.resultado_etapa1,
                    estado.resultado_etapa2,
                    texto_acordao,
                    self.prompt_sistema,
                    modelo_override=self.modelo,
                    chunking_audit=etapa3_chunking_audit,
                )
            except TokenBudgetExceededError:
                logger.warning(
                    "⏳ Orçamento de tokens excedido na Etapa 3. "
                    "Retentando imediatamente após ajuste de payload."
                )
                estado.resultado_etapa3 = _executar_com_kwargs_suportados(
                    executar_fn,
                    estado.resultado_etapa1,
                    estado.resultado_etapa2,
                    texto_acordao,
                    self.prompt_sistema,
                    modelo_override=self.modelo,
                    chunking_audit=etapa3_chunking_audit,
                )
            if etapa3_chunking_audit:
                estado.metadata.chunking_auditoria["etapa3"] = etapa3_chunking_audit
                if etapa3_chunking_audit.get("aplicado"):
                    _log_structured_event(
                        evento="chunking_etapa3",
                        processo_id=processo_id,
                        execucao_id=execucao_id,
                        etapa="etapa3",
                        extra={
                            "chunk_count": etapa3_chunking_audit.get("chunk_count", 0),
                            "coverage_ratio_chars": etapa3_chunking_audit.get("coverage_ratio_chars", 0.0),
                            "coverage_ratio_tokens": etapa3_chunking_audit.get("coverage_ratio_tokens", 0.0),
                        },
                    )

            if self.fail_closed:
                erros_e3 = _validar_etapa3(estado.resultado_etapa3)
                if erros_e3:
                    _definir_motivo_bloqueio(
                        estado,
                        "E3_VALIDACAO_FAIL",
                        "; ".join(erros_e3),
                    )
                    _log_structured_event(
                        evento="pipeline_bloqueado",
                        processo_id=processo_id,
                        execucao_id=execucao_id,
                        etapa="etapa3",
                        extra={
                            "motivo_bloqueio_codigo": estado.metadata.motivo_bloqueio_codigo,
                            "motivo_bloqueio_descricao": estado.metadata.motivo_bloqueio_descricao,
                        },
                    )
                    raise PipelineValidationError(" ".join(erros_e3))

            self.metricas["tempo_etapa3"] = time.time() - t0
            _log_structured_event(
                evento="etapa3_concluida",
                processo_id=processo_id,
                execucao_id=execucao_id,
                etapa="etapa3",
                extra={
                    "duracao_s": round(self.metricas["tempo_etapa3"], 3),
                    "decisao": (
                        estado.resultado_etapa3.decisao.value
                        if estado.resultado_etapa3 and estado.resultado_etapa3.decisao
                        else None
                    ),
                },
            )
            salvar_estado(estado, processo_id)

        # Step 6: Format and save output
        self._notify("Formatando e salvando resultados...", 6, total_steps)

        # Collect metrics
        estado.metadata.fim = datetime.now()
        estado.metadata.modelo_usado = self.modelo
        estado.metadata.prompt_tokens = token_tracker.total_prompt_tokens
        estado.metadata.completion_tokens = token_tracker.total_completion_tokens
        estado.metadata.total_tokens = token_tracker.total_tokens
        if estado.resultado_etapa3 and estado.resultado_etapa3.decisao == Decisao.INCONCLUSIVO:
            _definir_motivo_bloqueio(
                estado,
                estado.resultado_etapa3.motivo_bloqueio_codigo or "E3_INCONCLUSIVO",
                estado.resultado_etapa3.motivo_bloqueio_descricao
                or BLOQUEIO_CODIGOS["E3_INCONCLUSIVO"],
            )
        confiancas_etapas, confianca_global, validacoes_snapshot = _calcular_confiancas_pipeline(estado)
        confiancas_campos_etapa1 = _calcular_confianca_campos_etapa1(estado.resultado_etapa1)
        confiancas_temas_etapa2 = _calcular_confianca_temas_etapa2(estado.resultado_etapa2)
        politica_escalonamento = _avaliar_politica_escalonamento(
            confianca_global=confianca_global,
            confianca_campos_etapa1=confiancas_campos_etapa1,
            confianca_temas_etapa2=confiancas_temas_etapa2,
        )
        estado.metadata.confianca_por_etapa = confiancas_etapas
        estado.metadata.confianca_campos_etapa1 = confiancas_campos_etapa1
        estado.metadata.confianca_temas_etapa2 = confiancas_temas_etapa2
        estado.metadata.confianca_global = confianca_global
        estado.metadata.politica_escalonamento = politica_escalonamento

        self.metricas["tempo_total"] = time.time() - inicio
        self.metricas["tokens_totais"] = token_tracker.total_tokens
        self.metricas["execucao_id"] = execucao_id
        self.metricas["llm_total_calls"] = token_tracker.total_calls
        self.metricas["llm_calls_truncadas"] = token_tracker.total_truncated_calls
        self.metricas["llm_latencia_media_ms"] = round(token_tracker.average_latency_ms, 2)
        self.metricas["prompt_profile"] = estado.metadata.prompt_profile
        self.metricas["prompt_version"] = estado.metadata.prompt_version
        self.metricas["prompt_hash_sha256"] = estado.metadata.prompt_hash_sha256
        self.metricas["custo_estimado_usd"] = _estimar_custo(
            token_tracker.total_prompt_tokens,
            token_tracker.total_completion_tokens,
            self.modelo,
        )
        self.metricas["confianca_por_etapa"] = confiancas_etapas
        self.metricas["confianca_campos_etapa1"] = confiancas_campos_etapa1
        self.metricas["confianca_temas_etapa2"] = confiancas_temas_etapa2
        self.metricas["confianca_global"] = confianca_global
        self.metricas["politica_escalonamento"] = politica_escalonamento
        self.metricas["chunking_auditoria"] = estado.metadata.chunking_auditoria
        self.metricas["motivo_bloqueio_codigo"] = estado.metadata.motivo_bloqueio_codigo
        self.metricas["motivo_bloqueio_descricao"] = estado.metadata.motivo_bloqueio_descricao
        estado.metadata.llm_stats = {
            "total_calls": float(token_tracker.total_calls),
            "calls_truncadas": float(token_tracker.total_truncated_calls),
            "latencia_media_ms": round(token_tracker.average_latency_ms, 2),
        }

        alertas_validacao_auditoria: list[str] = []
        for etapa, erros in validacoes_snapshot.items():
            for erro in erros:
                alertas_validacao_auditoria.append(f"{etapa}: {erro}")
        if politica_escalonamento.get("escalonar"):
            motivos = politica_escalonamento.get("motivos", [])
            for motivo in motivos:
                alertas_validacao_auditoria.append(f"escalonamento: {motivo}")
            _log_structured_event(
                evento="escalonamento_confianca_recomendado",
                processo_id=processo_id,
                execucao_id=execucao_id,
                etapa="pipeline",
                extra={
                    "confianca_global": confianca_global,
                    "motivos": motivos,
                },
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
            alertas=alertas_validacao_auditoria,
            numero_processo=numero_proc,
            output_dir=output_dir,
        )
        auditoria_json_path = salvar_trilha_auditoria_json(
            estado,
            alertas=alertas_validacao_auditoria,
            numero_processo=numero_proc,
            output_dir=output_dir,
        )
        snapshot_path = salvar_snapshot_execucao_json(
            estado,
            validacoes=validacoes_snapshot,
            arquivos_saida={
                "minuta": str(minuta_path),
                "auditoria_markdown": str(auditoria_path),
                "auditoria_json": str(auditoria_json_path),
            },
            numero_processo=numero_proc,
            output_dir=output_dir,
        )
        self.metricas["arquivo_minuta"] = str(minuta_path)
        self.metricas["arquivo_auditoria"] = str(auditoria_path)
        self.metricas["arquivo_auditoria_json"] = str(auditoria_json_path)
        self.metricas["arquivo_snapshot_execucao"] = str(snapshot_path)

        # Save final state and cleanup
        salvar_estado(estado, processo_id)
        limpar_checkpoints(processo_id)

        logger.info(
            "✅ Pipeline concluído em %.1fs — %d tokens (~$%.4f)",
            self.metricas["tempo_total"],
            self.metricas["tokens_totais"],
            self.metricas["custo_estimado_usd"],
        )
        _log_structured_event(
            evento="pipeline_concluido",
            processo_id=processo_id,
            execucao_id=execucao_id,
            etapa="pipeline",
            extra={
                "duracao_s": round(self.metricas["tempo_total"], 3),
                "tokens_totais": self.metricas["tokens_totais"],
                "confianca_global": estado.metadata.confianca_global,
                "motivo_bloqueio_codigo": estado.metadata.motivo_bloqueio_codigo,
                "escalonamento_recomendado": bool(
                    estado.metadata.politica_escalonamento.get("escalonar")
                ),
            },
        )

        return estado.resultado_etapa3
