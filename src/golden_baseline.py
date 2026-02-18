"""Golden dataset baseline metrics for quality gates."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator

from src.config import BASE_DIR, OUTPUTS_DIR
from src.models import (
    ClassificationAudit,
    ResultadoEtapa1,
    ResultadoEtapa2,
    ResultadoEtapa3,
    TipoDocumento,
)
from src.pdf_processor import ExtractionResult
from src.pipeline import PipelineAdmissibilidade
from src.pipeline import _validar_etapa1, _validar_etapa2

GOLDEN_ROOT = BASE_DIR / "tests" / "fixtures" / "golden"


def _golden_case_paths(golden_root: Path) -> list[Path]:
    """Return all versioned golden case files."""
    return sorted(golden_root.glob("v*/case_*.json"))


def _load_case(path: Path) -> dict[str, Any]:
    """Load one golden case payload."""
    return json.loads(path.read_text(encoding="utf-8"))


def _mean(values: list[float]) -> float:
    """Safe average helper."""
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


@contextmanager
def _patched_pipeline_for_case(
    case: dict[str, Any],
    tmp_case_dir: Path,
) -> Iterator[list[str]]:
    """Patch pipeline dependencies to deterministic in-fixture behavior."""
    from src import pipeline as pipeline_module

    docs = case["inputs"]["pdfs"]
    results = case["mock_pipeline_results"]
    doc_by_filename: dict[str, dict[str, Any]] = {}
    pdf_paths: list[str] = []

    for doc in docs:
        fp = tmp_case_dir / doc["filename"]
        fp.write_bytes(b"%PDF-1.4\n%golden\n%%EOF\n")
        pdf_paths.append(str(fp))
        doc_by_filename[doc["filename"]] = doc

    etapa1_result = ResultadoEtapa1.model_validate(results["etapa1"])
    etapa2_result = ResultadoEtapa2.model_validate(results["etapa2"])
    etapa3_result = ResultadoEtapa3.model_validate(results["etapa3"])

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
                verifier_tipo=doc.tipo.value,
                verifier_confidence=1.0,
                verifier_ok=True,
                verifier_reason="golden_fixture",
            )
        return documentos

    patches = {
        "extrair_texto": _fake_extrair_texto,
        "classificar_documentos": _fake_classificar_documentos,
        "executar_etapa1": lambda *args, **kwargs: etapa1_result.model_copy(deep=True),
        "executar_etapa1_com_chunking": lambda *args, **kwargs: etapa1_result.model_copy(deep=True),
        "executar_etapa2": lambda *args, **kwargs: etapa2_result.model_copy(deep=True),
        "executar_etapa2_com_chunking": lambda *args, **kwargs: etapa2_result.model_copy(deep=True),
        "executar_etapa2_paralelo": lambda *args, **kwargs: etapa2_result.model_copy(deep=True),
        "executar_etapa3": lambda *args, **kwargs: etapa3_result.model_copy(deep=True),
        "executar_etapa3_com_chunking": lambda *args, **kwargs: etapa3_result.model_copy(deep=True),
    }

    originals: dict[str, Any] = {}
    try:
        for attr, replacement in patches.items():
            originals[attr] = getattr(pipeline_module, attr)
            setattr(pipeline_module, attr, replacement)
        yield pdf_paths
    finally:
        for attr, original in originals.items():
            setattr(pipeline_module, attr, original)


def _evaluate_case(case: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """Execute one golden case and collect per-stage quality metrics."""
    case_id = str(case.get("case_id", "unknown_case"))
    expected = case["expected"]
    mock_stage = case["mock_pipeline_results"]
    fields = ("numero_processo", "recorrente", "especie_recurso")

    with TemporaryDirectory(prefix=f"{case_id}_") as tmp_dir_raw:
        tmp_case_dir = Path(tmp_dir_raw)
        with _patched_pipeline_for_case(case, tmp_case_dir) as pdf_paths:
            pipeline = PipelineAdmissibilidade(
                formato_saida="md",
                saida_dir=str(output_dir / case_id),
            )
            final_result = pipeline.executar(
                pdfs=pdf_paths,
                processo_id=case_id,
                continuar=False,
            )

    estado = pipeline.estado_atual
    assert estado is not None
    etapa1 = estado.resultado_etapa1
    etapa2 = estado.resultado_etapa2

    classificacao_total = len(estado.documentos_entrada)
    classificacao_ok = 0
    expected_tipo = {doc["filename"]: doc["tipo"] for doc in case["inputs"]["pdfs"]}
    useful_pages_total = len(case["inputs"]["pdfs"])
    useful_pages_ok = 0
    for doc in estado.documentos_entrada:
        if expected_tipo.get(Path(doc.filepath).name) == doc.tipo.value:
            classificacao_ok += 1
        if str(doc.texto_extraido or "").strip():
            useful_pages_ok += 1

    e1_total = len(fields)
    e1_ok = 0
    for field in fields:
        if etapa1 and getattr(etapa1, field, "") == mock_stage["etapa1"].get(field, ""):
            e1_ok += 1

    expected_temas = int(expected.get("temas_count", 0))
    observed_temas = len(etapa2.temas) if etapa2 else 0
    e2_tema_ok = int(observed_temas == expected_temas)

    obice_contains = str(expected.get("obice_contains", "")).strip()
    e2_obice_ok = 0
    if obice_contains and etapa2 and etapa2.temas:
        if any(obice_contains in ob for ob in etapa2.temas[0].obices_sumulas):
            e2_obice_ok = 1
    e2_proxy_f1 = 0.0
    if (e2_tema_ok + e2_obice_ok) > 0:
        e2_proxy_f1 = round((2 * e2_tema_ok * e2_obice_ok) / (e2_tema_ok + e2_obice_ok), 4)

    decisao_observada = final_result.decisao.value if final_result.decisao else ""
    decisao_esperada = str(expected.get("decisao", ""))
    e3_decisao_ok = int(decisao_observada == decisao_esperada)

    motivo_esperado = str(expected.get("motivo_bloqueio_codigo", ""))
    motivo_observado = str(pipeline.metricas.get("motivo_bloqueio_codigo", ""))
    e3_motivo_ok = int(motivo_observado == motivo_esperado)

    conf = float(pipeline.metricas.get("confianca_global", 0.0))
    min_conf = expected.get("confianca_global_min")
    max_conf = expected.get("confianca_global_max")
    conf_ok = 1
    if min_conf is not None and conf < float(min_conf):
        conf_ok = 0
    if max_conf is not None and conf > float(max_conf):
        conf_ok = 0

    erros_e1 = _validar_etapa1(etapa1) if etapa1 else ["Etapa 1 não executada."]
    erros_e2 = _validar_etapa2(etapa2) if etapa2 else ["Etapa 2 não executada."]
    indicadores_evidencia = (
        "sem evidência",
        "sem citação literal",
        "sem página válida",
        "sem âncora",
        "sem verificação independente positiva",
    )
    falhas_criticas_evidencia = [
        erro
        for erro in (erros_e1 + erros_e2)
        if any(indicador in erro.lower() for indicador in indicadores_evidencia)
    ]
    critical_evidence_failures = len(falhas_criticas_evidencia)

    return {
        "case_id": case_id,
        "dataset_version": case.get("dataset_version", ""),
        "metrics": {
            "extraction_useful_pages_rate": round(useful_pages_ok / max(useful_pages_total, 1), 4),
            "classification_accuracy": round(classificacao_ok / max(classificacao_total, 1), 4),
            "etapa1_critical_fields_accuracy": round(e1_ok / max(e1_total, 1), 4),
            "etapa2_temas_count_accuracy": float(e2_tema_ok),
            "etapa2_obice_accuracy": float(e2_obice_ok),
            "etapa2_proxy_f1": float(e2_proxy_f1),
            "etapa3_decisao_accuracy": float(e3_decisao_ok),
            "etapa3_motivo_bloqueio_accuracy": float(e3_motivo_ok),
            "confianca_global_bounds_accuracy": float(conf_ok),
            "critical_evidence_failures": float(critical_evidence_failures),
            "critical_evidence_failures_zero": float(critical_evidence_failures == 0),
        },
        "observed": {
            "decisao": decisao_observada,
            "motivo_bloqueio_codigo": motivo_observado,
            "temas_count": observed_temas,
            "confianca_global": conf,
            "critical_evidence_failures_detail": falhas_criticas_evidencia,
        },
    }


def _build_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-case metrics into global baseline metrics."""
    metric_keys = [
        "extraction_useful_pages_rate",
        "classification_accuracy",
        "etapa1_critical_fields_accuracy",
        "etapa2_temas_count_accuracy",
        "etapa2_obice_accuracy",
        "etapa2_proxy_f1",
        "etapa3_decisao_accuracy",
        "etapa3_motivo_bloqueio_accuracy",
        "confianca_global_bounds_accuracy",
        "critical_evidence_failures_zero",
    ]
    summary_metrics: dict[str, float] = {}
    for key in metric_keys:
        values = [float(case["metrics"].get(key, 0.0)) for case in cases]
        summary_metrics[key] = _mean(values)

    return {
        "num_cases": len(cases),
        "metrics": summary_metrics,
        "critical_evidence_failures_total": int(
            sum(int(case["metrics"].get("critical_evidence_failures", 0)) for case in cases)
        ),
    }


