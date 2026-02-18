"""Tests for Pydantic data models (Sprint 1.3)."""

import pytest
from pydantic import ValidationError

from src.models import (
    CampoEvidencia,
    ClassificationAudit,
    Decisao,
    DocumentoEntrada,
    EstadoPipeline,
    MetadadosPipeline,
    ResultadoEtapa1,
    ResultadoEtapa2,
    ResultadoEtapa3,
    TemaEtapa2,
    TipoDocumento,
)


class TestDocumentoEntrada:
    """Test 1.5.4: DocumentoEntrada model validation."""

    def test_creates_with_required_fields(self) -> None:
        doc = DocumentoEntrada(filepath="test.pdf")
        assert doc.filepath == "test.pdf"
        assert doc.tipo == TipoDocumento.DESCONHECIDO
        assert doc.texto_extraido == ""
        assert doc.num_paginas == 0
        assert doc.classification_audit is None

    def test_creates_with_all_fields(self) -> None:
        doc = DocumentoEntrada(
            filepath="recurso.pdf",
            texto_extraido="texto do recurso",
            tipo=TipoDocumento.RECURSO,
            num_paginas=5,
            num_caracteres=1000,
            classification_audit=ClassificationAudit(
                method="heuristica",
                confidence=0.9,
                heuristic_score_recurso=0.9,
            ),
        )
        assert doc.tipo == TipoDocumento.RECURSO
        assert doc.num_paginas == 5
        assert doc.classification_audit is not None
        assert doc.classification_audit.method == "heuristica"
        assert doc.classification_audit.verifier_ok is True
        assert doc.classification_audit.verifier_tipo == ""

    def test_rejects_missing_filepath(self) -> None:
        with pytest.raises(ValidationError):
            DocumentoEntrada()  # type: ignore[call-arg]


class TestResultadoEtapa1:
    """Test ResultadoEtapa1 model."""

    def test_creates_with_defaults(self) -> None:
        r = ResultadoEtapa1()
        assert r.numero_processo == ""
        assert r.dispositivos_violados == []
        assert r.justica_gratuita is False
        assert r.evidencias_campos == {}
        assert r.verificacao_campos == {}
        assert r.inconclusivo is False
        assert r.motivo_inconclusivo == ""

    def test_creates_with_data(self) -> None:
        r = ResultadoEtapa1(
            numero_processo="1234567-89.2024.8.16.0001",
            recorrente="João da Silva",
            recorrido="Maria dos Santos",
            especie_recurso="Recurso Especial",
            dispositivos_violados=["art. 5, CF", "art. 927, CC"],
            justica_gratuita=True,
            evidencias_campos={
                "numero_processo": CampoEvidencia(
                    citacao_literal="Processo nº 1234567-89.2024.8.16.0001",
                    pagina=1,
                    ancora="Processo nº 1234567-89.2024.8.16.0001",
                )
            },
            verificacao_campos={"numero_processo": True},
            inconclusivo=True,
            motivo_inconclusivo="Campo obrigatório ausente: especie_recurso",
        )
        assert r.numero_processo == "1234567-89.2024.8.16.0001"
        assert len(r.dispositivos_violados) == 2
        assert r.justica_gratuita is True
        assert "numero_processo" in r.evidencias_campos
        assert r.verificacao_campos["numero_processo"] is True
        assert r.inconclusivo is True
        assert "especie_recurso" in r.motivo_inconclusivo


class TestTemaEtapa2:
    """Test TemaEtapa2 model."""

    def test_creates_with_defaults(self) -> None:
        t = TemaEtapa2()
        assert t.materia_controvertida == ""
        assert t.obices_sumulas == []
        assert t.evidencias_campos == {}

    def test_creates_with_data(self) -> None:
        t = TemaEtapa2(
            materia_controvertida="Danos morais",
            conclusao_fundamentos="Manteve a condenação",
            obices_sumulas=["Súmula 7/STJ"],
            evidencias_campos={
                "materia_controvertida": CampoEvidencia(
                    citacao_literal="Tema sobre danos morais",
                    pagina=1,
                    ancora="Tema 1",
                )
            },
        )
        assert t.materia_controvertida == "Danos morais"
        assert len(t.obices_sumulas) == 1
        assert "materia_controvertida" in t.evidencias_campos


