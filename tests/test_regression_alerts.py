"""Tests for automatic regression alerts."""

from pathlib import Path

from src.regression_alerts import (
    RESOURCE_TYPE_INCONCLUSIVO_RULE_KEY,
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


def _build_cases(
    *,
    especie_recurso: str,
    total: int,
    inconclusivos: int,
) -> list[dict]:
    cases: list[dict] = []
    for idx in range(total):
        decisao = "INCONCLUSIVO" if idx < inconclusivos else "INADMITIDO"
        cases.append(
            {
                "case_id": f"case_{especie_recurso}_{idx}",
                "observed": {
                    "especie_recurso": especie_recurso,
                    "decisao": decisao,
                },
            }
        )
    return cases


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


def test_evaluate_regression_alerts_flags_threshold_breach_by_resource_type() -> None:
    payload = _baseline_payload(0.999, 0.995)
    payload["cases"] = _build_cases(
        especie_recurso="RECURSO ESPECIAL",
        total=20,
        inconclusivos=3,
    )

    report = evaluate_regression_alerts(
        current_payload=payload,
        rules={
            "extraction_useful_pages_rate": {"min_threshold": 0.995, "max_negative_delta": 0.002},
            "etapa3_decisao_accuracy": {"min_threshold": 0.99, "max_negative_delta": 0.002},
            RESOURCE_TYPE_INCONCLUSIVO_RULE_KEY: {
                "max_threshold": 0.10,
                "max_positive_delta": 0.10,
                "min_cases": 5,
            },
        },
    )

    assert report["has_alerts"] is True
    assert any(a["type"] == "resource_type_threshold_breach" for a in report["alerts"])
    assert report["quality_by_resource_type"]["current"]["RECURSO ESPECIAL"]["inconclusivo_rate"] == 0.15


def test_evaluate_regression_alerts_flags_positive_delta_by_resource_type() -> None:
    previous = _baseline_payload(1.0, 1.0)
    previous["cases"] = _build_cases(
        especie_recurso="AGRAVO INTERNO",
        total=50,
        inconclusivos=1,
    )
    current = _baseline_payload(1.0, 1.0)
    current["cases"] = _build_cases(
        especie_recurso="AGRAVO INTERNO",
        total=50,
        inconclusivos=6,
    )

    report = evaluate_regression_alerts(
        current_payload=current,
        previous_payload=previous,
        rules={
            "extraction_useful_pages_rate": {"min_threshold": 0.995, "max_negative_delta": 0.002},
            "etapa3_decisao_accuracy": {"min_threshold": 0.99, "max_negative_delta": 0.002},
            RESOURCE_TYPE_INCONCLUSIVO_RULE_KEY: {
                "max_threshold": 0.50,
                "max_positive_delta": 0.05,
                "min_cases": 5,
            },
        },
    )

    assert report["has_alerts"] is True
    assert any(a["type"] == "resource_type_regression_breach" for a in report["alerts"])
    checks = [
        c
        for c in report["checks"]
        if c["metric"] == RESOURCE_TYPE_INCONCLUSIVO_RULE_KEY
        and c.get("resource_type") == "AGRAVO INTERNO"
    ]
    assert checks
    assert checks[0]["delta"] == 0.1


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
