"""Golden dataset E2E regression tests for the full pipeline orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.models import (
    ClassificationAudit,
    ResultadoEtapa1,
    ResultadoEtapa2,
    ResultadoEtapa3,
    TipoDocumento,
)
from src.pdf_processor import ExtractionResult
from src.pipeline import PipelineAdmissibilidade

GOLDEN_ROOT = Path(__file__).parent / "fixtures" / "golden"
CRITICAL_FIELDS_ETAPA1: tuple[str, ...] = ("numero_processo", "recorrente", "especie_recurso")
ESSENTIAL_FIELDS_ETAPA2: tuple[str, ...] = (
    "materia_controvertida",
    "conclusao_fundamentos",
    "obices_sumulas",
    "trecho_transcricao",
)


def _golden_case_paths() -> list[Path]:
    """Return all versioned golden case files."""
    return sorted(GOLDEN_ROOT.glob("v*/case_*.json"))


def _load_case(path: Path) -> dict[str, Any]:
    """Load one golden case payload."""
    return json.loads(path.read_text(encoding="utf-8"))


def _case_id_from_file(path: Path) -> str:
    """Derive pytest id from file payload."""
    try:
        return _load_case(path).get("case_id", path.stem)
    except Exception:
        return path.stem


def _assert_evidence_entry(evidence: dict[str, Any], *, context: str) -> None:
    """Validate minimal mandatory evidence contract."""
    assert str(evidence.get("citacao_literal") or "").strip(), f"{context}: sem citação literal"
    assert str(evidence.get("ancora") or "").strip(), f"{context}: sem âncora"
    pagina = evidence.get("pagina")
    assert isinstance(pagina, int) and pagina >= 1, f"{context}: sem página válida"


@pytest.mark.golden
def test_golden_dataset_has_cases() -> None:
    """Guardrail: ensure there is at least one golden case versioned."""
    assert _golden_case_paths(), "Nenhum caso encontrado em tests/fixtures/golden/v*/case_*.json"


@pytest.mark.golden
@pytest.mark.parametrize("case_file", _golden_case_paths(), ids=_case_id_from_file)
def test_pipeline_golden_regression(
    case_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run deterministic E2E regression using versioned golden fixtures."""
    case = _load_case(case_file)
    expected = case["expected"]
    docs = case["inputs"]["pdfs"]
    results = case["mock_pipeline_results"]

    doc_by_filename: dict[str, dict[str, Any]] = {}
    pdf_paths: list[str] = []
    for doc in docs:
        fp = tmp_path / doc["filename"]
        fp.write_bytes(b"%PDF-1.4\n%mock\n%%EOF\n")
        pdf_paths.append(str(fp))
        doc_by_filename[doc["filename"]] = doc

    def _fake_extrair_texto(filepath: str) -> ExtractionResult:
        source = doc_by_filename[Path(filepath).name]
        text = source["texto"]
        return ExtractionResult(
            texto=text,
            num_paginas=1,
            num_caracteres=len(text),
            engine_usada="golden-fixture",
            raw_text_by_page=[text],
            clean_text_by_page=[text],
            quality_score=1.0,
        )

    def _fake_classificar_documentos(documentos, **kwargs):
        for doc in documentos:
            source = doc_by_filename[Path(doc.filepath).name]
            doc.tipo = TipoDocumento(source["tipo"])
            doc.classification_audit = ClassificationAudit(
                method="golden_fixture",
                confidence=1.0,
                heuristic_score_recurso=1.0 if doc.tipo == TipoDocumento.RECURSO else 0.0,
                heuristic_score_acordao=1.0 if doc.tipo == TipoDocumento.ACORDAO else 0.0,
                evidence_snippets=[source["texto"][:100]],
            )
        return documentos

    etapa1_result = ResultadoEtapa1.model_validate(results["etapa1"])
    etapa2_result = ResultadoEtapa2.model_validate(results["etapa2"])
    etapa3_result = ResultadoEtapa3.model_validate(results["etapa3"])

    monkeypatch.setattr("src.pipeline.extrair_texto", _fake_extrair_texto)
    monkeypatch.setattr("src.pipeline.classificar_documentos", _fake_classificar_documentos)
    monkeypatch.setattr("src.pipeline.executar_etapa1", lambda *args, **kwargs: etapa1_result.model_copy(deep=True))
    monkeypatch.setattr(
        "src.pipeline.executar_etapa1_com_chunking",
        lambda *args, **kwargs: etapa1_result.model_copy(deep=True),
    )
    monkeypatch.setattr("src.pipeline.executar_etapa2", lambda *args, **kwargs: etapa2_result.model_copy(deep=True))
    monkeypatch.setattr(
        "src.pipeline.executar_etapa2_com_chunking",
        lambda *args, **kwargs: etapa2_result.model_copy(deep=True),
    )
    monkeypatch.setattr(
        "src.pipeline.executar_etapa2_paralelo",
        lambda *args, **kwargs: etapa2_result.model_copy(deep=True),
    )
    monkeypatch.setattr("src.pipeline.executar_etapa3", lambda *args, **kwargs: etapa3_result.model_copy(deep=True))
    monkeypatch.setattr(
        "src.pipeline.executar_etapa3_com_chunking",
        lambda *args, **kwargs: etapa3_result.model_copy(deep=True),
    )

    pipeline = PipelineAdmissibilidade(
        formato_saida="md",
        saida_dir=str(tmp_path / "outputs"),
    )
    final_result = pipeline.executar(
        pdfs=pdf_paths,
        processo_id=case["case_id"],
        continuar=False,
    )

    assert final_result.decisao is not None
    assert final_result.decisao.value == expected["decisao"]
    assert pipeline.metricas["motivo_bloqueio_codigo"] == expected.get("motivo_bloqueio_codigo", "")

    min_conf = expected.get("confianca_global_min")
    if min_conf is not None:
        assert pipeline.metricas["confianca_global"] >= float(min_conf)

    max_conf = expected.get("confianca_global_max")
    if max_conf is not None:
        assert pipeline.metricas["confianca_global"] <= float(max_conf)

    minuta_path = Path(pipeline.metricas["arquivo_minuta"])
    auditoria_path = Path(pipeline.metricas["arquivo_auditoria"])
    snapshot_path = Path(pipeline.metricas["arquivo_snapshot_execucao"])
    assert minuta_path.exists()
    assert auditoria_path.exists()
    assert snapshot_path.exists()

    snapshot_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot_payload["snapshot_schema_version"] == "1.0.0"

    etapa1_result = snapshot_payload["stages"]["etapa1"]["resultado"]
    etapa1_evid = etapa1_result.get("evidencias_campos") or {}
    etapa1_verif = etapa1_result.get("verificacao_campos") or {}
    for campo in CRITICAL_FIELDS_ETAPA1:
        if not str(etapa1_result.get(campo) or "").strip():
            continue
        assert campo in etapa1_evid, f"Etapa 1: evidência ausente para {campo}"
        _assert_evidence_entry(etapa1_evid[campo], context=f"Etapa 1/{campo}")
        assert etapa1_verif.get(campo) is True, f"Etapa 1: verificação falhou para {campo}"

    etapa2_temas = snapshot_payload["stages"]["etapa2"]["resultado"]["temas"]
    assert len(etapa2_temas) == int(expected["temas_count"])
    assert any(expected["obice_contains"] in ob for ob in etapa2_temas[0]["obices_sumulas"])
    for idx, tema in enumerate(etapa2_temas, 1):
        evidencias_tema = tema.get("evidencias_campos") or {}
        for campo in ESSENTIAL_FIELDS_ETAPA2:
            valor = tema.get(campo)
            if campo == "obices_sumulas":
                if not isinstance(valor, list) or not any(str(v).strip() for v in valor):
                    continue
            elif not str(valor or "").strip():
                continue
            assert campo in evidencias_tema, f"Etapa 2 tema {idx}: evidência ausente para {campo}"
            _assert_evidence_entry(
                evidencias_tema[campo],
                context=f"Etapa 2 tema {idx}/{campo}",
            )

    etapa3_result = snapshot_payload["stages"]["etapa3"]["resultado"]
    assert etapa3_result.get("itens_evidencia_usados"), "Etapa 3: sem itens_evidencia_usados"
