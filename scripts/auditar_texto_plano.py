#!/usr/bin/env python3
"""Audit outputs for plaintext sensitive data in DLQ and cache artifacts."""

from __future__ import annotations

import json
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROCESS_NUMBER_RE = re.compile(r"\b\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}\b")
CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
CNPJ_RE = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")


def _collect_plaintext_markers(text: str) -> list[str]:
    markers: list[str] = []
    if PROCESS_NUMBER_RE.search(text):
        markers.append("numero_processo")
    if CPF_RE.search(text):
        markers.append("cpf")
    if CNPJ_RE.search(text):
        markers.append("cnpj")
    return markers


def _audit_dead_letter(dead_letter_dir: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not dead_letter_dir.exists():
        return findings

    for path in sorted(dead_letter_dir.glob("*")):
        if not path.is_file():
            continue
        if path.suffix == ".json":
            findings.append(
                {
                    "scope": "dead_letter",
                    "path": str(path),
                    "issue": "legacy_plaintext_file",
                }
            )
            continue
        if path.suffix != ".dlq":
            findings.append(
                {
                    "scope": "dead_letter",
                    "path": str(path),
                    "issue": "unexpected_extension",
                }
            )
            continue

        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue

        # .dlq should not be valid plaintext JSON.
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None

        if payload is not None:
            findings.append(
                {
                    "scope": "dead_letter",
                    "path": str(path),
                    "issue": "dlq_decodable_as_json_plaintext",
                }
            )
            continue

        markers = _collect_plaintext_markers(text)
        if markers:
            findings.append(
                {
                    "scope": "dead_letter",
                    "path": str(path),
                    "issue": "plaintext_marker_in_dlq",
                    "markers": markers,
                }
            )
    return findings


def _audit_cache(cache_dir: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not cache_dir.exists():
        return findings

    for path in sorted(cache_dir.rglob("*.json")):
        raw_text = path.read_text(encoding="utf-8", errors="ignore")
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            findings.append(
                {
                    "scope": "cache",
                    "path": str(path),
                    "issue": "invalid_json_cache_entry",
                }
            )
            continue

        if not isinstance(payload, dict):
            findings.append(
                {
                    "scope": "cache",
                    "path": str(path),
                    "issue": "unexpected_cache_shape",
                }
            )
            continue

        if "payload" in payload:
            findings.append(
                {
                    "scope": "cache",
                    "path": str(path),
                    "issue": "legacy_plaintext_payload_field",
                }
            )
            continue

        if "payload_encrypted" not in payload:
            findings.append(
                {
                    "scope": "cache",
                    "path": str(path),
                    "issue": "missing_payload_encrypted",
                }
            )
            continue

        markers = _collect_plaintext_markers(raw_text)
        if markers:
            findings.append(
                {
                    "scope": "cache",
                    "path": str(path),
                    "issue": "plaintext_marker_in_cache_file",
                    "markers": markers,
                }
            )

    return findings


def _apply_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    for finding in findings:
        path = Path(str(finding.get("path") or ""))
        if not path.exists() or not path.is_file():
            continue
        issue = str(finding.get("issue") or "")
        if issue in {
            "legacy_plaintext_file",
            "legacy_plaintext_payload_field",
            "invalid_json_cache_entry",
            "missing_payload_encrypted",
            "plaintext_marker_in_cache_file",
            "plaintext_marker_in_dlq",
            "dlq_decodable_as_json_plaintext",
            "unexpected_cache_shape",
            "unexpected_extension",
        }:
            path.unlink(missing_ok=True)
            applied.append(
                {
                    "path": str(path),
                    "action": "deleted",
                    "issue": issue,
                }
            )
    return applied


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="auditar_texto_plano",
        description="Audita e opcionalmente remove artefatos legados em texto plano.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplica saneamento removendo artefatos legados/plaintext detectados.",
    )
    args = parser.parse_args()

    root = Path("outputs")
    dead_letter_dir = root / "dead_letter"
    cache_dir = root / ".cache"

    findings = _audit_dead_letter(dead_letter_dir) + _audit_cache(cache_dir)
    applied: list[dict[str, Any]] = []
    if args.apply and findings:
        applied = _apply_findings(findings)
        findings = _audit_dead_letter(dead_letter_dir) + _audit_cache(cache_dir)
    report = {
        "generated_at": datetime.now().isoformat(),
        "dead_letter_dir": str(dead_letter_dir),
        "cache_dir": str(cache_dir),
        "apply_mode": bool(args.apply),
        "applied_actions_count": len(applied),
        "applied_actions": applied,
        "findings_count": len(findings),
        "findings": findings,
        "status": "OK" if not findings else "ALERT",
    }

    report_path = root / f"auditoria_texto_plano_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"REPORT={report_path}")
    print(f"STATUS={report['status']}")
    print(f"FINDINGS={len(findings)}")
    return 0 if not findings else 2


if __name__ == "__main__":
    raise SystemExit(main())
