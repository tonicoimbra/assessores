"""Tests for operational dashboard aggregation."""

import json
from pathlib import Path

import pytest

from src.operational_dashboard import gerar_dashboard_operacional


def _write_snapshot(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_dashboard_handles_empty_snapshot_directory(tmp_path: Path) -> None:
    dashboard_json, dashboard_md, payload = gerar_dashboard_operacional(
        snapshot_dir=tmp_path / "snapshots",
        output_dir=tmp_path / "out",
    )

    assert dashboard_json.exists()
    assert dashboard_md.exists()
    assert payload["execucoes"]["total"] == 0
    assert payload["tokens"]["total"] == 0
    assert payload["custo_estimado_usd"]["total"] == 0.0
    assert payload["qualidade"]["retrabalho_retry"]["taxa_por_call"] == 0.0
    assert payload["qualidade"]["cobertura_evidencia"]["taxa"] == 0.0


def test_dashboard_aggregates_latency_errors_tokens_and_cost(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    output_dir = tmp_path / "out"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    _write_snapshot(
        snapshot_dir / "snapshot_execucao_a.json",
        {
            "metadata": {
                "inicio": "2026-02-18T10:00:00",
                "fim": "2026-02-18T10:00:10",
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "total_tokens": 1500,
                "modelo_usado": "gpt-4o-mini",
                "llm_stats": {
                    "total_calls": 3,
                    "calls_truncadas": 1,
                    "latencia_media_ms": 250.0,
                },
            },
            "stages": {
                "etapa1": {"validacao_erros": []},
                "etapa2": {"validacao_erros": ["tema sem evidência"]},
                "etapa3": {"validacao_erros": [], "resultado": {"decisao": "INADMITIDO"}},
            },
        },
    )
    _write_snapshot(
        snapshot_dir / "snapshot_execucao_b.json",
        {
            "metadata": {
                "inicio": "2026-02-18T10:01:00",
                "fim": "2026-02-18T10:01:20",
                "prompt_tokens": 500,
                "completion_tokens": 400,
                "total_tokens": 900,
                "modelo_usado": "gpt-4o",
                "llm_stats": {
                    "total_calls": 2,
                    "calls_truncadas": 0,
                    "latencia_media_ms": 300.0,
                },
            },
            "stages": {
                "etapa1": {"validacao_erros": []},
                "etapa2": {"validacao_erros": []},
                "etapa3": {
                    "validacao_erros": ["minuta sem aviso explícito"],
                    "resultado": {"decisao": "INCONCLUSIVO"},
                },
            },
        },
    )

    dashboard_json, dashboard_md, payload = gerar_dashboard_operacional(
        snapshot_dir=snapshot_dir,
        output_dir=output_dir,
    )

    assert dashboard_json.exists()
    assert dashboard_md.exists()
    assert payload["execucoes"]["total"] == 2
    assert payload["latencia"]["media_s"] == 15.0
    assert payload["tokens"]["total"] == 2400
    assert payload["qualidade"]["taxa_inconclusivo"] == 0.5
    assert payload["qualidade"]["erro_por_etapa"]["etapa2"] == 0.5
    assert payload["qualidade"]["erro_por_etapa"]["etapa3"] == 0.5
    assert payload["llm"]["calls_total"] == 5
    assert payload["llm"]["calls_truncadas_total"] == 1
    assert payload["qualidade"]["retrabalho_retry"]["llm_calls_truncadas_total"] == 1
    assert payload["qualidade"]["retrabalho_retry"]["taxa_por_call"] == 0.2
    assert payload["custo_estimado_usd"]["total"] > 0.0


def test_dashboard_calculates_evidence_coverage(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    output_dir = tmp_path / "out"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    _write_snapshot(
        snapshot_dir / "snapshot_execucao_cov.json",
        {
            "metadata": {
                "inicio": "2026-02-18T11:00:00",
                "fim": "2026-02-18T11:00:15",
                "prompt_tokens": 100,
                "completion_tokens": 100,
                "total_tokens": 200,
                "modelo_usado": "gpt-4o-mini",
                "llm_stats": {
                    "total_calls": 4,
                    "calls_truncadas": 1,
                    "latencia_media_ms": 210.0,
                },
            },
            "stages": {
                "etapa1": {
                    "validacao_erros": [],
                    "resultado": {
                        "numero_processo": "123",
                        "recorrente": "Parte A",
                        "especie_recurso": "",
                        "evidencias_campos": {
                            "numero_processo": {
                                "citacao_literal": "Processo 123",
                                "pagina": 1,
                                "ancora": "Processo 123",
                            },
                            "recorrente": {
                                "citacao_literal": "Parte A",
                                "pagina": 1,
                                "ancora": "",
                            },
                        },
                    },
                },
                "etapa2": {
                    "validacao_erros": [],
                    "resultado": {
                        "temas": [
                            {
                                "materia_controvertida": "Tema A",
                                "conclusao_fundamentos": "Conclusão A",
                                "obices_sumulas": ["Súmula 7/STJ"],
                                "trecho_transcricao": "",
                                "evidencias_campos": {
                                    "materia_controvertida": {
                                        "citacao_literal": "Tema A",
                                        "pagina": 2,
                                        "ancora": "Tema A",
                                    },
                                    "conclusao_fundamentos": {
                                        "citacao_literal": "Conclusão A",
                                        "pagina": None,
                                        "ancora": "Conclusão A",
                                    },
                                    "obices_sumulas": {
                                        "citacao_literal": "Súmula 7/STJ",
                                        "pagina": 3,
                                        "ancora": "Súmula 7/STJ",
                                    },
                                },
                            }
                        ]
                    },
                },
                "etapa3": {"validacao_erros": [], "resultado": {"decisao": "INADMITIDO"}},
            },
        },
    )

    _, _, payload = gerar_dashboard_operacional(
        snapshot_dir=snapshot_dir,
        output_dir=output_dir,
    )

    assert payload["qualidade"]["retrabalho_retry"]["taxa_por_call"] == 0.25
    assert payload["qualidade"]["cobertura_evidencia"]["campos_cobertos"] == 3
    assert payload["qualidade"]["cobertura_evidencia"]["campos_avaliados"] == 5
    assert payload["qualidade"]["cobertura_evidencia"]["taxa"] == 0.6


def test_dashboard_includes_build_metadata_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GITHUB_RUN_ID", "901")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")

    _, _, payload = gerar_dashboard_operacional(
        snapshot_dir=tmp_path / "snapshots",
        output_dir=tmp_path / "out",
    )

    assert payload["build"]["provider"] == "github"
    assert payload["build"]["build_id"] == "901"
    assert payload["build"]["commit_sha"] == "abc123"
    assert payload["build"]["branch"] == "main"
