"""Operational dashboard aggregation from execution snapshots."""

from __future__ import annotations

import csv
import json
import logging
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

from src.config import OUTPUTS_DIR
from src.pipeline import _estimar_custo

logger = logging.getLogger("assessor_ai")

CRITICAL_FIELDS_ETAPA1: tuple[str, ...] = ("numero_processo", "recorrente", "especie_recurso")
ESSENTIAL_FIELDS_ETAPA2: tuple[str, ...] = (
    "materia_controvertida",
    "conclusao_fundamentos",
    "obices_sumulas",
    "trecho_transcricao",
)
DECISAO_CATEGORIES: tuple[str, ...] = ("ADMITIDO", "INADMITIDO", "INCONCLUSIVO")


def _listar_snapshots(snapshot_dir: Path) -> list[Path]:
    """Return execution snapshot files sorted by path."""
    return sorted(p for p in snapshot_dir.rglob("snapshot_execucao_*.json") if p.is_file())


def _parse_iso_datetime(value: Any) -> datetime | None:
    """Parse ISO datetime string safely."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _calc_duration_seconds(metadata: dict[str, Any]) -> float:
    """Estimate execution duration using metadata start/end timestamps."""
    inicio = _parse_iso_datetime(metadata.get("inicio"))
    fim = _parse_iso_datetime(metadata.get("fim"))
    if inicio is None or fim is None:
        return 0.0
    return max(0.0, (fim - inicio).total_seconds())


def _extrair_decisao(snapshot: dict[str, Any]) -> str:
    """Extract stage 3 decision from snapshot."""
    stages = snapshot.get("stages", {})
    if not isinstance(stages, dict):
        return ""
    etapa3 = stages.get("etapa3", {})
    if not isinstance(etapa3, dict):
        return ""
    resultado = etapa3.get("resultado") or {}
    if not isinstance(resultado, dict):
        return ""
    decisao = str(resultado.get("decisao") or "").strip().upper()
    return decisao


def _snapshot_reference_datetime(snapshot: dict[str, Any]) -> datetime | None:
    """Resolve reference datetime for period filtering and weekly aggregation."""
    metadata = snapshot.get("metadata", {})
    if not isinstance(metadata, dict):
        return None
    return _parse_iso_datetime(metadata.get("fim")) or _parse_iso_datetime(metadata.get("inicio"))


def _collect_validation_alerts(snapshot: dict[str, Any]) -> list[str]:
    """Collect validation alerts from snapshot payload with best-effort parsing."""
    alerts: list[str] = []

    root_alerts = snapshot.get("alertas_validacao")
    if isinstance(root_alerts, list):
        alerts.extend(str(a).strip() for a in root_alerts if str(a).strip())

    validacoes = snapshot.get("validacoes")
    if isinstance(validacoes, dict):
        for erros in validacoes.values():
            if isinstance(erros, list):
                alerts.extend(str(a).strip() for a in erros if str(a).strip())

    metadata = snapshot.get("metadata", {})
    if isinstance(metadata, dict):
        metadata_alerts = metadata.get("alertas")
        if isinstance(metadata_alerts, list):
            alerts.extend(str(a).strip() for a in metadata_alerts if str(a).strip())

    stages = snapshot.get("stages", {})
    if isinstance(stages, dict):
        for stage_payload in stages.values():
            if not isinstance(stage_payload, dict):
                continue
            erros = stage_payload.get("validacao_erros")
            if isinstance(erros, list):
                alerts.extend(str(a).strip() for a in erros if str(a).strip())

    deduped = list(dict.fromkeys(alerts))
    return deduped


def _categorize_alert(alert: str) -> str:
    """Normalize alert messages to stable categories for top-k reporting."""
    text = " ".join(str(alert or "").strip().lower().split())
    if not text:
        return "outros"
    if ("seção" in text or "secao" in text) and (
        "não encontrada" in text or "nao encontrada" in text or "ausente" in text
    ):
        return "seção ausente"
    if "súmula" in text or "sumula" in text:
        if "não" in text or "nao" in text or "ausente" in text or "sem" in text:
            return "súmula não encontrada"
        return "súmula"
    if "evidência" in text or "evidencia" in text:
        return "evidência"
    if "inconclus" in text:
        return "inconclusivo"
    if "etapa 1" in text:
        return "etapa 1"
    if "etapa 2" in text:
        return "etapa 2"
    if "etapa 3" in text:
        return "etapa 3"
    if ":" in text:
        return text.split(":", 1)[0].strip()
    return text[:80]


def _resolve_week_key(reference_dt: datetime | None) -> str:
    """Return ISO week key used in weekly decision distribution."""
    if reference_dt is None:
        return "sem_data"
    iso_year, iso_week, _ = reference_dt.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _resolve_build_info() -> dict[str, str]:
    """Resolve CI/local build identifiers for dashboard traceability."""
    provider = "local"
    build_id = ""
    for key, provider_name in (
        ("GITHUB_RUN_ID", "github"),
        ("CI_PIPELINE_ID", "gitlab"),
        ("BUILD_ID", "generic"),
    ):
        value = str(os.getenv(key, "")).strip()
        if value:
            build_id = value
            provider = provider_name
            break

    commit_sha = (
        str(os.getenv("GITHUB_SHA", "")).strip()
        or str(os.getenv("CI_COMMIT_SHA", "")).strip()
        or str(os.getenv("COMMIT_SHA", "")).strip()
    )
    branch = (
        str(os.getenv("GITHUB_REF_NAME", "")).strip()
        or str(os.getenv("CI_COMMIT_REF_NAME", "")).strip()
        or str(os.getenv("BRANCH_NAME", "")).strip()
    )
    return {
        "provider": provider,
        "build_id": build_id,
        "commit_sha": commit_sha,
        "branch": branch,
    }


def _tem_valor_em_campo(payload: dict[str, Any], campo: str) -> bool:
    """Check whether a domain field contains useful value for evidence scoring."""
    if campo == "obices_sumulas":
        valor = payload.get(campo)
        if not isinstance(valor, list):
            return False
        return any(str(item).strip() for item in valor)
    return bool(str(payload.get(campo) or "").strip())


def _evidencia_completa(raw: Any) -> bool:
    """Validate required evidence attributes (citation, page and anchor)."""
    if not isinstance(raw, dict):
        return False
    citacao = str(raw.get("citacao_literal") or "").strip()
    ancora = str(raw.get("ancora") or "").strip()
    pagina = raw.get("pagina")
    return bool(citacao and ancora and isinstance(pagina, int) and pagina >= 1)


def _calc_evidence_coverage(snapshot: dict[str, Any]) -> tuple[int, int]:
    """Return (covered_fields, eligible_fields) evidence coverage for a snapshot."""
    covered = 0
    total = 0

    stages = snapshot.get("stages", {})
    if not isinstance(stages, dict):
        return covered, total
    etapa1_result = (stages.get("etapa1", {}) or {}).get("resultado") or {}
    if isinstance(etapa1_result, dict):
        evidencias = etapa1_result.get("evidencias_campos")
        evidencias_map = evidencias if isinstance(evidencias, dict) else {}
        for campo in CRITICAL_FIELDS_ETAPA1:
            if not _tem_valor_em_campo(etapa1_result, campo):
                continue
            total += 1
            if _evidencia_completa(evidencias_map.get(campo)):
                covered += 1

    etapa2_result = (stages.get("etapa2", {}) or {}).get("resultado") or {}
    temas = etapa2_result.get("temas") if isinstance(etapa2_result, dict) else []
    if isinstance(temas, list):
        for tema in temas:
            if not isinstance(tema, dict):
                continue
            evidencias = tema.get("evidencias_campos")
            evidencias_map = evidencias if isinstance(evidencias, dict) else {}
            for campo in ESSENTIAL_FIELDS_ETAPA2:
                if not _tem_valor_em_campo(tema, campo):
                    continue
                total += 1
                if _evidencia_completa(evidencias_map.get(campo)):
                    covered += 1

    return covered, total


def _load_snapshot_payloads(snapshot_dir: Path) -> tuple[list[Path], list[dict[str, Any]]]:
    """Load snapshot payloads from directory, ignoring invalid files."""
    snapshot_paths = _listar_snapshots(snapshot_dir)
    snapshots: list[dict[str, Any]] = []
    for path in snapshot_paths:
        try:
            snapshots.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            logger.warning("Snapshot inválido ignorado no dashboard: %s", path)
    return snapshot_paths, snapshots


def _filter_snapshots_by_period(
    snapshots: list[dict[str, Any]],
    *,
    period_days: int | None,
) -> list[dict[str, Any]]:
    """Filter snapshots by lookback period (in days) using snapshot metadata timestamps."""
    if period_days is None or period_days <= 0:
        return snapshots

    cutoff = datetime.now() - timedelta(days=period_days)
    filtered: list[dict[str, Any]] = []
    for snapshot in snapshots:
        reference_dt = _snapshot_reference_datetime(snapshot)
        if reference_dt is not None and reference_dt >= cutoff:
            filtered.append(snapshot)
    return filtered


def _build_dashboard_payload(
    snapshots: list[dict[str, Any]],
    *,
    period_days: int | None = None,
) -> dict[str, Any]:
    """Aggregate operational metrics from snapshot payloads."""
    total_exec = len(snapshots)

    durations: list[float] = []
    token_totals: list[int] = []
    costs: list[float] = []
    decisions: list[str] = []
    stage_errors = {"etapa1": 0, "etapa2": 0, "etapa3": 0}
    llm_total_calls = 0
    llm_total_truncadas = 0
    llm_latencias: list[float] = []
    evidence_covered_fields = 0
    evidence_total_fields = 0
    decisions_by_week: dict[str, Counter[str]] = defaultdict(Counter)
    minutas_com_alerta = 0
    alert_categories_counter: Counter[str] = Counter()

    for snapshot in snapshots:
        metadata = snapshot.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        prompt_tokens = int(metadata.get("prompt_tokens", 0) or 0)
        completion_tokens = int(metadata.get("completion_tokens", 0) or 0)
        total_tokens = int(metadata.get("total_tokens", 0) or 0)
        modelo = str(metadata.get("modelo_usado") or "gpt-4o")

        duration_s = _calc_duration_seconds(metadata)
        durations.append(duration_s)
        token_totals.append(total_tokens)
        costs.append(_estimar_custo(prompt_tokens, completion_tokens, modelo))

        decisao = _extrair_decisao(snapshot)
        if decisao:
            decisions.append(decisao)
            if decisao in DECISAO_CATEGORIES:
                week_key = _resolve_week_key(_snapshot_reference_datetime(snapshot))
                decisions_by_week[week_key][decisao] += 1

        stages = snapshot.get("stages", {})
        if not isinstance(stages, dict):
            stages = {}
        for etapa in ("etapa1", "etapa2", "etapa3"):
            etapa_payload = stages.get(etapa, {})
            if not isinstance(etapa_payload, dict):
                continue
            erros = etapa_payload.get("validacao_erros", [])
            if isinstance(erros, list) and erros:
                stage_errors[etapa] += 1

        alertas = _collect_validation_alerts(snapshot)
        if alertas:
            minutas_com_alerta += 1
            for alerta in alertas:
                categoria_alerta = _categorize_alert(alerta)
                if categoria_alerta:
                    alert_categories_counter[categoria_alerta] += 1

        llm_stats = metadata.get("llm_stats", {})
        if not isinstance(llm_stats, dict):
            llm_stats = {}
        llm_total_calls += int(llm_stats.get("total_calls", 0) or 0)
        llm_total_truncadas += int(llm_stats.get("calls_truncadas", 0) or 0)
        llm_latencias.append(float(llm_stats.get("latencia_media_ms", 0.0) or 0.0))

        covered, total = _calc_evidence_coverage(snapshot)
        evidence_covered_fields += covered
        evidence_total_fields += total

    inconclusivos = sum(1 for d in decisions if d == "INCONCLUSIVO")
    decisoes_conclusivas = len(decisions)
    top_5_alertas = [
        {"tipo": tipo, "quantidade": quantidade}
        for tipo, quantidade in sorted(
            alert_categories_counter.items(),
            key=lambda item: (-item[1], item[0]),
        )[:5]
    ]
    distribuicao_decisao_por_semana = []
    for semana in sorted(decisions_by_week):
        contagem = decisions_by_week[semana]
        distribuicao_decisao_por_semana.append(
            {
                "semana": semana,
                "ADMITIDO": int(contagem.get("ADMITIDO", 0)),
                "INADMITIDO": int(contagem.get("INADMITIDO", 0)),
                "INCONCLUSIVO": int(contagem.get("INCONCLUSIVO", 0)),
            }
        )

    dashboard = {
        "gerado_em": datetime.now().isoformat(),
        "build": _resolve_build_info(),
        "periodo_dias": period_days,
        "execucoes": {
            "total": total_exec,
            "com_decisao": decisoes_conclusivas,
        },
        "latencia": {
            "media_s": round(mean(durations), 3) if durations else 0.0,
            "max_s": round(max(durations), 3) if durations else 0.0,
            "min_s": round(min(durations), 3) if durations else 0.0,
        },
        "tokens": {
            "total": int(sum(token_totals)),
            "media_por_execucao": round(mean(token_totals), 2) if token_totals else 0.0,
        },
        "custo_estimado_usd": {
            "total": round(sum(costs), 6),
            "media_por_execucao": round(mean(costs), 6) if costs else 0.0,
        },
        "qualidade": {
            "taxa_inconclusivo": round((inconclusivos / total_exec), 3) if total_exec else 0.0,
            "erro_por_etapa": {
                "etapa1": round(stage_errors["etapa1"] / total_exec, 3) if total_exec else 0.0,
                "etapa2": round(stage_errors["etapa2"] / total_exec, 3) if total_exec else 0.0,
                "etapa3": round(stage_errors["etapa3"] / total_exec, 3) if total_exec else 0.0,
            },
            "retrabalho_retry": {
                "llm_calls_truncadas_total": llm_total_truncadas,
                "taxa_por_call": round(llm_total_truncadas / llm_total_calls, 3) if llm_total_calls else 0.0,
            },
            "cobertura_evidencia": {
                "campos_cobertos": evidence_covered_fields,
                "campos_avaliados": evidence_total_fields,
                "taxa": (
                    round(evidence_covered_fields / evidence_total_fields, 3)
                    if evidence_total_fields
                    else 0.0
                ),
            },
            "alertas_validacao": {
                "minutas_com_alerta": minutas_com_alerta,
                "minutas_avaliadas": total_exec,
                "taxa": round((minutas_com_alerta / total_exec), 3) if total_exec else 0.0,
                "top_5_tipos": top_5_alertas,
            },
        },
        "llm": {
            "calls_total": llm_total_calls,
            "calls_truncadas_total": llm_total_truncadas,
            "latencia_media_ms": round(mean(llm_latencias), 2) if llm_latencias else 0.0,
        },
        "distribuicao_decisao_por_semana": distribuicao_decisao_por_semana,
    }
    return dashboard


def _to_markdown(payload: dict[str, Any]) -> str:
    """Render markdown summary for operational dashboard."""
    build = payload["build"]
    execucoes = payload["execucoes"]
    latencia = payload["latencia"]
    tokens = payload["tokens"]
    custo = payload["custo_estimado_usd"]
    qualidade = payload["qualidade"]
    llm = payload["llm"]
    erro_etapa = qualidade["erro_por_etapa"]
    alertas_validacao = qualidade["alertas_validacao"]
    distribuicao = payload.get("distribuicao_decisao_por_semana", [])

    lines = [
        "# Dashboard Operacional",
        "",
        f"- Gerado em: {payload['gerado_em']}",
        f"- Build: {build['build_id'] or 'local'} ({build['provider']})",
        f"- Commit: {build['commit_sha'] or 'n/d'}",
        f"- Branch: {build['branch'] or 'n/d'}",
        f"- Execuções analisadas: {execucoes['total']}",
        f"- Execuções com decisão: {execucoes['com_decisao']}",
        "",
        "## Latência",
        "",
        f"- Média: {latencia['media_s']:.3f}s",
        f"- Mínima: {latencia['min_s']:.3f}s",
        f"- Máxima: {latencia['max_s']:.3f}s",
        "",
        "## Tokens",
        "",
        f"- Total: {tokens['total']}",
        f"- Média por execução: {tokens['media_por_execucao']}",
        "",
        "## Custo Estimado (USD)",
        "",
        f"- Total: ${custo['total']:.6f}",
        f"- Média por execução: ${custo['media_por_execucao']:.6f}",
        "",
        "## Qualidade",
        "",
        f"- Taxa de INCONCLUSIVO: {qualidade['taxa_inconclusivo']:.3f}",
        f"- Taxa de erro Etapa 1: {erro_etapa['etapa1']:.3f}",
        f"- Taxa de erro Etapa 2: {erro_etapa['etapa2']:.3f}",
        f"- Taxa de erro Etapa 3: {erro_etapa['etapa3']:.3f}",
        (
            "- Retry/retrabalho (proxy LLM truncada): "
            f"{qualidade['retrabalho_retry']['taxa_por_call']:.3f}"
        ),
        (
            "- Cobertura de evidência: "
            f"{qualidade['cobertura_evidencia']['taxa']:.3f} "
            f"({qualidade['cobertura_evidencia']['campos_cobertos']}/"
            f"{qualidade['cobertura_evidencia']['campos_avaliados']})"
        ),
        (
            "- Minutas com alertas de validação: "
            f"{alertas_validacao['taxa']:.3f} "
            f"({alertas_validacao['minutas_com_alerta']}/{alertas_validacao['minutas_avaliadas']})"
        ),
        "",
        "## LLM",
        "",
        f"- Calls totais: {llm['calls_total']}",
        f"- Calls truncadas: {llm['calls_truncadas_total']}",
        f"- Latência média: {llm['latencia_media_ms']:.2f} ms",
        "",
        "## Decisão por Semana",
        "",
    ]
    if distribuicao:
        for item in distribuicao:
            lines.append(
                "- "
                + f"{item['semana']}: "
                + f"ADMITIDO={item['ADMITIDO']}, "
                + f"INADMITIDO={item['INADMITIDO']}, "
                + f"INCONCLUSIVO={item['INCONCLUSIVO']}"
            )
    else:
        lines.append("- Sem decisões no período.")

    lines.extend(
        [
            "",
            "## Top Alertas de Validação",
            "",
        ]
    )
    if alertas_validacao["top_5_tipos"]:
        for item in alertas_validacao["top_5_tipos"]:
            lines.append(f"- {item['tipo']}: {item['quantidade']}")
    else:
        lines.append("- Sem alertas de validação no período.")
    lines.append("")
    return "\n".join(lines)


def _export_dashboard_csv(payload: dict[str, Any], destination: Path) -> None:
    """Export selected dashboard metrics as CSV for external analysis."""
    qualidade = payload.get("qualidade", {})
    alertas = qualidade.get("alertas_validacao", {})
    distribuicao = payload.get("distribuicao_decisao_por_semana", [])
    top_alertas = alertas.get("top_5_tipos", [])

    with destination.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("categoria", "metrica", "semana", "valor"),
        )
        writer.writeheader()
        writer.writerow(
            {
                "categoria": "alertas_validacao",
                "metrica": "minutas_com_alerta",
                "semana": "",
                "valor": int(alertas.get("minutas_com_alerta", 0) or 0),
            }
        )
        writer.writerow(
            {
                "categoria": "alertas_validacao",
                "metrica": "minutas_avaliadas",
                "semana": "",
                "valor": int(alertas.get("minutas_avaliadas", 0) or 0),
            }
        )
        writer.writerow(
            {
                "categoria": "alertas_validacao",
                "metrica": "taxa",
                "semana": "",
                "valor": float(alertas.get("taxa", 0.0) or 0.0),
            }
        )

        for weekly_item in distribuicao:
            semana = str(weekly_item.get("semana") or "")
            for decisao in DECISAO_CATEGORIES:
                writer.writerow(
                    {
                        "categoria": "distribuicao_decisao_por_semana",
                        "metrica": decisao,
                        "semana": semana,
                        "valor": int(weekly_item.get(decisao, 0) or 0),
                    }
                )

        for item in top_alertas:
            writer.writerow(
                {
                    "categoria": "top_alertas_validacao",
                    "metrica": str(item.get("tipo") or "outros"),
                    "semana": "",
                    "valor": int(item.get("quantidade", 0) or 0),
                }
            )


def obter_metricas_operacionais(
    *,
    snapshot_dir: Path | None = None,
    period_days: int | None = 30,
) -> dict[str, Any]:
    """Compute operational metrics payload, optionally filtered by lookback period."""
    source_dir = snapshot_dir or OUTPUTS_DIR
    _, snapshots = _load_snapshot_payloads(source_dir)
    snapshots_filtered = _filter_snapshots_by_period(snapshots, period_days=period_days)
    return _build_dashboard_payload(snapshots_filtered, period_days=period_days)


def gerar_dashboard_operacional(
    *,
    snapshot_dir: Path | None = None,
    output_dir: Path | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    """
    Generate operational dashboard (JSON + Markdown + CSV) from execution snapshots.

    Returns:
        Tuple (dashboard_json_path, dashboard_markdown_path, payload)
    """
    source_dir = snapshot_dir or OUTPUTS_DIR
    target_dir = output_dir or OUTPUTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    snapshot_paths, snapshots = _load_snapshot_payloads(source_dir)
    payload = _build_dashboard_payload(snapshots)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dashboard_json = target_dir / f"dashboard_operacional_{timestamp}.json"
    dashboard_md = target_dir / f"dashboard_operacional_{timestamp}.md"
    dashboard_csv = target_dir / f"dashboard_operacional_{timestamp}.csv"

    dashboard_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    dashboard_md.write_text(_to_markdown(payload), encoding="utf-8")
    _export_dashboard_csv(payload, dashboard_csv)

    logger.info(
        "📈 Dashboard operacional gerado: snapshots=%d json=%s md=%s csv=%s",
        len(snapshot_paths),
        dashboard_json,
        dashboard_md,
        dashboard_csv,
    )
    return dashboard_json, dashboard_md, payload
