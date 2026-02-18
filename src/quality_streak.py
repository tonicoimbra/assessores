"""Validation of consecutive quality-gate runs (PRD-READY-002)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import OUTPUTS_DIR


def list_quality_gate_reports(reports_dir: Path | None = None) -> list[Path]:
    """List quality gate reports in chronological order by filename."""
    root = reports_dir or OUTPUTS_DIR
    return sorted(root.glob("quality_gate_report_*.json"))


def load_quality_gate_report(path: Path) -> dict[str, Any]:
    """Load one quality gate report payload."""
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_iso_datetime(value: str) -> datetime | None:
    """Parse ISO datetime with optional trailing Z; return None on failure."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def evaluate_quality_gate_streak(
    *,
    report_paths: list[Path],
    min_runs: int = 3,
) -> dict[str, Any]:
    """Evaluate whether the latest N quality-gate runs passed consecutively."""
    if min_runs < 1:
        raise ValueError("min_runs deve ser >= 1")

    ordered = sorted(report_paths)
    errors: list[str] = []
    considered = ordered[-min_runs:]

    if len(ordered) < min_runs:
        errors.append(
            f"Relatórios insuficientes: encontrados {len(ordered)}, mínimo exigido {min_runs}."
        )

    checks: list[dict[str, Any]] = []
    previous_ts: datetime | None = None
    for path in considered:
        payload = load_quality_gate_report(path)
        report_passed = bool(payload.get("passed") is True)
        generated_at_raw = str(payload.get("generated_at") or "")
        generated_at = _parse_iso_datetime(generated_at_raw)

        if generated_at is None:
            errors.append(f"Relatório sem generated_at válido: {path.name}")
        elif previous_ts and generated_at <= previous_ts:
            errors.append(
                "Sequência temporal inválida entre relatórios consecutivos: "
                f"{path.name}"
            )
        previous_ts = generated_at or previous_ts

        if not report_passed:
            errors.append(f"Gate reprovado em {path.name}.")

        checks.append(
            {
                "report": str(path),
                "passed": report_passed,
                "generated_at": generated_at_raw,
            }
        )

    trailing_pass_streak = 0
    for path in reversed(ordered):
        payload = load_quality_gate_report(path)
        if bool(payload.get("passed") is True):
            trailing_pass_streak += 1
            continue
        break

    passed = not errors and len(ordered) >= min_runs
    return {
        "quality_streak_schema_version": "1.0.0",
        "generated_at": datetime.now().isoformat(),
        "min_runs": int(min_runs),
        "runs_available": len(ordered),
        "runs_considered": len(considered),
        "trailing_pass_streak": trailing_pass_streak,
        "passed": passed,
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "errors": errors,
    }


def save_quality_streak_report(
    report: dict[str, Any],
    *,
    output_dir: Path | None = None,
) -> Path:
    """Persist quality streak report as JSON."""
    out_dir = output_dir or OUTPUTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"quality_streak_report_{timestamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
