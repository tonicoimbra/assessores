"""Tests for consecutive quality-gate streak validation."""

import json
from pathlib import Path

from src.quality_streak import (
    evaluate_quality_gate_streak,
    list_quality_gate_reports,
    save_quality_streak_report,
)


def _write_report(path: Path, *, passed: bool, generated_at: str) -> None:
    payload = {
        "gate_schema_version": "1.0.0",
        "generated_at": generated_at,
        "passed": passed,
        "gates": [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_quality_streak_passes_with_three_latest_reports(tmp_path: Path) -> None:
    _write_report(
        tmp_path / "quality_gate_report_20260218_100000.json",
        passed=True,
        generated_at="2026-02-18T10:00:00",
    )
    _write_report(
        tmp_path / "quality_gate_report_20260218_110000.json",
        passed=True,
        generated_at="2026-02-18T11:00:00",
    )
    _write_report(
        tmp_path / "quality_gate_report_20260218_120000.json",
        passed=True,
        generated_at="2026-02-18T12:00:00",
    )

    reports = list_quality_gate_reports(tmp_path)
    result = evaluate_quality_gate_streak(report_paths=reports, min_runs=3)
    assert result["passed"] is True
    assert result["trailing_pass_streak"] == 3
    assert result["errors"] == []


def test_quality_streak_fails_when_one_recent_report_failed(tmp_path: Path) -> None:
    _write_report(
        tmp_path / "quality_gate_report_20260218_100000.json",
        passed=True,
        generated_at="2026-02-18T10:00:00",
    )
    _write_report(
        tmp_path / "quality_gate_report_20260218_110000.json",
        passed=False,
        generated_at="2026-02-18T11:00:00",
    )
    _write_report(
        tmp_path / "quality_gate_report_20260218_120000.json",
        passed=True,
        generated_at="2026-02-18T12:00:00",
    )

    reports = list_quality_gate_reports(tmp_path)
    result = evaluate_quality_gate_streak(report_paths=reports, min_runs=3)
    assert result["passed"] is False
    assert any("Gate reprovado" in err for err in result["errors"])
    assert result["trailing_pass_streak"] == 1


def test_quality_streak_fails_when_reports_are_insufficient(tmp_path: Path) -> None:
    _write_report(
        tmp_path / "quality_gate_report_20260218_100000.json",
        passed=True,
        generated_at="2026-02-18T10:00:00",
    )
    reports = list_quality_gate_reports(tmp_path)
    result = evaluate_quality_gate_streak(report_paths=reports, min_runs=3)
    assert result["passed"] is False
    assert any("Relatórios insuficientes" in err for err in result["errors"])


def test_quality_streak_report_is_saved(tmp_path: Path) -> None:
    report = {
        "quality_streak_schema_version": "1.0.0",
        "generated_at": "2026-02-18T12:00:00",
        "passed": True,
        "checks": [],
        "errors": [],
    }
    path = save_quality_streak_report(report, output_dir=tmp_path)
    assert path.exists()
    assert path.name.startswith("quality_streak_report_")
