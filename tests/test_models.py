"""Tests for Pydantic data models (Sprint 1.3)."""

import pytest
from pydantic import ValidationError

from src.models import (
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

    def test_creates_with_all_fields(self) -> None:
        doc = DocumentoEntrada(
            filepath="recurso.pdf",
            texto_extraido="texto do recurso",
            tipo=TipoDocumento.RECURSO,
            num_paginas=5,
            num_caracteres=1000,
        )
        assert doc.tipo == TipoDocumento.RECURSO
        assert doc.num_paginas == 5

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

    def test_creates_with_data(self) -> None:
        r = ResultadoEtapa1(
            numero_processo="1234567-89.2024.8.16.0001",
            recorrente="João da Silva",
            recorrido="Maria dos Santos",
            especie_recurso="Recurso Especial",
            dispositivos_violados=["art. 5, CF", "art. 927, CC"],
            justica_gratuita=True,
        )
        assert r.numero_processo == "1234567-89.2024.8.16.0001"
        assert len(r.dispositivos_violados) == 2
        assert r.justica_gratuita is True


class TestTemaEtapa2:
    """Test TemaEtapa2 model."""

    def test_creates_with_defaults(self) -> None:
        t = TemaEtapa2()
        assert t.materia_controvertida == ""
        assert t.obices_sumulas == []

    def test_creates_with_data(self) -> None:
        t = TemaEtapa2(
            materia_controvertida="Danos morais",
            conclusao_fundamentos="Manteve a condenação",
            obices_sumulas=["Súmula 7/STJ"],
        )
        assert t.materia_controvertida == "Danos morais"
        assert len(t.obices_sumulas) == 1


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

    def test_admitido_decision(self) -> None:
        r = ResultadoEtapa3(decisao=Decisao.ADMITIDO)
        assert r.decisao == Decisao.ADMITIDO

    def test_inadmitido_decision(self) -> None:
        r = ResultadoEtapa3(decisao=Decisao.INADMITIDO)
        assert r.decisao == Decisao.INADMITIDO


class TestEstadoPipeline:
    """Test EstadoPipeline model."""

    def test_creates_empty(self) -> None:
        estado = EstadoPipeline()
        assert estado.documentos_entrada == []
        assert estado.resultado_etapa1 is None
        assert estado.resultado_etapa2 is None
        assert estado.resultado_etapa3 is None
        assert isinstance(estado.metadata, MetadadosPipeline)

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
