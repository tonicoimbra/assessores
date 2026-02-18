"""Quality gate evaluation for golden baseline reports."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import OUTPUTS_DIR

DEFAULT_PRODUCTION_TARGETS: dict[str, float] = {
    "extraction_useful_pages_rate": 0.995,
    "etapa1_critical_fields_accuracy": 0.98,
    "etapa2_proxy_f1": 0.97,
    "etapa3_decisao_accuracy": 0.99,
    "critical_evidence_failures_zero": 1.0,
}


def find_latest_baseline_file(baseline_dir: Path | None = None) -> Path | None:
    """Return latest generated baseline file from directory."""
    root = baseline_dir or OUTPUTS_DIR
    candidates = sorted(root.glob("baseline_dataset_ouro_*.json"))
    if not candidates:
        return None
    return candidates[-1]


def load_baseline_payload(path: Path) -> dict[str, Any]:
    """Load baseline payload from file."""
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_quality_gates(
    payload: dict[str, Any],
    *,
    targets: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Evaluate baseline metrics against configured production targets."""
    summary_metrics = payload.get("summary", {}).get("metrics", {})
    target_values = targets or DEFAULT_PRODUCTION_TARGETS

    gates: list[dict[str, Any]] = []
    for metric_name, threshold in target_values.items():
        observed = float(summary_metrics.get(metric_name, 0.0))
        passed = observed >= float(threshold)
        gates.append(
            {
                "metric": metric_name,
                "observed": round(observed, 4),
                "threshold": round(float(threshold), 4),
                "passed": passed,
            }
        )

    passed_all = all(g["passed"] for g in gates)
    return {
        "gate_schema_version": "1.0.0",
        "generated_at": datetime.now().isoformat(),
        "targets": target_values,
        "passed": passed_all,
        "gates": gates,
    }


def save_quality_gate_report(
    report: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> Path:
    """Persist quality gate report as JSON."""
    out_dir = output_dir or OUTPUTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"quality_gate_report_{timestamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
