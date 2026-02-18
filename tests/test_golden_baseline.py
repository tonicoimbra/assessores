"""Tests for golden dataset quality baseline generation."""

from pathlib import Path

from src.golden_baseline import gerar_baseline_dataset_ouro


def test_generate_golden_baseline_report(tmp_path: Path) -> None:
    json_path, md_path, payload = gerar_baseline_dataset_ouro(
        output_dir=tmp_path,
    )

    assert json_path.exists()
    assert md_path.exists()
    assert payload["baseline_schema_version"] == "1.0.0"
    assert payload["summary"]["num_cases"] >= 1

    metrics = payload["summary"]["metrics"]
    assert 0.0 <= metrics["extraction_useful_pages_rate"] <= 1.0
    assert 0.0 <= metrics["classification_accuracy"] <= 1.0
    assert 0.0 <= metrics["etapa1_critical_fields_accuracy"] <= 1.0
    assert 0.0 <= metrics["etapa2_temas_count_accuracy"] <= 1.0
    assert 0.0 <= metrics["etapa2_proxy_f1"] <= 1.0
    assert 0.0 <= metrics["etapa3_decisao_accuracy"] <= 1.0
    assert 0.0 <= metrics["critical_evidence_failures_zero"] <= 1.0
    assert payload["summary"]["critical_evidence_failures_total"] >= 0
