"""Data models for the admissibility analysis pipeline."""

from datetime import datetime
from enum import Enum

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


# --- 1.3.1 DocumentoEntrada ---


class DocumentoEntrada(BaseModel):
    """Input document with extracted text and classification."""

    filepath: str
    texto_extraido: str = ""
    tipo: TipoDocumento = TipoDocumento.DESCONHECIDO
    num_paginas: int = 0
    num_caracteres: int = 0


# --- 1.3.2 ResultadoEtapa1 ---


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
    texto_formatado: str = ""


# --- 1.3.3 TemaEtapa2 ---


class TemaEtapa2(BaseModel):
    """Single theme from Stage 2 analysis."""

    materia_controvertida: str = ""
    conclusao_fundamentos: str = ""
    base_vinculante: str = ""
    obices_sumulas: list[str] = Field(default_factory=list)
    trecho_transcricao: str = ""


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


# --- 1.3.6 EstadoPipeline ---


class MetadadosPipeline(BaseModel):
    """Pipeline execution metadata."""

    inicio: datetime | None = None
    fim: datetime | None = None
    modelo_usado: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    modelos_utilizados: dict[str, str] = Field(default_factory=dict)


class EstadoPipeline(BaseModel):
    """Complete pipeline state aggregating all stages."""

    documentos_entrada: list[DocumentoEntrada] = Field(default_factory=list)
    resultado_etapa1: ResultadoEtapa1 | None = None
    resultado_etapa2: ResultadoEtapa2 | None = None
    resultado_etapa3: ResultadoEtapa3 | None = None
    metadata: MetadadosPipeline = Field(default_factory=MetadadosPipeline)
