"""Schema contract tests for Stage 1/2/3 outputs."""

import pytest
from pydantic import ValidationError

from src.models import Decisao, ResultadoEtapa1, ResultadoEtapa2, ResultadoEtapa3


def test_resultado_etapa1_json_schema_contract() -> None:
    schema = ResultadoEtapa1.model_json_schema()
    properties = schema["properties"]

    assert schema["type"] == "object"
    assert properties["numero_processo"]["type"] == "string"
    assert properties["dispositivos_violados"]["type"] == "array"
    assert properties["evidencias_campos"]["type"] == "object"
    assert (
        properties["evidencias_campos"]["additionalProperties"]["$ref"]
        == "#/$defs/CampoEvidencia"
    )


def test_resultado_etapa2_json_schema_contract() -> None:
    schema = ResultadoEtapa2.model_json_schema()
    properties = schema["properties"]

    assert schema["type"] == "object"
    assert properties["temas"]["type"] == "array"
    assert properties["temas"]["items"]["$ref"] == "#/$defs/TemaEtapa2"
    assert properties["texto_formatado"]["type"] == "string"


def test_resultado_etapa3_json_schema_contract() -> None:
    schema = ResultadoEtapa3.model_json_schema()
    properties = schema["properties"]

    assert schema["type"] == "object"
    assert properties["fundamentos_decisao"]["type"] == "array"
    assert properties["itens_evidencia_usados"]["type"] == "array"
    assert {"$ref": "#/$defs/Decisao"} in properties["decisao"]["anyOf"]
    assert {"type": "null"} in properties["decisao"]["anyOf"]


def test_resultado_etapa1_rejects_invalid_evidencia_contract() -> None:
    invalid_payload = {
        "numero_processo": "123",
        "evidencias_campos": {
            "numero_processo": {
                "citacao_literal": "Processo 123",
                "pagina": {},
            }
        },
    }

    with pytest.raises(ValidationError):
        ResultadoEtapa1.model_validate(invalid_payload)


def test_resultado_etapa2_rejects_invalid_tema_contract() -> None:
    invalid_payload = {
        "temas": [
            {
                "materia_controvertida": "Tema único",
                "obices_sumulas": "Súmula 7/STJ",
            }
        ]
    }

    with pytest.raises(ValidationError):
        ResultadoEtapa2.model_validate(invalid_payload)


def test_resultado_etapa3_rejects_invalid_decisao_enum() -> None:
    with pytest.raises(ValidationError):
        ResultadoEtapa3.model_validate({"decisao": "PARCIAL"})


def test_resultado_etapa3_accepts_decisao_enum_from_string() -> None:
    result = ResultadoEtapa3.model_validate({"decisao": "INCONCLUSIVO"})
    assert result.decisao == Decisao.INCONCLUSIVO


def test_resultado_etapa1_ignores_unknown_fields() -> None:
    result = ResultadoEtapa1.model_validate(
        {"numero_processo": "123", "campo_inesperado": "ignorado"}
    )
    dumped = result.model_dump()

    assert dumped["numero_processo"] == "123"
    assert "campo_inesperado" not in dumped


def test_stage_models_json_roundtrip_contract() -> None:
    etapa1 = ResultadoEtapa1.model_validate(
        {
            "numero_processo": "123",
            "recorrente": "Parte A",
            "evidencias_campos": {
                "numero_processo": {"citacao_literal": "Processo 123", "pagina": 1}
            },
        }
    )
    etapa2 = ResultadoEtapa2.model_validate(
        {
            "temas": [
                {
                    "materia_controvertida": "Tema",
                    "obices_sumulas": ["Súmula 7/STJ"],
                }
            ]
        }
    )
    etapa3 = ResultadoEtapa3.model_validate(
        {
            "decisao": "ADMITIDO",
            "fundamentos_decisao": ["Fundamento A"],
            "itens_evidencia_usados": ["Tema 1"],
        }
    )

    restored_etapa1 = ResultadoEtapa1.model_validate_json(etapa1.model_dump_json())
    restored_etapa2 = ResultadoEtapa2.model_validate_json(etapa2.model_dump_json())
    restored_etapa3 = ResultadoEtapa3.model_validate_json(etapa3.model_dump_json())

    assert restored_etapa1.model_dump() == etapa1.model_dump()
    assert restored_etapa2.model_dump() == etapa2.model_dump()
    assert restored_etapa3.model_dump() == etapa3.model_dump()
