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
RESOURCE_TYPE_INCONCLUSIVO_RULE_KEY = "inconclusivo_rate_by_especie_recurso"
DEFAULT_RESOURCE_TYPE_INCONCLUSIVO_RULE: dict[str, float] = {
    "max_threshold": 0.05,
    "max_positive_delta": 0.02,
    "min_cases": 5.0,
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


def _normalize_resource_type(value: Any) -> str:
    """Normalize resource type label for stable grouping."""
    text = " ".join(str(value or "").strip().upper().split())
    return text or "DESCONHECIDO"


def _extract_case_resource_type(case: dict[str, Any]) -> str:
    """Extract `especie_recurso` from one baseline case payload."""
    candidates: list[Any] = [
        case.get("especie_recurso"),
        case.get("resource_type"),
    ]
    observed = case.get("observed")
    if isinstance(observed, dict):
        candidates.extend([observed.get("especie_recurso"), observed.get("resource_type")])
    expected = case.get("expected")
    if isinstance(expected, dict):
        candidates.append(expected.get("especie_recurso"))
    mock_pipeline_results = case.get("mock_pipeline_results")
    if isinstance(mock_pipeline_results, dict):
        etapa1 = mock_pipeline_results.get("etapa1")
        if isinstance(etapa1, dict):
            candidates.append(etapa1.get("especie_recurso"))

    for candidate in candidates:
        normalized = _normalize_resource_type(candidate)
        if normalized != "DESCONHECIDO":
            return normalized
    return "DESCONHECIDO"


def _extract_case_decision(case: dict[str, Any]) -> str:
    """Extract decision label from one baseline case payload."""
    candidates: list[Any] = [case.get("decisao")]
    observed = case.get("observed")
    if isinstance(observed, dict):
        candidates.append(observed.get("decisao"))
    expected = case.get("expected")
    if isinstance(expected, dict):
        candidates.append(expected.get("decisao"))
    for candidate in candidates:
        text = " ".join(str(candidate or "").strip().upper().split())
        if text:
            return text
    return ""


def _is_inconclusivo(decision: str) -> bool:
    """Return True when decision indicates INCONCLUSIVO."""
    normalized = str(decision or "").upper()
    return "INCONCLUS" in normalized


def _compute_inconclusivo_rate_by_resource_type(payload: dict[str, Any]) -> dict[str, dict[str, float | int]]:
    """Aggregate INCONCLUSIVO rate segmented by resource type from baseline cases."""
    cases = payload.get("cases")
    if not isinstance(cases, list):
        return {}

    counters: dict[str, dict[str, int]] = {}
    for case in cases:
        if not isinstance(case, dict):
            continue
        resource_type = _extract_case_resource_type(case)
        counters.setdefault(resource_type, {"total_cases": 0, "inconclusivo_cases": 0})
        counters[resource_type]["total_cases"] += 1

        decision = _extract_case_decision(case)
        if _is_inconclusivo(decision):
            counters[resource_type]["inconclusivo_cases"] += 1

    aggregated: dict[str, dict[str, float | int]] = {}
    for resource_type in sorted(counters):
        total_cases = int(counters[resource_type]["total_cases"])
        inconclusivo_cases = int(counters[resource_type]["inconclusivo_cases"])
        inconclusivo_rate = (
            round(inconclusivo_cases / total_cases, 4) if total_cases else 0.0
        )
        aggregated[resource_type] = {
            "total_cases": total_cases,
            "inconclusivo_cases": inconclusivo_cases,
            "inconclusivo_rate": inconclusivo_rate,
        }
    return aggregated


def evaluate_regression_alerts(
    *,
    current_payload: dict[str, Any],
    previous_payload: dict[str, Any] | None = None,
    rules: dict[str, dict[str, float]] | None = None,
    current_baseline_path: Path | None = None,
    previous_baseline_path: Path | None = None,
) -> dict[str, Any]:
    """Evaluate extraction/decision metrics and return alert report."""
    active_rules = dict(rules or DEFAULT_ALERT_RULES)
    resource_rule_raw = active_rules.pop(
        RESOURCE_TYPE_INCONCLUSIVO_RULE_KEY,
        DEFAULT_RESOURCE_TYPE_INCONCLUSIVO_RULE,
    )
    resource_rule = {
        "max_threshold": float(
            resource_rule_raw.get("max_threshold", DEFAULT_RESOURCE_TYPE_INCONCLUSIVO_RULE["max_threshold"])
        ),
        "max_positive_delta": float(
            resource_rule_raw.get(
                "max_positive_delta",
                DEFAULT_RESOURCE_TYPE_INCONCLUSIVO_RULE["max_positive_delta"],
            )
        ),
        "min_cases": float(resource_rule_raw.get("min_cases", DEFAULT_RESOURCE_TYPE_INCONCLUSIVO_RULE["min_cases"])),
    }
    current_metrics = current_payload.get("summary", {}).get("metrics", {})
    previous_metrics = (
        previous_payload.get("summary", {}).get("metrics", {})
        if previous_payload
        else {}
    )
    current_resource_metrics = _compute_inconclusivo_rate_by_resource_type(current_payload)
    previous_resource_metrics = (
        _compute_inconclusivo_rate_by_resource_type(previous_payload)
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

    min_cases = int(max(1.0, resource_rule["min_cases"]))
    max_threshold = float(resource_rule["max_threshold"])
    max_positive_delta = float(resource_rule["max_positive_delta"])
    for resource_type in sorted(current_resource_metrics):
        current_info = current_resource_metrics[resource_type]
        total_cases = int(current_info["total_cases"])
        inconclusivo_cases = int(current_info["inconclusivo_cases"])
        observed = float(current_info["inconclusivo_rate"])

        previous_info = previous_resource_metrics.get(resource_type, {})
        previous_value_raw = previous_info.get("inconclusivo_rate")
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

        skipped = total_cases < min_cases
        threshold_breach = not skipped and observed > max_threshold
        regression_breach = (
            not skipped
            and previous_value is not None
            and delta is not None
            and delta > max_positive_delta
        )
        passed = not (threshold_breach or regression_breach)

        checks.append(
            {
                "metric": RESOURCE_TYPE_INCONCLUSIVO_RULE_KEY,
                "resource_type": resource_type,
                "sample_size": total_cases,
                "inconclusivo_cases": inconclusivo_cases,
                "observed": round(observed, 4),
                "previous": round(previous_value, 4) if previous_value is not None else None,
                "delta": delta,
                "max_threshold": round(max_threshold, 4),
                "max_positive_delta": round(max_positive_delta, 4),
                "min_cases": min_cases,
                "skipped": skipped,
                "passed": passed,
            }
        )

        if threshold_breach:
            alerts.append(
                {
                    "metric": RESOURCE_TYPE_INCONCLUSIVO_RULE_KEY,
                    "resource_type": resource_type,
                    "type": "resource_type_threshold_breach",
                    "severity": "critical",
                    "message": (
                        "Taxa de INCONCLUSIVO acima do limite para "
                        f"{resource_type}: {observed:.4f} > {max_threshold:.4f} "
                        f"(n={total_cases})"
                    ),
                }
            )
        if regression_breach and delta is not None:
            alerts.append(
                {
                    "metric": RESOURCE_TYPE_INCONCLUSIVO_RULE_KEY,
                    "resource_type": resource_type,
                    "type": "resource_type_regression_breach",
                    "severity": "critical",
                    "message": (
                        "Taxa de INCONCLUSIVO regrediu por tipo de recurso "
                        f"{resource_type}: delta={delta:.4f} > {max_positive_delta:.4f} "
                        f"(atual={observed:.4f}, anterior={previous_value:.4f})"
                    ),
                }
            )

    has_alerts = bool(alerts)
    report_rules = dict(active_rules)
    report_rules[RESOURCE_TYPE_INCONCLUSIVO_RULE_KEY] = resource_rule
    return {
        "regression_alert_schema_version": "1.1.0",
        "generated_at": datetime.now().isoformat(),
        "current_baseline": str(current_baseline_path) if current_baseline_path else "",
        "previous_baseline": str(previous_baseline_path) if previous_baseline_path else "",
        "rules": report_rules,
        "quality_by_resource_type": {
            "metric": RESOURCE_TYPE_INCONCLUSIVO_RULE_KEY,
            "current": current_resource_metrics,
            "previous": previous_resource_metrics,
        },
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