class TestResultadoEtapa2:
    """Test ResultadoEtapa2 model."""

    def test_creates_empty(self) -> None:
        r = ResultadoEtapa2()
        assert r.temas == []

    def test_creates_with_temas(self) -> None:
        tema = TemaEtapa2(materia_controvertida="Teste")
        r = ResultadoEtapa2(temas=[tema])
        assert len(r.temas) == 1
        assert r.temas[0].materia_controvertida == "Teste"


class TestResultadoEtapa3:
    """Test ResultadoEtapa3 model."""

    def test_creates_with_defaults(self) -> None:
        r = ResultadoEtapa3()
        assert r.minuta_completa == ""
        assert r.decisao is None
        assert r.fundamentos_decisao == []
        assert r.itens_evidencia_usados == []
        assert r.aviso_inconclusivo is False
        assert r.motivo_bloqueio_codigo == ""
        assert r.motivo_bloqueio_descricao == ""

    def test_admitido_decision(self) -> None:
        r = ResultadoEtapa3(decisao=Decisao.ADMITIDO)
        assert r.decisao == Decisao.ADMITIDO

    def test_inadmitido_decision(self) -> None:
        r = ResultadoEtapa3(decisao=Decisao.INADMITIDO)
        assert r.decisao == Decisao.INADMITIDO

    def test_inconclusivo_decision(self) -> None:
        r = ResultadoEtapa3(decisao=Decisao.INCONCLUSIVO)
        assert r.decisao == Decisao.INCONCLUSIVO


class TestEstadoPipeline:
    """Test EstadoPipeline model."""

    def test_creates_empty(self) -> None:
        estado = EstadoPipeline()
        assert estado.documentos_entrada == []
        assert estado.resultado_etapa1 is None
        assert estado.resultado_etapa2 is None
        assert estado.resultado_etapa3 is None
        assert isinstance(estado.metadata, MetadadosPipeline)
        assert estado.metadata.confianca_por_etapa == {}
        assert estado.metadata.confianca_campos_etapa1 == {}
        assert estado.metadata.confianca_temas_etapa2 == {}
        assert estado.metadata.confianca_global == 0.0
        assert estado.metadata.politica_escalonamento == {}
        assert estado.metadata.chunking_auditoria == {}
        assert estado.metadata.prompt_profile == ""
        assert estado.metadata.prompt_version == ""
        assert estado.metadata.prompt_hash_sha256 == ""
        assert estado.metadata.llm_stats == {}
        assert estado.metadata.execucao_id == ""
        assert estado.metadata.motivo_bloqueio_codigo == ""
        assert estado.metadata.motivo_bloqueio_descricao == ""

    def test_full_pipeline_state(self) -> None:
        estado = EstadoPipeline(
            documentos_entrada=[DocumentoEntrada(filepath="a.pdf")],
            resultado_etapa1=ResultadoEtapa1(numero_processo="123"),
            resultado_etapa2=ResultadoEtapa2(temas=[]),
            resultado_etapa3=ResultadoEtapa3(decisao=Decisao.ADMITIDO),
        )
        assert len(estado.documentos_entrada) == 1
        assert estado.resultado_etapa1 is not None
        assert estado.resultado_etapa3.decisao == Decisao.ADMITIDO


class TestEnums:
    """Test enum values."""

    def test_tipo_documento_values(self) -> None:
        assert TipoDocumento.RECURSO.value == "RECURSO"
        assert TipoDocumento.ACORDAO.value == "ACORDAO"
        assert TipoDocumento.DESCONHECIDO.value == "DESCONHECIDO"

    def test_decisao_values(self) -> None:
        assert Decisao.ADMITIDO.value == "ADMITIDO"
        assert Decisao.INADMITIDO.value == "INADMITIDO"
        assert Decisao.INCONCLUSIVO.value == "INCONCLUSIVO"


class TestSerialization:
    """Test JSON serialization/deserialization."""

    def test_model_to_json(self) -> None:
        r = ResultadoEtapa1(numero_processo="123", dispositivos_violados=["art. 5"])
        json_str = r.model_dump_json()
        assert "123" in json_str

    def test_model_from_json(self) -> None:
        data = {"numero_processo": "456", "dispositivos_violados": ["art. 10"]}
        r = ResultadoEtapa1.model_validate(data)
        assert r.numero_processo == "456"

    def test_pipeline_state_roundtrip(self) -> None:
        estado = EstadoPipeline(
            resultado_etapa1=ResultadoEtapa1(numero_processo="789"),
        )
        json_str = estado.model_dump_json()
        restored = EstadoPipeline.model_validate_json(json_str)
        assert restored.resultado_etapa1.numero_processo == "789"