def _to_markdown(payload: dict[str, Any]) -> str:
    """Render baseline report in markdown format."""
    summary = payload["summary"]
    metrics = summary["metrics"]

    lines = [
        "# Baseline de Qualidade — Dataset Ouro",
        "",
        f"- Gerado em: {payload['generated_at']}",
        f"- Dataset root: {payload['dataset_root']}",
        f"- Casos analisados: {summary['num_cases']}",
        "",
        "## Métricas por Etapa",
        "",
        f"- Classificação (acurácia): {metrics['classification_accuracy']:.4f}",
        f"- Extração (páginas úteis): {metrics['extraction_useful_pages_rate']:.4f}",
        f"- Etapa 1 campos críticos (acurácia): {metrics['etapa1_critical_fields_accuracy']:.4f}",
        f"- Etapa 2 contagem de temas (acurácia): {metrics['etapa2_temas_count_accuracy']:.4f}",
        f"- Etapa 2 óbice esperado (acurácia): {metrics['etapa2_obice_accuracy']:.4f}",
        f"- Etapa 2 proxy F1: {metrics['etapa2_proxy_f1']:.4f}",
        f"- Etapa 3 decisão (acurácia): {metrics['etapa3_decisao_accuracy']:.4f}",
        f"- Etapa 3 motivo de bloqueio (acurácia): {metrics['etapa3_motivo_bloqueio_accuracy']:.4f}",
        f"- Confiança global dentro do intervalo esperado: {metrics['confianca_global_bounds_accuracy']:.4f}",
        f"- Casos sem falhas críticas de evidência: {metrics['critical_evidence_failures_zero']:.4f}",
        f"- Falhas críticas de evidência (total): {summary['critical_evidence_failures_total']}",
        "",
        "## Casos",
        "",
    ]

    for case in payload["cases"]:
        cm = case["metrics"]
        lines.append(
            "- "
            f"{case['case_id']}: ext={cm['extraction_useful_pages_rate']:.3f}, "
            f"cls={cm['classification_accuracy']:.3f}, "
            f"e1={cm['etapa1_critical_fields_accuracy']:.3f}, "
            f"e2_temas={cm['etapa2_temas_count_accuracy']:.3f}, "
            f"e2_obice={cm['etapa2_obice_accuracy']:.3f}, "
            f"e2_f1={cm['etapa2_proxy_f1']:.3f}, "
            f"e3_dec={cm['etapa3_decisao_accuracy']:.3f}, "
            f"e3_motivo={cm['etapa3_motivo_bloqueio_accuracy']:.3f}, "
            f"conf={cm['confianca_global_bounds_accuracy']:.3f}, "
            f"ev_fail={cm['critical_evidence_failures']:.0f}"
        )
    lines.append("")
    return "\n".join(lines)


def gerar_baseline_dataset_ouro(
    *,
    golden_root: Path | None = None,
    output_dir: Path | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    """
    Generate baseline quality report from versioned golden dataset cases.

    Returns:
        Tuple (json_path, markdown_path, payload)
    """
    dataset_root = golden_root or GOLDEN_ROOT
    target_dir = output_dir or OUTPUTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    case_paths = _golden_case_paths(dataset_root)
    cases = [_evaluate_case(_load_case(path), target_dir) for path in case_paths]
    summary = _build_summary(cases)

    payload = {
        "baseline_schema_version": "1.0.0",
        "generated_at": datetime.now().isoformat(),
        "dataset_root": str(dataset_root),
        "cases": cases,
        "summary": summary,
    }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = target_dir / f"baseline_dataset_ouro_{timestamp}.json"
    md_path = target_dir / f"baseline_dataset_ouro_{timestamp}.md"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_to_markdown(payload), encoding="utf-8")

    return json_path, md_path, payload
