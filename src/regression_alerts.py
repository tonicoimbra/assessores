"""Automatic regression alerts for extraction/decision quality metrics."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import OUTPUTS_DIR

DEFAULT_ALERT_RULES: dict[str, dict[str, float]] = {
    "extraction_useful_pages_rate": {
        "min_threshold": 0.995,
        "max_negative_delta": 0.002,
    },
    "etapa3_decisao_accuracy": {
        "min_threshold": 0.99,
        "max_negative_delta": 0.002,
    },
}


def _list_baseline_files(baseline_dir: Path | None = None) -> list[Path]:
    """List baseline files in chronological order by filename."""
    root = baseline_dir or OUTPUTS_DIR
    return sorted(root.glob("baseline_dataset_ouro_*.json"))


def find_previous_baseline_file(
    *,
    current_baseline: Path | None = None,
    baseline_dir: Path | None = None,
) -> Path | None:
    """Return previous baseline file (if any) for regression comparison."""
    candidates = _list_baseline_files(baseline_dir)
    if len(candidates) < 2:
        return None

    if current_baseline is None:
        return candidates[-2]

    current = current_baseline.resolve()
    for idx, path in enumerate(candidates):
        if path.resolve() == current:
            return candidates[idx - 1] if idx > 0 else None
    return candidates[-2]


def load_baseline_payload(path: Path) -> dict[str, Any]:
    """Load baseline payload from file."""
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_regression_alerts(
    *,
    current_payload: dict[str, Any],
    previous_payload: dict[str, Any] | None = None,
    rules: dict[str, dict[str, float]] | None = None,
    current_baseline_path: Path | None = None,
    previous_baseline_path: Path | None = None,
) -> dict[str, Any]:
    """Evaluate extraction/decision metrics and return alert report."""
    active_rules = rules or DEFAULT_ALERT_RULES
    current_metrics = current_payload.get("summary", {}).get("metrics", {})
    previous_metrics = (
        previous_payload.get("summary", {}).get("metrics", {})
        if previous_payload
        else {}
    )

    alerts: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []

    for metric_name, rule in active_rules.items():
        observed = float(current_metrics.get(metric_name, 0.0))
        min_threshold = float(rule.get("min_threshold", 0.0))
        max_negative_delta = float(rule.get("max_negative_delta", 0.0))

        previous_value_raw = previous_metrics.get(metric_name)
        previous_value = (
            float(previous_value_raw)
            if previous_value_raw is not None
            else None
        )
        delta = (
            round(observed - previous_value, 4)
            if previous_value is not None
            else None
        )

        threshold_breach = observed < min_threshold
        regression_breach = (
            previous_value is not None
            and delta is not None
            and delta < -max_negative_delta
        )
        passed = not (threshold_breach or regression_breach)

        check_payload = {
            "metric": metric_name,
            "observed": round(observed, 4),
            "previous": round(previous_value, 4) if previous_value is not None else None,
            "delta": delta,
            "min_threshold": round(min_threshold, 4),
            "max_negative_delta": round(max_negative_delta, 4),
            "passed": passed,
        }
        checks.append(check_payload)

        if threshold_breach:
            alerts.append(
                {
                    "metric": metric_name,
                    "type": "threshold_breach",
                    "severity": "critical",
                    "message": (
                        f"{metric_name} abaixo do mínimo: "
                        f"{observed:.4f} < {min_threshold:.4f}"
                    ),
                }
            )
        if regression_breach and delta is not None:
            alerts.append(
                {
                    "metric": metric_name,
                    "type": "regression_breach",
                    "severity": "critical",
                    "message": (
                        f"{metric_name} regrediu além do permitido: "
                        f"delta={delta:.4f} < -{max_negative_delta:.4f}"
                    ),
                }
            )

    has_alerts = bool(alerts)
    return {
        "regression_alert_schema_version": "1.0.0",
        "generated_at": datetime.now().isoformat(),
        "current_baseline": str(current_baseline_path) if current_baseline_path else "",
        "previous_baseline": str(previous_baseline_path) if previous_baseline_path else "",
        "rules": active_rules,
        "checks": checks,
        "alerts": alerts,
        "has_alerts": has_alerts,
        "status": "ALERT" if has_alerts else "OK",
    }


def save_regression_alert_report(
    report: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> Path:
    """Persist regression alert report as JSON."""
    out_dir = output_dir or OUTPUTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"regression_alert_report_{timestamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
