"""Tests for automatic regression alerts."""

from pathlib import Path

from src.regression_alerts import (
    evaluate_regression_alerts,
    find_previous_baseline_file,
    save_regression_alert_report,
)


def _baseline_payload(extraction: float, decisao: float) -> dict:
    return {
        "summary": {
            "metrics": {
                "extraction_useful_pages_rate": extraction,
                "etapa3_decisao_accuracy": decisao,
            }
        }
    }


def test_evaluate_regression_alerts_without_previous_passes_when_above_threshold() -> None:
    report = evaluate_regression_alerts(
        current_payload=_baseline_payload(0.999, 0.995),
    )
    assert report["has_alerts"] is False
    assert report["status"] == "OK"
    assert all(check["passed"] for check in report["checks"])


def test_evaluate_regression_alerts_flags_threshold_breach() -> None:
    report = evaluate_regression_alerts(
        current_payload=_baseline_payload(0.990, 0.995),
    )
    assert report["has_alerts"] is True
    assert any(a["type"] == "threshold_breach" for a in report["alerts"])


def test_evaluate_regression_alerts_flags_regression_against_previous() -> None:
    previous = _baseline_payload(1.0, 1.0)
    current = _baseline_payload(0.997, 0.997)
    report = evaluate_regression_alerts(
        current_payload=current,
        previous_payload=previous,
    )
    assert report["has_alerts"] is True
    assert any(a["type"] == "regression_breach" for a in report["alerts"])


def test_find_previous_baseline_file(tmp_path: Path) -> None:
    p1 = tmp_path / "baseline_dataset_ouro_20260101_100000.json"
    p2 = tmp_path / "baseline_dataset_ouro_20260101_110000.json"
    p3 = tmp_path / "baseline_dataset_ouro_20260101_120000.json"
    p1.write_text("{}", encoding="utf-8")
    p2.write_text("{}", encoding="utf-8")
    p3.write_text("{}", encoding="utf-8")

    assert find_previous_baseline_file(current_baseline=p3, baseline_dir=tmp_path) == p2
    assert find_previous_baseline_file(current_baseline=None, baseline_dir=tmp_path) == p2


def test_save_regression_alert_report(tmp_path: Path) -> None:
    path = save_regression_alert_report({"status": "OK"}, output_dir=tmp_path)
    assert path.exists()
    assert path.name.startswith("regression_alert_report_")
