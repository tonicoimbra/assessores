"""Tests for quality gate evaluation from baseline payloads."""

from pathlib import Path

from src.quality_gates import (
    evaluate_quality_gates,
    find_latest_baseline_file,
    save_quality_gate_report,
)


def test_evaluate_quality_gates_passes_with_high_metrics() -> None:
    payload = {
        "summary": {
            "metrics": {
                "extraction_useful_pages_rate": 1.0,
                "etapa1_critical_fields_accuracy": 1.0,
                "etapa2_proxy_f1": 1.0,
                "etapa3_decisao_accuracy": 1.0,
            }
        }
    }
    report = evaluate_quality_gates(payload)
    assert report["passed"] is True
    assert all(g["passed"] for g in report["gates"])


def test_evaluate_quality_gates_fails_with_low_metrics() -> None:
    payload = {
        "summary": {
            "metrics": {
                "extraction_useful_pages_rate": 0.90,
                "etapa1_critical_fields_accuracy": 0.95,
                "etapa2_proxy_f1": 0.80,
                "etapa3_decisao_accuracy": 0.98,
            }
        }
    }
    report = evaluate_quality_gates(payload)
    assert report["passed"] is False
    assert any(not g["passed"] for g in report["gates"])


def test_find_latest_baseline_file_and_save_report(tmp_path: Path) -> None:
    p1 = tmp_path / "baseline_dataset_ouro_20260101_100000.json"
    p2 = tmp_path / "baseline_dataset_ouro_20260101_110000.json"
    p1.write_text("{}", encoding="utf-8")
    p2.write_text("{}", encoding="utf-8")

    latest = find_latest_baseline_file(tmp_path)
    assert latest == p2

    report_path = save_quality_gate_report(
        {"passed": True, "gates": []},
        output_dir=tmp_path,
    )
    assert report_path.exists()
    assert report_path.name.startswith("quality_gate_report_")
