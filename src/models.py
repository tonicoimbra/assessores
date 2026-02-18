"""Data models for the admissibility analysis pipeline."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TipoDocumento(str, Enum):
    """Document type classification."""

    RECURSO = "RECURSO"
    ACORDAO = "ACORDAO"
    DESCONHECIDO = "DESCONHECIDO"


class Decisao(str, Enum):
    """Final admissibility decision."""

    ADMITIDO = "ADMITIDO"
    INADMITIDO = "INADMITIDO"
    INCONCLUSIVO = "INCONCLUSIVO"


class ClassificationAudit(BaseModel):
    """Classification audit payload with evidence and scoring details."""

    method: str = ""
    confidence: float = 0.0
    heuristic_score_recurso: float = 0.0
    heuristic_score_acordao: float = 0.0
    matched_recurso_patterns: list[str] = Field(default_factory=list)
    matched_acordao_patterns: list[str] = Field(default_factory=list)
    evidence_snippets: list[str] = Field(default_factory=list)
    llm_model: str = ""
    llm_tipo_raw: str = ""
    llm_confianca_raw: float | None = None
    verifier_tipo: str = ""
    verifier_confidence: float = 0.0
    verifier_ok: bool = True
    verifier_reason: str = ""
    composite_score_recurso: float = 0.0
    composite_score_acordao: float = 0.0
    decision_margin: float = 0.0
    consistency_score: float = 1.0
    consistency_flags: list[str] = Field(default_factory=list)


# --- 1.3.1 DocumentoEntrada ---


class DocumentoEntrada(BaseModel):
    """Input document with extracted text and classification."""

    filepath: str
    texto_extraido: str = ""
    tipo: TipoDocumento = TipoDocumento.DESCONHECIDO
    num_paginas: int = 0
    num_caracteres: int = 0
    classification_audit: ClassificationAudit | None = None


# --- 1.3.2 ResultadoEtapa1 ---


class CampoEvidencia(BaseModel):
    """Evidence for a single extracted field."""

    citacao_literal: str = ""
    pagina: int | None = None
    ancora: str = ""
    offset_inicio: int | None = None


class ResultadoEtapa1(BaseModel):
    """Stage 1 result: structured data extracted from the appeal petition."""

    numero_processo: str = ""
    recorrente: str = ""
    recorrido: str = ""
    especie_recurso: str = ""
    permissivo_constitucional: str = ""
    camara_civel: str = ""
    dispositivos_violados: list[str] = Field(default_factory=list)
    justica_gratuita: bool = False
    efeito_suspensivo: bool = False
    evidencias_campos: dict[str, CampoEvidencia] = Field(default_factory=dict)
    verificacao_campos: dict[str, bool] = Field(default_factory=dict)
    inconclusivo: bool = False
    motivo_inconclusivo: str = ""
    texto_formatado: str = ""


# --- 1.3.3 TemaEtapa2 ---


class TemaEtapa2(BaseModel):
    """Single theme from Stage 2 analysis."""

    materia_controvertida: str = ""
    conclusao_fundamentos: str = ""
    base_vinculante: str = ""
    obices_sumulas: list[str] = Field(default_factory=list)
    trecho_transcricao: str = ""
    evidencias_campos: dict[str, CampoEvidencia] = Field(default_factory=dict)


# --- 1.3.4 ResultadoEtapa2 ---


class ResultadoEtapa2(BaseModel):
    """Stage 2 result: thematic analysis of the ruling."""

    temas: list[TemaEtapa2] = Field(default_factory=list)
    texto_formatado: str = ""


# --- 1.3.5 ResultadoEtapa3 ---


class ResultadoEtapa3(BaseModel):
    """Stage 3 result: final admissibility decision draft."""

    minuta_completa: str = ""
    decisao: Decisao | None = None
    fundamentos_decisao: list[str] = Field(default_factory=list)
    itens_evidencia_usados: list[str] = Field(default_factory=list)
    aviso_inconclusivo: bool = False
    motivo_bloqueio_codigo: str = ""
    motivo_bloqueio_descricao: str = ""


# --- 1.3.6 EstadoPipeline ---


class MetadadosPipeline(BaseModel):
    """Pipeline execution metadata."""

    inicio: datetime | None = None
    fim: datetime | None = None
    modelo_usado: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    execucao_id: str = ""
    prompt_profile: str = ""
    prompt_version: str = ""
    prompt_hash_sha256: str = ""
    llm_stats: dict[str, float] = Field(default_factory=dict)
    modelos_utilizados: dict[str, str] = Field(default_factory=dict)
    confianca_por_etapa: dict[str, float] = Field(default_factory=dict)
    confianca_campos_etapa1: dict[str, float] = Field(default_factory=dict)
    confianca_temas_etapa2: dict[str, float] = Field(default_factory=dict)
    confianca_global: float = 0.0
    politica_escalonamento: dict[str, Any] = Field(default_factory=dict)
    chunking_auditoria: dict[str, Any] = Field(default_factory=dict)
    motivo_bloqueio_codigo: str = ""
    motivo_bloqueio_descricao: str = ""


class EstadoPipeline(BaseModel):
    """Complete pipeline state aggregating all stages."""

    documentos_entrada: list[DocumentoEntrada] = Field(default_factory=list)
    resultado_etapa1: ResultadoEtapa1 | None = None
    resultado_etapa2: ResultadoEtapa2 | None = None
    resultado_etapa3: ResultadoEtapa3 | None = None
    metadata: MetadadosPipeline = Field(default_factory=MetadadosPipeline)
