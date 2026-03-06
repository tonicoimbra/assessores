"""Tests for operational dashboard aggregation."""

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.operational_dashboard import gerar_dashboard_operacional, obter_metricas_operacionais


def _write_snapshot(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_dashboard_handles_empty_snapshot_directory(tmp_path: Path) -> None:
    dashboard_json, dashboard_md, payload = gerar_dashboard_operacional(
        snapshot_dir=tmp_path / "snapshots",
        output_dir=tmp_path / "out",
    )

    assert dashboard_json.exists()
    assert dashboard_md.exists()
    csv_files = sorted((tmp_path / "out").glob("dashboard_operacional_*.csv"))
    assert len(csv_files) == 1
    assert payload["execucoes"]["total"] == 0
    assert payload["tokens"]["total"] == 0
    assert payload["custo_estimado_usd"]["total"] == 0.0
    assert payload["qualidade"]["retrabalho_retry"]["taxa_por_call"] == 0.0
    assert payload["qualidade"]["cobertura_evidencia"]["taxa"] == 0.0
    assert payload["qualidade"]["alertas_validacao"]["taxa"] == 0.0
    assert payload["distribuicao_decisao_por_semana"] == []


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


def test_dashboard_adds_weekly_decision_alert_rate_top5_and_csv(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    output_dir = tmp_path / "out"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    _write_snapshot(
        snapshot_dir / "snapshot_execucao_a.json",
        {
            "metadata": {"inicio": "2026-02-18T10:00:00", "fim": "2026-02-18T10:00:08"},
            "stages": {
                "etapa1": {"validacao_erros": []},
                "etapa2": {"validacao_erros": ["Seção II não encontrada"]},
                "etapa3": {"validacao_erros": [], "resultado": {"decisao": "ADMITIDO"}},
            },
        },
    )
    _write_snapshot(
        snapshot_dir / "snapshot_execucao_b.json",
        {
            "metadata": {"inicio": "2026-02-19T10:00:00", "fim": "2026-02-19T10:00:12"},
            "stages": {
                "etapa1": {"validacao_erros": []},
                "etapa2": {"validacao_erros": []},
                "etapa3": {
                    "validacao_erros": ["Súmula não encontrada no acórdão"],
                    "resultado": {"decisao": "INADMITIDO"},
                },
            },
        },
    )
    _write_snapshot(
        snapshot_dir / "snapshot_execucao_c.json",
        {
            "metadata": {"inicio": "2026-02-28T10:00:00", "fim": "2026-02-28T10:00:12"},
            "stages": {
                "etapa1": {"validacao_erros": []},
                "etapa2": {"validacao_erros": []},
                "etapa3": {"validacao_erros": [], "resultado": {"decisao": "INCONCLUSIVO"}},
            },
        },
    )

    _, _, payload = gerar_dashboard_operacional(snapshot_dir=snapshot_dir, output_dir=output_dir)

    alertas = payload["qualidade"]["alertas_validacao"]
    assert alertas["minutas_com_alerta"] == 2
    assert alertas["minutas_avaliadas"] == 3
    assert alertas["taxa"] == 0.667
    assert alertas["top_5_tipos"][0] == {"tipo": "seção ausente", "quantidade": 1}
    assert alertas["top_5_tipos"][1] == {"tipo": "súmula não encontrada", "quantidade": 1}

    distribuicao = {item["semana"]: item for item in payload["distribuicao_decisao_por_semana"]}
    week_1 = datetime.fromisoformat("2026-02-18T10:00:08").isocalendar()
    week_2 = datetime.fromisoformat("2026-02-28T10:00:12").isocalendar()
    semana_1 = f"{week_1.year}-W{week_1.week:02d}"
    semana_2 = f"{week_2.year}-W{week_2.week:02d}"
    assert distribuicao[semana_1]["ADMITIDO"] == 1
    assert distribuicao[semana_1]["INADMITIDO"] == 1
    assert distribuicao[semana_1]["INCONCLUSIVO"] == 0
    assert distribuicao[semana_2]["ADMITIDO"] == 0
    assert distribuicao[semana_2]["INADMITIDO"] == 0
    assert distribuicao[semana_2]["INCONCLUSIVO"] == 1

    csv_files = sorted(output_dir.glob("dashboard_operacional_*.csv"))
    assert len(csv_files) == 1
    with csv_files[0].open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert any(
        row["categoria"] == "alertas_validacao"
        and row["metrica"] == "taxa"
        and row["valor"] == "0.667"
        for row in rows
    )
    assert any(
        row["categoria"] == "distribuicao_decisao_por_semana"
        and row["metrica"] == "INCONCLUSIVO"
        and row["semana"] == semana_2
        and row["valor"] == "1"
        for row in rows
    )


def test_obter_metricas_operacionais_filters_by_period(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    recent_end = (datetime.now() - timedelta(days=1)).replace(microsecond=0)
    old_end = (datetime.now() - timedelta(days=40)).replace(microsecond=0)

    _write_snapshot(
        snapshot_dir / "snapshot_execucao_recente.json",
        {
            "metadata": {
                "inicio": (recent_end - timedelta(seconds=10)).isoformat(),
                "fim": recent_end.isoformat(),
            },
            "stages": {"etapa3": {"resultado": {"decisao": "ADMITIDO"}}},
        },
    )
    _write_snapshot(
        snapshot_dir / "snapshot_execucao_antigo.json",
        {
            "metadata": {
                "inicio": (old_end - timedelta(seconds=10)).isoformat(),
                "fim": old_end.isoformat(),
            },
            "stages": {"etapa3": {"resultado": {"decisao": "INADMITIDO"}}},
        },
    )

    payload = obter_metricas_operacionais(snapshot_dir=snapshot_dir, period_days=30)

    assert payload["execucoes"]["total"] == 1
    assert payload["execucoes"]["com_decisao"] == 1
    assert payload["periodo_dias"] == 30
